from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from backend.main import _client_ip, _rate_limit_handler


def test_client_ip_uses_rightmost_hop_ignoring_spoofed_leftmost(monkeypatch):
    """El proxy Apache/Plesk APPENDS la IP real; no la reemplaza. La entrada
    más a la izquierda la controla el cliente. Con RATE_LIMIT_TRUSTED_PROXIES=1
    (default), rotar el valor izquierdo NO debe cambiar la clave del limiter:
    si lo hiciera, un atacante podría evadir el límite por completo cambiando
    ese valor en cada request."""
    monkeypatch.setattr("backend.main.RATE_LIMIT_TRUST_FORWARDED_FOR", True)
    monkeypatch.setattr("backend.main.RATE_LIMIT_TRUSTED_PROXIES", 1)

    class _Req:
        def __init__(self, xff):
            self.headers = {"x-forwarded-for": xff}
            self.client = type("C", (), {"host": "10.0.0.1"})()

    real_ip = "203.0.113.9"
    for spoofed_leftmost in ("FAKE1", "1.2.3.4", "attacker-controlled-value", "FAKE2"):
        req = _Req(f"{spoofed_leftmost}, {real_ip}")
        assert _client_ip(req) == real_ip


def test_client_ip_trusted_proxies_configurable(monkeypatch):
    """Con N proxies de confianza, la IP real está a N posiciones desde la
    derecha, incluso si el cliente antepone entradas falsas."""
    monkeypatch.setattr("backend.main.RATE_LIMIT_TRUST_FORWARDED_FOR", True)
    monkeypatch.setattr("backend.main.RATE_LIMIT_TRUSTED_PROXIES", 2)

    class _Req:
        headers = {"x-forwarded-for": "spoofed, 203.0.113.5, 198.51.100.1"}
        client = type("C", (), {"host": "10.0.0.1"})()

    # 2 proxies de confianza -> el real es el penúltimo desde la derecha.
    assert _client_ip(_Req()) == "203.0.113.5"


def test_client_ip_ignores_forwarded_for_when_trust_disabled(monkeypatch):
    monkeypatch.setattr("backend.main.RATE_LIMIT_TRUST_FORWARDED_FOR", False)
    monkeypatch.setattr("backend.main.RATE_LIMIT_TRUSTED_PROXIES", 1)

    class _Req:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = type("C", (), {"host": "192.0.2.55"})()

    assert _client_ip(_Req()) == "192.0.2.55"


def test_client_ip_falls_back_when_no_forwarded_for_header(monkeypatch):
    monkeypatch.setattr("backend.main.RATE_LIMIT_TRUST_FORWARDED_FOR", True)
    monkeypatch.setattr("backend.main.RATE_LIMIT_TRUSTED_PROXIES", 1)

    class _Req:
        headers = {}
        client = type("C", (), {"host": "192.0.2.77"})()

    assert _client_ip(_Req()) == "192.0.2.77"


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


def test_convert_limiter_429_includes_retry_after_header():
    app = FastAPI()
    limiter = Limiter(key_func=_client_ip, enabled=True)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    @app.post("/probe")
    @limiter.limit("1/minute")
    async def probe(request: Request):
        return {"ok": True}

    client = TestClient(app)
    assert client.post("/probe").status_code == 200
    r = client.post("/probe")
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    assert int(r.headers["Retry-After"]) > 0


def test_app_has_limiter_wired():
    from backend.main import app

    assert hasattr(app.state, "limiter")


def test_convert_endpoints_actually_carry_rate_limit_decorator():
    """Verifica que /api/convert, /api/convert-single y /api/zip llevan de verdad
    el decorador @limiter.limit, introspeccionando los límites que slowapi
    registró en app.state.limiter (no una app separada). Si se borra el
    decorador de cualquiera de los tres endpoints, este test debe fallar."""
    from backend.main import app

    real_limiter = app.state.limiter
    registered = set(real_limiter._route_limits.keys()) | set(
        real_limiter._dynamic_route_limits.keys()
    )
    expected = {
        "backend.main.convert_files",
        "backend.main.convert_single_file",
        "backend.main.create_zip",
    }
    missing = expected - registered
    assert not missing, f"Falta @limiter.limit en: {missing}"
