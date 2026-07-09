# Fase 0 — Cimientos y blindaje del despliegue público (diseño)

> Spec de implementación de la **Fase 0** del [roadmap 2026](../plans/roadmap-2026.md).
> Los cuatro entregables (0.1–0.4) se tratan como un único spec cohesivo
> ("cimientos"), pero se implementan de forma incremental dejando los tests en
> verde en cada paso. Mantiene los principios del proyecto: **on-device**, deps
> opcionales con import perezoso, **fuentes de verdad únicas** y suite verde.

## Objetivo

Blindar la instancia pública (`md.encodigo.es`, tras proxy Apache/Plesk) y crear
la red de seguridad (CI + smoke tests) sobre la que se construyen el resto de
fases. Bajo riesgo, alto apalancamiento.

**Hecho cuando:** la API rechaza ráfagas con `429`, `/healthz` responde `200`,
cada push corre lint+tests en verde, y un smoke de frontend cubre el arranque de
la UI.

---

## 0.1 Rate limiting por IP — `slowapi`

**Dependencia nueva (producción):** `slowapi` (Python puro, sin binario de
sistema; `uv sync` la instala).

**Alcance:** límite `20/minute` por IP en los endpoints de conversión:
`/api/convert`, `/api/convert-single`, `/api/zip`. Los GET
(`/api/supported-formats`, `/api/anonymizer-options`, `/healthz`, estáticos y
`/`) quedan **sin límite**.

**IP real tras proxy:** el despliegue va detrás de Apache/Plesk, así que
`request.client.host` es el proxy (una sola IP) y limitaría global en vez de por
cliente. Se usa una `key_func` propia:

```python
def _client_ip(request: Request) -> str:
    if RATE_LIMIT_TRUST_FORWARDED_FOR:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()  # leftmost = cliente original
    return get_remote_address(request)
```

Asunción: el proxy es de confianza (convención leftmost de `X-Forwarded-For`). Un
cliente podría falsear la cabecera para evadir *su propio* límite; tras un proxy
de confianza es el estándar aceptado y queda desactivable por env. En local sin
proxy (sin cabecera) cae a la IP directa.

**Fuentes de verdad / configuración** (constantes junto a las de hardening en
`backend/main.py`, leídas de env con default):

| Constante | Env | Default | Qué controla |
|-----------|-----|---------|--------------|
| `RATE_LIMIT_CONVERT` | `RATE_LIMIT_CONVERT` | `"20/minute"` | Límite aplicado a los endpoints de conversión |
| `RATE_LIMIT_ENABLED` | `RATE_LIMIT_ENABLED` | `1` (true) | Interruptor global (los tests lo apagan) |
| `RATE_LIMIT_TRUST_FORWARDED_FOR` | `RATE_LIMIT_TRUST_FORWARDED_FOR` | `1` (true) | Si se lee `X-Forwarded-For` |

**Integración FastAPI:** `Limiter(key_func=_client_ip, enabled=RATE_LIMIT_ENABLED)`
en `app.state.limiter`; handler de `RateLimitExceeded` registrado que devuelve
**429** con JSON claro (`{"detail": "Rate limit exceeded: <límite>"}`). Los
endpoints de conversión llevan `@limiter.limit(RATE_LIMIT_CONVERT)` (requieren
`request: Request` en la firma — ya lo tienen por `_check_request_size`).

**Test-friendly:** todas las llamadas de la suite salen de `127.0.0.1`, así que
un limiter activo a 20/min las sumaría entre tests y rompería la suite. Solución:
`tests/conftest.py` fija `RATE_LIMIT_ENABLED=0` para toda la suite; un test
dedicado instancia la app con el limiter activo y un límite mínimo (p. ej.
`2/minute`) y verifica que la 3ª llamada devuelve `429`.

---

## 0.2 `/healthz` + logging estructurado

**`/healthz`** (liveness + readiness ligero):

```json
{ "status": "ok", "version": "<app.version>",
  "checks": { "tesseract": true, "ffmpeg": true } }
```

`200` siempre que el proceso vive. Los `checks` usan `shutil.which` (baratísimo)
para reportar la presencia de binarios de sistema. **No** dispara la carga de
spaCy/Tesseract/Whisper: un healthcheck no debe colgarse cargando un modelo de
570 MB. Sin límite de rate, incluido en el schema (`/docs`).

**Logging** con stdlib `logging`, configurado una vez al arranque (helper
`_configure_logging()`):

- Nivel por env `LOG_LEVEL` (default `INFO`).
- Formato estructurado con timestamp, nivel, logger y mensaje.
- Middleware ligero (o ampliación del existente) que registra **una línea por
  request**: `method`, `path`, `status`, `dur_ms`, `ip` (la misma `_client_ip`).
- Sin dependencias nuevas. No registra cuerpos ni nombres de archivo (evita PII
  en logs, coherente con el foco de privacidad del producto).

---

## 0.3 CI — GitHub Actions

`.github/workflows/ci.yml`, disparado en `push` y `pull_request`.

- Runner `ubuntu-latest`, Python **3.13** (el que fija el proyecto vía uv; spaCy
  3.8).
- Pasos:
  1. `actions/checkout`.
  2. `astral-sh/setup-uv` con caché habilitada (reutiliza el modelo
     `es_core_news_lg` ~570 MB, que es dependencia del `pyproject`, entre runs).
  3. `apt-get install -y tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng
     ffmpeg` — para que los tests reales de OCR (gated en `shutil.which`) y de
     audio corran en CI en vez de saltarse.
  4. `uv sync --all-extras`.
  5. `uv run ruff check backend/ tests/`.
  6. `uv run black --check backend/ tests/`.
  7. `uv run --all-extras pytest`.
- Falla el job si cualquier paso falla (lint, formato o tests).

---

## 0.4 Smoke de frontend (ligero, sin navegador)

`tests/test_frontend_smoke.py` con `fastapi.testclient.TestClient` — **cero
dependencias nuevas**, no ejecuta JS real (eso queda para una futura fase con
Playwright si hiciera falta):

1. `GET /` sirve `index.html` referenciando `static/script.js` (módulo ESM) y
   `static/styles.css`.
2. Recorre los `.js` bajo `frontend/static/js/` y los `.css` bajo
   `frontend/static/css/` **en disco** y verifica que `/static/js/<x>` y
   `/static/css/<x>` responden `200` (detecta módulos referenciados pero no
   servidos, o renombrados).
3. Valida un puñado de anclajes clave del HTML que el JS necesita para arrancar
   (el `<dialog>` del modal de preview y al menos un hook `data-action` de la
   delegación de eventos).

---

## Cambios transversales

- **`CLAUDE.md`**: documentar rate limiting (constantes, `X-Forwarded-For`),
  `/healthz`, logging, el workflow de CI y el smoke de frontend. Añadir a la nota
  de "cuándo actualizar tests" los nuevos disparadores (constantes de rate
  limit).
- **`pyproject.toml`**: añadir `slowapi` a `dependencies`.
- **`tests/conftest.py`**: nuevo (o ampliado) para apagar el limiter en la suite.
- **Suite objetivo:** los 64 tests actuales + los nuevos (rate-limit 429,
  healthz, ~3 de smoke de frontend), todos en verde.

## Fuera de alcance (Fase 0)

- Playwright / browser tests reales (se reconsidera en una fase posterior).
- Rate limiting distribuido (Redis): la instancia es única, in-memory basta.
- Localización de logs o de errores de API (Fase 5 y más allá).

## Orden de implementación sugerido

`0.3 (CI)` primero da red de seguridad inmediata, luego `0.1`, `0.2`, `0.4`.
Alternativamente `0.1 → 0.2 → 0.4 → 0.3` para no correr CI sobre features a
medias. El plan de implementación (writing-plans) fija el orden definitivo.
