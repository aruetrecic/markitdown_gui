"""OCR de imágenes con Tesseract (vía pytesseract).

markitdown NO hace OCR: su conversor de imágenes solo extrae metadatos EXIF
(si hay exiftool instalado) o una descripción mediante un LLM (si se le pasa un
`llm_client`). Por eso, al subir una imagen sin ninguna de esas dos cosas,
`text_content` sale vacío. Para extraer el TEXTO visible de la imagen usamos
Tesseract en local, sin servicios externos — coherente con la anonimización
on-device del resto de la app.

El binario `tesseract` y los paquetes de idioma deben estar instalados en el
sistema. En Fedora:

    sudo dnf install tesseract tesseract-langpack-spa tesseract-langpack-eng

Si faltan pytesseract/Pillow (ImportError) o el binario `tesseract` (OSError),
`ocr_image` lo propaga para que la API responda 503 en lugar de un 500 opaco,
igual que hace el anonimizador cuando su motor no está disponible.
"""

from __future__ import annotations

# Extensiones de imagen que pasamos por OCR (subconjunto de SUPPORTED_EXTENSIONS).
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

# Idiomas por defecto: español + inglés (cubre nóminas/formularios y texto técnico).
DEFAULT_LANG = "spa+eng"


def is_image(extension: str) -> bool:
    """True si la extensión (con punto) corresponde a una imagen que pasamos por OCR."""
    return extension.lower() in IMAGE_EXTENSIONS


def ocr_image(path: str, lang: str = DEFAULT_LANG) -> str:
    """Extrae el texto de una imagen con Tesseract y lo devuelve como texto plano.

    Lanza:
      - ImportError si pytesseract/Pillow no están instalados.
      - OSError si el binario `tesseract` no está disponible en el sistema.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:  # pragma: no cover - depende del entorno
        raise ImportError("OCR no disponible: faltan pytesseract/Pillow. Ejecuta 'uv sync'.") from e

    try:
        with Image.open(path) as img:
            text = pytesseract.image_to_string(img, lang=lang)
    except pytesseract.TesseractNotFoundError as e:
        raise OSError(
            "Tesseract no está instalado. En Fedora: "
            "sudo dnf install tesseract tesseract-langpack-spa tesseract-langpack-eng"
        ) from e

    return text.strip()
