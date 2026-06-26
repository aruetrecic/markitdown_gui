import io
import os
import tempfile
import zipfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from markitdown import MarkItDown
from pydantic import BaseModel, Field

from backend import compactor, ocr, pdf_markdown

# Límites para mitigar DoS por documentos grandes o lotes masivos
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB por archivo
MAX_FILES_PER_BATCH = 50
MAX_FILENAME_LEN = 255

# Crear aplicación FastAPI
app = FastAPI(title="MarkItDown GUI")

# Comprime las respuestas (Markdown, JSON y estáticos de texto) cuando el cliente
# acepta gzip. El Markdown y el CSS/JS comprimen mucho; ahorra ancho de banda de
# bajada. minimum_size evita comprimir respuestas diminutas (overhead inútil).
app.add_middleware(GZipMiddleware, minimum_size=500)

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    """Fuerza revalidación de HTML/JS/CSS en el navegador.

    Sin esto, tras cambiar el frontend el navegador puede servir versiones
    obsoletas desde caché (síntoma típico: errores de funciones inexistentes o
    estilos viejos hasta hacer Ctrl+Shift+R). `no-cache` no impide cachear: el
    navegador revalida con el ETag/Last-Modified que ya emite StaticFiles, así
    que se reusa el archivo (304) si no cambió y se recarga (200) si cambió.
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


# Plugins desactivados: cargarían cualquier paquete instalado y amplían
# la superficie de ataque sin necesidad real aquí.
md = MarkItDown(enable_plugins=False)


def _safe_filename(name: str | None) -> str:
    """Sanitizar nombre antes de reflejarlo en respuestas, sugerencia de descarga, o miembro de zip.

    - Quita componentes de ruta (defensa contra path-traversal y zip-slip).
    - Elimina caracteres de control ASCII (rompen el render del frontend y nombres de zip).
    - Trunca a MAX_FILENAME_LEN.
    """
    if not name:
        return "file"
    # Strip path components (unix y windows). basename solo cubre el separador del SO actual.
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(c for c in name if ord(c) >= 0x20 and ord(c) != 0x7F)
    cleaned = cleaned[:MAX_FILENAME_LEN]
    return cleaned or "file"


def _check_request_size(request: Request) -> None:
    """Rechaza temprano por Content-Length si excede el presupuesto del lote."""
    cl = request.headers.get("content-length")
    if cl is None:
        return
    try:
        size = int(cl)
    except ValueError:
        return
    if size > MAX_FILE_SIZE * MAX_FILES_PER_BATCH:
        raise HTTPException(status_code=413, detail="Request body too large")


_UPLOAD_CHUNK = 1024 * 1024  # 1 MB


class _FileTooLarge(Exception):
    """El upload supera MAX_FILE_SIZE (detectado al vuelo durante el streaming)."""


async def _stream_to_tempfile(file: UploadFile, suffix: str) -> str:
    """Vuelca el upload a un archivo temporal por trozos, sin cargarlo entero en
    memoria, aplicando el límite de tamaño mientras se escribe.

    Devuelve la ruta del temp. Lanza `_FileTooLarge` (tras limpiar el temp) si el
    contenido supera MAX_FILE_SIZE.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        tmp_path = tmp_file.name
        size = 0
        while True:
            chunk = await file.read(_UPLOAD_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_FILE_SIZE:
                tmp_file.close()
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise _FileTooLarge()
            tmp_file.write(chunk)
    return tmp_path


def _parse_entities(raw: str) -> list[str]:
    """Convierte 'email,person, dni_nie' en ['email', 'person', 'dni_nie']."""
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def _apply_anonymization(text: str, anonymize: bool, entities: list[str]) -> str:
    """Aplica anonimización si se pidió. Import perezoso de Presidio."""
    if not anonymize or not entities:
        return text
    from backend.anonymizer import anonymize_text

    return anonymize_text(text, entities)


def _compact(text: str, enabled: bool) -> str:
    """Compacta el Markdown si se pidió (limpieza sin pérdida)."""
    if not enabled:
        return text
    return compactor.compact_markdown(text)


def _extract_markdown(tmp_path: str, file_extension: str) -> str:
    """Extrae el contenido del documento como texto.

    Las imágenes pasan por OCR (Tesseract), ya que markitdown no reconoce el texto
    de una imagen y devolvería contenido vacío.

    Los PDF se enrutan a pymupdf4llm, que produce Markdown estructurado (títulos,
    tablas) conservando la cabecera/pie —cosas que markitdown no da: por pdfminer
    sale texto plano, y por la vía DOCX se pierde la cabecera/pie (mammoth la
    ignora). Si pymupdf4llm falla o no está instalado, o no extrae nada, se cae a
    markitdown para no empeorar nunca respecto al comportamiento previo.

    El resto de formatos los maneja markitdown. Puede lanzar ImportError/OSError
    si el motor OCR no está disponible.
    """
    if ocr.is_image(file_extension):
        return ocr.ocr_image(tmp_path)
    if file_extension.lower() == ".pdf":
        try:
            text = pdf_markdown.pdf_to_markdown(tmp_path)
        except Exception:
            text = ""
        if text.strip():
            return text
        # Fallback: pymupdf4llm no disponible / falló / sin contenido.
    return md.convert(tmp_path).text_content


# Extensiones soportadas
SUPPORTED_EXTENSIONS = {
    # Documentos
    ".pdf": "PDF",
    ".docx": "Word",
    ".doc": "Word",
    ".pptx": "PowerPoint",
    ".ppt": "PowerPoint",
    ".xlsx": "Excel",
    ".xls": "Excel",
    ".csv": "CSV",
    # Imágenes
    ".jpg": "Image",
    ".jpeg": "Image",
    ".png": "Image",
    ".gif": "Image",
    ".bmp": "Image",
    ".webp": "Image",
    # Audio
    ".mp3": "Audio",
    ".wav": "Audio",
    ".m4a": "Audio",
    # Texto
    ".txt": "Text",
    ".json": "JSON",
    ".xml": "XML",
    ".html": "HTML",
    ".htm": "HTML",
    ".md": "Markdown",
    ".epub": "EPUB",
    ".zip": "ZIP",
}


def _unsupported_format_msg() -> str:
    """Mensaje de error para una extensión no soportada (listando las válidas)."""
    return f"Format not supported. Supported formats: {', '.join(SUPPORTED_EXTENSIONS.keys())}"


@app.get("/")
async def root():
    """Servir la página principal"""
    return FileResponse("frontend/index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Sirve el SVG como favicon también en /favicon.ico para clientes que no leen el <link>."""
    return FileResponse("frontend/static/favicon.svg", media_type="image/svg+xml")


@app.get("/api/supported-formats")
async def get_supported_formats():
    """Obtener lista de formatos soportados"""
    return JSONResponse(
        {"formats": SUPPORTED_EXTENSIONS, "extensions": list(SUPPORTED_EXTENSIONS.keys())}
    )


@app.get("/api/anonymizer-options")
async def get_anonymizer_options():
    """Tipos de datos sensibles que se pueden anonimizar (para el frontend)."""
    from backend.anonymizer import available_options

    return JSONResponse({"options": available_options()})


@app.post("/api/convert")
async def convert_files(
    request: Request,
    files: list[UploadFile] = File(...),
    anonymize: bool = Form(False),
    anonymize_entities: str = Form(""),
    compact: bool = Form(True),
):
    """
    Convertir múltiples archivos a Markdown.
    Detecta automáticamente la extensión y convierte individualmente.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    entities = _parse_entities(anonymize_entities)

    if len(files) > MAX_FILES_PER_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {MAX_FILES_PER_BATCH})",
        )

    _check_request_size(request)

    results = []
    errors = []

    for file in files:
        safe_name = _safe_filename(file.filename)
        try:
            file_extension = Path(file.filename or "").suffix.lower()

            if file_extension not in SUPPORTED_EXTENSIONS:
                errors.append({"filename": safe_name, "error": _unsupported_format_msg()})
                continue

            try:
                tmp_path = await _stream_to_tempfile(file, file_extension)
            except _FileTooLarge:
                errors.append(
                    {
                        "filename": safe_name,
                        "error": f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)} MB)",
                    }
                )
                continue

            try:
                raw_text = _extract_markdown(tmp_path, file_extension)
                filename_without_ext = _safe_filename(Path(file.filename or "").stem)
                text_content = _apply_anonymization(raw_text, anonymize, entities)
                original_chars = len(text_content)
                text_content = _compact(text_content, compact)

                results.append(
                    {
                        "original_filename": safe_name,
                        "format": SUPPORTED_EXTENSIONS.get(file_extension, "Unknown"),
                        "extension": file_extension,
                        "markdown_content": text_content,
                        "markdown_filename": f"{filename_without_ext}.md",
                        "anonymized": bool(anonymize and entities),
                        "original_chars": original_chars,
                        "compacted": compact,
                        "status": "success",
                    }
                )
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        except Exception as e:
            errors.append({"filename": safe_name, "error": str(e)})

    return JSONResponse(
        {
            "results": results,
            "errors": errors,
            "total_files": len(files),
            "successful": len(results),
            "failed": len(errors),
        }
    )


@app.post("/api/convert-single")
async def convert_single_file(
    request: Request,
    file: UploadFile = File(...),
    anonymize: bool = Form(False),
    anonymize_entities: str = Form(""),
    compact: bool = Form(True),
):
    """Convertir un único archivo a Markdown"""
    _check_request_size(request)
    entities = _parse_entities(anonymize_entities)

    try:
        file_extension = Path(file.filename or "").suffix.lower()

        if file_extension not in SUPPORTED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=_unsupported_format_msg())

        try:
            tmp_path = await _stream_to_tempfile(file, file_extension)
        except _FileTooLarge:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)} MB)",
            ) from None

        try:
            filename_without_ext = _safe_filename(Path(file.filename or "").stem)
            try:
                raw_text = _extract_markdown(tmp_path, file_extension)
            except (ImportError, OSError) as e:
                raise HTTPException(
                    status_code=503,
                    detail=f"OCR no disponible: {e}",
                ) from e
            try:
                text_content = _apply_anonymization(raw_text, anonymize, entities)
            except (ImportError, OSError) as e:
                raise HTTPException(
                    status_code=503,
                    detail=f"Anonimización no disponible: {e}",
                ) from e

            original_chars = len(text_content)
            text_content = _compact(text_content, compact)

            return JSONResponse(
                {
                    "original_filename": _safe_filename(file.filename),
                    "format": SUPPORTED_EXTENSIONS.get(file_extension, "Unknown"),
                    "extension": file_extension,
                    "markdown_content": text_content,
                    "markdown_filename": f"{filename_without_ext}.md",
                    "anonymized": bool(anonymize and entities),
                    "original_chars": original_chars,
                    "compacted": compact,
                    "status": "success",
                }
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


class ZipFileEntry(BaseModel):
    filename: str = Field(..., max_length=MAX_FILENAME_LEN * 2)
    content: str


class ZipRequest(BaseModel):
    files: list[ZipFileEntry]


def _unique_zip_name(name: str, taken: set[str]) -> str:
    """Devuelve un nombre que no colisione con los ya usados, añadiendo sufijo (2), (3), ..."""
    if name not in taken:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    i = 2
    while True:
        candidate = f"{stem} ({i}).{ext}" if ext else f"{stem} ({i})"
        if candidate not in taken:
            return candidate
        i += 1


@app.post("/api/zip")
async def create_zip(request: Request, payload: ZipRequest):
    """Empaquetar varios .md generados por el cliente en un único zip."""
    _check_request_size(request)

    if not payload.files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(payload.files) > MAX_FILES_PER_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {MAX_FILES_PER_BATCH})",
        )

    buf = io.BytesIO()
    taken: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in payload.files:
            name = _safe_filename(entry.filename)
            if not name.lower().endswith(".md"):
                name = f"{name}.md"
            name = _unique_zip_name(name, taken)
            taken.add(name)
            zf.writestr(name, entry.content)

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="conversiones.zip"'},
    )


if __name__ == "__main__":
    # Ruta de import completa: el módulo es backend.main, no main, así que
    # `uv run python -m backend.main` resuelve la app correctamente con reload.
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
