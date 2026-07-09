# Fase 0 — Cimientos y blindaje del despliegue público — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Blindar la instancia pública (rate limiting, `/healthz`, logging) y crear la red de seguridad (CI + smoke de frontend) sin romper los 64 tests actuales.

**Architecture:** Todo el trabajo de backend cae en `backend/main.py` (rate limiting con `slowapi` vía decorador + `key_func` que respeta `X-Forwarded-For`; `/healthz` barato con `shutil.which`; middleware de logging estructurado con stdlib). Los tests nuevos usan `TestClient`; un `conftest.py` apaga el limiter en la suite. CI es un workflow de GitHub Actions con `uv`.

**Tech Stack:** FastAPI 0.109, `slowapi`, stdlib `logging`/`shutil`, pytest + `TestClient`, GitHub Actions + `astral-sh/setup-uv`.

## Global Constraints

- **On-device:** sin servicios externos. `slowapi` es Python puro, sin binario.
- **Deps opcionales / import perezoso:** no romper el arranque si falta un motor. `slowapi` sí es dependencia dura (barata).
- **Fuentes de verdad únicas:** los límites y flags viven en constantes de `backend/main.py` leídas de env; no hardcodear en varios sitios.
- **Suite verde:** los 64 tests actuales siguen pasando; se añaden los nuevos. Comando: `uv run --all-extras pytest`.
- **Formato/lint:** `black` (line-length 100) y `ruff` (E,F,I,UP,B; ignore B008) deben pasar en `backend/` y `tests/`.
- **Python 3.13** en CI (el que fija el proyecto por spaCy 3.8).
- **Rate limit por defecto:** `20/minute` en endpoints de conversión; GET sin límite.

---

### Task 1: Rate limiting por IP (`slowapi`)

**Files:**
- Modify: `pyproject.toml` (añadir `slowapi` a `dependencies`)
- Modify: `backend/main.py` (constantes + limiter + decoradores + handler 429)
- Create: `tests/conftest.py`
- Test: `tests/test_rate_limit.py`

**Interfaces:**
- Produces: `RATE_LIMIT_CONVERT: str`, `RATE_LIMIT_ENABLED: bool`, `RATE_LIMIT_TRUST_FORWARDED_FOR: bool`, `_client_ip(request: Request) -> str`, `limiter: slowapi.Limiter`, `_rate_limit_handler(request, exc) -> JSONResponse` en `backend.main`.

- [ ] **Step 1: Añadir la dependencia**

En `pyproject.toml`, dentro de `[project].dependencies`, añadir tras `python-dotenv>=1.0.1`:

```toml
    "slowapi>=0.1.9",
```

Luego instalar:

```bash
uv sync --all-extras
```

Expected: `slowapi` y su dep `limits` quedan instaladas sin conflicto.

- [ ] **Step 2: Crear `tests/conftest.py` que apaga el limiter para la suite**

`pytest` importa `conftest.py` antes que los módulos de test, así que fijar el env aquí garantiza que `backend.main` lo lea desactivado (todas las llamadas de test salen de `127.0.0.1` y un limiter activo las sumaría entre tests).

```python
import os

# El limiter cuenta por IP; en los tests todo sale de 127.0.0.1, así que un
# límite real sumaría las llamadas entre tests y provocaría 429 espurios.
# Se apaga globalmente; el test dedicado de rate limiting instancia su propio
# Limiter activo para verificar el 429.
os.environ.setdefault("RATE_LIMIT_ENABLED", "0")
```

- [ ] **Step 3: Escribir el test que falla**

`tests/test_rate_limit.py`:

```python
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
```

- [ ] **Step 4: Ejecutar el test para verlo fallar**

Run: `uv run --all-extras pytest tests/test_rate_limit.py -v`
Expected: FAIL — `ImportError: cannot import name '_client_ip'` (aún no existe).

- [ ] **Step 5: Implementar en `backend/main.py`**

Añadir el import de `os` ya existe. Tras el bloque de imports (junto a `from backend import compactor, ocr, pdf_markdown`), añadir:

```python
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
```

Junto a las constantes de hardening (tras `MAX_FILENAME_LEN = 255`), añadir:

```python
# Rate limiting (instancia pública tras proxy Apache/Plesk).
RATE_LIMIT_CONVERT = os.getenv("RATE_LIMIT_CONVERT", "20/minute")
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") != "0"
RATE_LIMIT_TRUST_FORWARDED_FOR = os.getenv("RATE_LIMIT_TRUST_FORWARDED_FOR", "1") != "0"
```

Tras crear `app = FastAPI(title="MarkItDown GUI")`, añadir el limiter y el handler:

```python
def _client_ip(request: Request) -> str:
    """IP real del cliente para rate limiting.

    Tras el proxy Apache/Plesk, request.client.host es el proxy (una sola IP).
    Se lee el primer valor de X-Forwarded-For (convención leftmost = cliente
    original); en local sin proxy cae a la IP directa. Desactivable por env
    (RATE_LIMIT_TRUST_FORWARDED_FOR=0) si el despliegue no es de confianza.
    """
    if RATE_LIMIT_TRUST_FORWARDED_FOR:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip, enabled=RATE_LIMIT_ENABLED)
app.state.limiter = limiter


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 con JSON claro cuando se supera el límite."""
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
```

Aplicar el decorador a los tres endpoints de conversión (el `@app.post` va arriba, `@limiter.limit` justo debajo). En `@app.post("/api/convert")`:

```python
@app.post("/api/convert")
@limiter.limit(RATE_LIMIT_CONVERT)
async def convert_files(
    request: Request,
    ...
```

En `@app.post("/api/convert-single")`:

```python
@app.post("/api/convert-single")
@limiter.limit(RATE_LIMIT_CONVERT)
async def convert_single_file(
    request: Request,
    ...
```

En `@app.post("/api/zip")` — verificar que su firma tiene `request: Request`; si no lo tiene, añadirlo como primer parámetro (slowapi lo exige para leer la IP):

```python
@app.post("/api/zip")
@limiter.limit(RATE_LIMIT_CONVERT)
async def create_zip(request: Request, ...):
    ...
```

- [ ] **Step 6: Ejecutar los tests nuevos**

Run: `uv run --all-extras pytest tests/test_rate_limit.py -v`
Expected: PASS (los 3).

- [ ] **Step 7: Ejecutar la suite completa (no regresión)**

Run: `uv run --all-extras pytest`
Expected: PASS — 64 previos + 3 nuevos. Si algún test de convert diera 429, revisar que `conftest.py` fija `RATE_LIMIT_ENABLED=0`.

- [ ] **Step 8: Lint + formato**

Run: `uv run ruff check backend/ tests/ && uv run black --check backend/ tests/`
Expected: sin errores.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock backend/main.py tests/conftest.py tests/test_rate_limit.py
git commit -m "feat(seguridad): rate limiting por IP con slowapi (20/min en conversión)"
```

---

### Task 2: `/healthz` + logging estructurado

**Files:**
- Modify: `backend/main.py` (config de logging, middleware de request, endpoint `/healthz`)
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: `_client_ip` (Task 1).
- Produces: endpoint `GET /healthz` → `{status, version, checks:{tesseract,ffmpeg}}`; `logger` (`logging.Logger`) en `backend.main`.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_health.py`:

```python
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
```

- [ ] **Step 2: Ejecutar el test para verlo fallar**

Run: `uv run --all-extras pytest tests/test_health.py -v`
Expected: FAIL — `/healthz` devuelve 404.

- [ ] **Step 3: Implementar logging + endpoint en `backend/main.py`**

Añadir a los imports de la cabecera:

```python
import logging
import shutil
import time
```

Tras la creación de `app` y del limiter, configurar logging una vez:

```python
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("markitdown_gui")
```

Añadir un middleware de logging (junto a `add_no_cache_headers`). No registra nombres de archivo ni cuerpos (evita PII en logs):

```python
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Una línea estructurada por request: method, path, status, duración, IP."""
    start = time.perf_counter()
    response = await call_next(request)
    dur_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "request method=%s path=%s status=%s dur_ms=%.1f ip=%s",
        request.method,
        request.url.path,
        response.status_code,
        dur_ms,
        _client_ip(request),
    )
    return response
```

Añadir el endpoint `/healthz` (junto a los otros GET). Usa `shutil.which` (barato) y **no** carga spaCy/Tesseract/Whisper:

```python
@app.get("/healthz")
async def healthz():
    """Readiness ligero: vivo + qué binarios de sistema hay. No carga modelos."""
    return JSONResponse(
        {
            "status": "ok",
            "version": app.version,
            "checks": {
                "tesseract": shutil.which("tesseract") is not None,
                "ffmpeg": shutil.which("ffmpeg") is not None,
            },
        }
    )
```

- [ ] **Step 4: Ejecutar los tests nuevos**

Run: `uv run --all-extras pytest tests/test_health.py -v`
Expected: PASS (los 2).

- [ ] **Step 5: Suite completa + lint/formato**

Run: `uv run --all-extras pytest && uv run ruff check backend/ tests/ && uv run black --check backend/ tests/`
Expected: todo verde.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/test_health.py
git commit -m "feat(observabilidad): /healthz ligero + logging estructurado por request"
```

---

### Task 3: Smoke de frontend (ligero, sin navegador)

**Files:**
- Test: `tests/test_frontend_smoke.py`

**Interfaces:**
- Consumes: `app` (`TestClient`), estructura real de `frontend/static/`.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_frontend_smoke.py`. Recorre los assets reales en disco para detectar módulos referenciados pero no servidos, o renombrados. `styles.css`/`script.js` son los índices (viven en `frontend/static/`), los parciales bajo `js/` y `css/` (incl. subdir `components/`):

```python
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
STATIC = Path(__file__).resolve().parent.parent / "frontend" / "static"


def test_index_references_entry_assets():
    html = client.get("/").text
    assert 'href="static/styles.css"' in html
    assert 'src="static/script.js"' in html


def test_all_js_modules_are_served():
    modules = sorted((STATIC / "js").glob("*.js"))
    assert modules, "no se encontraron módulos JS en disco"
    for js in modules:
        r = client.get(f"/static/js/{js.name}")
        assert r.status_code == 200, f"no servido: js/{js.name}"


def test_all_css_partials_are_served():
    partials = sorted((STATIC / "css").rglob("*.css"))
    assert partials, "no se encontraron parciales CSS en disco"
    for css in partials:
        rel = css.relative_to(STATIC).as_posix()  # incluye components/...
        r = client.get(f"/static/{rel}")
        assert r.status_code == 200, f"no servido: {rel}"


def test_index_has_key_js_anchors():
    html = client.get("/").text
    assert 'id="contentModal"' in html  # el <dialog> del modal de preview
    assert "data-action=" in html  # delegación de eventos
```

- [ ] **Step 2: Ejecutar los tests**

Run: `uv run --all-extras pytest tests/test_frontend_smoke.py -v`
Expected: PASS (los 4) — la app ya sirve estos assets; el smoke fija el contrato.

- [ ] **Step 3: Suite completa + lint/formato**

Run: `uv run --all-extras pytest && uv run ruff check backend/ tests/ && uv run black --check backend/ tests/`
Expected: todo verde.

- [ ] **Step 4: Commit**

```bash
git add tests/test_frontend_smoke.py
git commit -m "test(frontend): smoke ligero de assets y anclajes clave del index"
```

---

### Task 4: CI — GitHub Actions

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `uv`, `pyproject.toml`, la suite completa.

- [ ] **Step 1: Crear el workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Instalar deps de sistema (OCR + audio)
        run: |
          sudo apt-get update
          sudo apt-get install -y tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng ffmpeg

      - name: Instalar uv (con caché)
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Instalar Python 3.13
        run: uv python install 3.13

      - name: Sincronizar dependencias
        run: uv sync --all-extras

      - name: Ruff (lint)
        run: uv run ruff check backend/ tests/

      - name: Black (formato)
        run: uv run black --check backend/ tests/

      - name: Pytest
        run: uv run --all-extras pytest
```

- [ ] **Step 2: Validar la sintaxis del YAML localmente**

Run: `uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"`
Expected: `yaml ok`. (Si `yaml` no está disponible, saltar — GitHub validará al push.)

- [ ] **Step 3: Verificar que los mismos comandos pasan en local**

Run: `uv run ruff check backend/ tests/ && uv run black --check backend/ tests/ && uv run --all-extras pytest`
Expected: todo verde (replica lo que hará CI, salvo la instalación de sistema).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: lint (ruff), formato (black) y tests (pytest) en cada push/PR"
```

---

### Task 5: Documentación (CLAUDE.md)

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Documentar los añadidos de la Fase 0**

En `CLAUDE.md`, sección de arquitectura del backend, añadir viñetas (adaptar al estilo existente):

- **Rate limiting:** `slowapi` limita `/api/convert`, `/api/convert-single`, `/api/zip` a `RATE_LIMIT_CONVERT` (default `20/minute`) por IP. La IP se obtiene con `_client_ip`, que respeta `X-Forwarded-For` (leftmost) tras el proxy Apache/Plesk; configurable con `RATE_LIMIT_TRUST_FORWARDED_FOR`. `RATE_LIMIT_ENABLED=0` lo apaga (lo hace `tests/conftest.py`). Superarlo → 429.
- **`/healthz`:** readiness barato (`shutil.which` para tesseract/ffmpeg); no carga spaCy/Tesseract/Whisper.
- **Logging:** stdlib `logging` (`LOG_LEVEL`, default INFO); middleware `log_requests` emite una línea por request (method/path/status/dur_ms/ip); no registra nombres de archivo (sin PII en logs).
- **CI:** `.github/workflows/ci.yml` corre ruff + black + pytest con `uv` en Python 3.13; instala tesseract+langpacks y ffmpeg para los tests reales de OCR/audio.
- **Tests:** `test_rate_limit.py`, `test_health.py`, `test_frontend_smoke.py`. Al cambiar las constantes `RATE_LIMIT_*`, actualizar `test_rate_limit.py`.

En la sección de dependencias, mencionar `slowapi` (Python puro, sin binario).

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: documenta rate limiting, /healthz, logging, CI y smoke tests (Fase 0)"
```

---

## Cierre de la fase

- [ ] Suite completa verde: `uv run --all-extras pytest` (64 + ~9 nuevos).
- [ ] Lint/formato verde: `uv run ruff check backend/ tests/ && uv run black --check backend/ tests/`.
- [ ] Integración a `main` según el flujo habitual (branch → push → `gh pr create` → `gh pr merge --squash --delete-branch` → sync main). Verificar que el workflow de CI corre verde en el PR.
