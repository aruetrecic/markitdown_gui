import io
import zipfile

from fastapi.testclient import TestClient

from backend.main import (
    MAX_CUSTOM_TERMS,
    MAX_FILE_SIZE,
    MAX_FILES_PER_BATCH,
    SUPPORTED_EXTENSIONS,
    _parse_custom_terms,
    app,
)

client = TestClient(app)


def test_root_serves_index_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<html" in r.text.lower()


def test_static_assets_mounted():
    css = client.get("/static/styles.css")
    js = client.get("/static/script.js")
    assert css.status_code == 200
    assert js.status_code == 200
    # Los módulos ES viven en subdirectorios servidos por el mismo montaje /static
    module = client.get("/static/js/main.js")
    assert module.status_code == 200


def test_responses_are_gzipped():
    r = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert "accept-encoding" in r.headers.get("vary", "").lower()


def test_supported_formats_endpoint():
    r = client.get("/api/supported-formats")
    assert r.status_code == 200
    body = r.json()
    assert body["formats"] == SUPPORTED_EXTENSIONS
    assert set(body["extensions"]) == set(SUPPORTED_EXTENSIONS.keys())


def test_convert_single_rejects_unsupported_extension():
    r = client.post(
        "/api/convert-single",
        files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "not supported" in r.json()["detail"].lower()


def test_convert_single_converts_text_file():
    r = client.post(
        "/api/convert-single",
        files={"file": ("hello.txt", b"hola mundo", "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["original_filename"] == "hello.txt"
    assert body["markdown_filename"] == "hello.md"
    assert body["extension"] == ".txt"
    assert "hola mundo" in body["markdown_content"]


def test_convert_multi_collects_errors_alongside_results():
    r = client.post(
        "/api/convert",
        files=[
            ("files", ("a.txt", b"alpha", "text/plain")),
            ("files", ("b.exe", b"\x00\x00", "application/octet-stream")),
        ],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_files"] == 2
    assert body["successful"] == 1
    assert body["failed"] == 1
    assert body["results"][0]["original_filename"] == "a.txt"
    assert body["errors"][0]["filename"] == "b.exe"


def test_convert_multi_requires_at_least_one_file():
    r = client.post("/api/convert", files=[])
    assert r.status_code == 422


def test_convert_single_rejects_oversized_file():
    payload = b"x" * (MAX_FILE_SIZE + 1)
    r = client.post(
        "/api/convert-single",
        files={"file": ("big.txt", payload, "text/plain")},
    )
    assert r.status_code == 413
    assert "too large" in r.json()["detail"].lower()


def test_convert_multi_rejects_too_many_files():
    files = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(MAX_FILES_PER_BATCH + 1)]
    r = client.post("/api/convert", files=files)
    assert r.status_code == 400
    assert "too many" in r.json()["detail"].lower()


def test_convert_multi_oversized_file_lands_in_errors_not_results():
    files = [
        ("files", ("ok.txt", b"contenido", "text/plain")),
        ("files", ("big.txt", b"x" * (MAX_FILE_SIZE + 1), "text/plain")),
    ]
    r = client.post("/api/convert", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["successful"] == 1
    assert body["failed"] == 1
    assert body["errors"][0]["filename"] == "big.txt"
    assert "too large" in body["errors"][0]["error"].lower()


def test_zip_packages_files_and_returns_application_zip():
    r = client.post(
        "/api/zip",
        json={
            "files": [
                {"filename": "uno.md", "content": "# uno\n"},
                {"filename": "dos.md", "content": "# dos\n"},
            ]
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "conversiones.zip" in r.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = sorted(zf.namelist())
        assert names == ["dos.md", "uno.md"]
        assert zf.read("uno.md").decode() == "# uno\n"


def test_zip_dedupes_colliding_filenames():
    r = client.post(
        "/api/zip",
        json={
            "files": [
                {"filename": "doc.md", "content": "primero"},
                {"filename": "doc.md", "content": "segundo"},
                {"filename": "doc.md", "content": "tercero"},
            ]
        },
    )
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = sorted(zf.namelist())
        assert names == ["doc (2).md", "doc (3).md", "doc.md"]


def test_zip_strips_path_traversal_in_filename():
    r = client.post(
        "/api/zip",
        json={
            "files": [
                {"filename": "../../etc/passwd.md", "content": "no escapes"},
                {"filename": "..\\..\\windows\\system32\\evil.md", "content": "tampoco"},
            ]
        },
    )
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        for name in zf.namelist():
            assert not name.startswith("/")
            assert not name.startswith("..")
            assert "/" not in name
            assert "\\" not in name


def test_zip_appends_md_suffix_if_missing():
    r = client.post(
        "/api/zip",
        json={"files": [{"filename": "sin_extension", "content": "x"}]},
    )
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.namelist() == ["sin_extension.md"]


def test_zip_rejects_empty_payload():
    r = client.post("/api/zip", json={"files": []})
    assert r.status_code == 400


def test_zip_rejects_too_many_files():
    files = [{"filename": f"f{i}.md", "content": "x"} for i in range(MAX_FILES_PER_BATCH + 1)]
    r = client.post("/api/zip", json={"files": files})
    assert r.status_code == 400


def test_filename_with_html_is_sanitized_in_response():
    # El backend debe quitar caracteres de control; los caracteres < > " ' & se preservan
    # como texto pero el frontend los escapa antes de inyectar en innerHTML.
    payload_name = "evil\x00\n<img src=x>.txt"
    r = client.post(
        "/api/convert-single",
        files={"file": (payload_name, b"hola", "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    # Los caracteres de control han sido eliminados
    assert "\x00" not in body["original_filename"]
    assert "\n" not in body["original_filename"]
    assert "\x00" not in body["markdown_filename"]
    # Los <, >, etc. siguen presentes (es responsabilidad del cliente escaparlos al renderizar)
    assert "<img" in body["original_filename"]


def test_parse_custom_terms_dedup_and_cap():
    """Test _parse_custom_terms dedup, casing, and cap behavior."""
    raw = "a,A\nb, b , " + ",".join(f"t{i}" for i in range(150))
    out = _parse_custom_terms(raw)
    assert out[0] == "a"  # first-seen casing kept
    assert out.count("a") + out.count("A") == 1  # deduped case-insensitively
    assert len(out) == MAX_CUSTOM_TERMS  # capped at 100
