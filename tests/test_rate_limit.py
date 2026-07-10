from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from backend.main import _client_ip, _rate_limit_handler


def test_client_ip_prefers_forwarded_for(monkeypatch):
    monkeypatch.setattr("backend.main.RATE_LIMIT_TRUST_FORWARDED_FOR", True)

    class _Req:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = type("C", (), {"host": "10.0.0.1"})()

    assert _client_ip(_Req()) == "203.0.113.7"


def test_convert_limiter_returns_429_when_exceeded():
    # App mínima que reusa el key_func y el handler reales con un límite diminuto.
    app = FastAPI()
    limiter = Limiter(key_func=_client_ip, enabled=True)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    @app.post("/probe")
    @limiter.limit("2/minute")
    async def probe(request: Request):
        return {"ok": True}

    client = TestClient(app)
    assert client.post("/probe").status_code == 200
    assert client.post("/probe").status_code == 200
    r = client.post("/probe")
    assert r.status_code == 429
    assert "Rate limit exceeded" in r.json()["detail"]


def test_app_has_limiter_wired():
    from backend.main import app

    assert hasattr(app.state, "limiter")
