from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_healthz_ok():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert set(body["checks"]) == {"tesseract", "ffmpeg"}
    assert all(isinstance(v, bool) for v in body["checks"].values())


def test_request_is_logged(caplog):
    with caplog.at_level("INFO", logger="markitdown_gui"):
        client.get("/healthz")
    assert any("path=/healthz" in rec.message for rec in caplog.records)
