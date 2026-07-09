# Roadmap — nuevas funcionalidades MarkItDown GUI

> Roadmap por fases para la evolución de la app, ordenado por dependencias,
> riesgo y valor. Mantiene los principios del proyecto: **on-device** (sin
> servicios externos), dependencias opcionales con **import perezoso** (+503 si
> falta el motor), **fuentes de verdad únicas** (`SUPPORTED_EXTENSIONS`,
> `ENTITY_CONFIG`, `TOKEN_PLATFORMS`) y **tests verdes** en cada fase.

**Convenciones de esfuerzo:** S (≤1 día) · M (2-4 días) · L (1-2 semanas).
Cada fase deja la app entregable y la suite (64+ tests) en verde.

---

## Estado actual (línea base)

Wrapper FastAPI sobre MarkItDown que convierte ~24 formatos a Markdown, todo
on-device, pensado para preparar documentos para LLMs.

Cadena por archivo: subida en streaming → extracción (OCR/PDF/markitdown) →
anonimización PII opcional → compactación sin pérdida → resultado con estimación
de tokens. Capacidades: Office/PDF/texto/EPUB/ZIP/audio, OCR Tesseract
`spa+eng`, PII Presidio+spaCy con recognizers propios (DNI/NIE, IBAN, NSS, CIF,
matrícula, fecha…), compactación stdlib, tokens heurísticos (4 plataformas),
descarga `.md`/`.zip`. Hardening: límites de tamaño/lote, sanitización de
nombres, gzip, no-cache.

**Huecos detectados:** audio vía SpeechRecognition online (baja calidad, rompe
on-device); OCR de idioma fijo y sin detección de PDF escaneado; PII sin informe
de lo redactado, sin términos propios, sin etiquetas coherentes; tokens solo
heurísticos sin coste; salida solo `.md`; despliegue público sin rate limiting /
`/healthz` / logging; UI solo en español (→ Fase 5).

---

## Fase 0 — Cimientos y blindaje del despliegue público

*Por qué primero: la instancia pública (md.encodigo.es) está expuesta sin
protección, y CI da red de seguridad para todo lo demás. Bajo riesgo, alto
apalancamiento.*

| #   | Entregable | Deps nuevas | Esf. | Riesgo |
|-----|------------|-------------|------|--------|
| 0.1 | **Rate limiting** por IP en `/api/*` | `slowapi` | S | Bajo |
| 0.2 | **`/healthz`** (readiness) + **logging estructurado** | stdlib `logging` | S | Bajo |
| 0.3 | **CI** (GitHub Actions: ruff + black + pytest) | — | S | Bajo |
| 0.4 | **Tests de frontend** mínimos (smoke DOM/Playwright) | `playwright` (dev) | M | Medio |

**Hecho cuando:** la API rechaza ráfagas con 429, `/healthz` responde 200, y
cada push corre lint+tests en verde.

---

## Fase 1 — Diferenciador de privacidad (PII)

*Por qué aquí: es el mayor diferenciador del producto y todo cae en
`anonymizer.py` (una sola zona de código). Construye confianza/RGPD.*

| #   | Entregable | Deps | Esf. | Riesgo |
|-----|------------|------|------|--------|
| 1.1 | **Informe de anonimización** `{tipo: nº ocurrencias}` en API + modal | — | M | Bajo |
| 1.2 | **Pseudonimización consistente** opcional (`[PERSONA_1]`, `[PERSONA_2]`…) | Presidio | M | Medio |
| 1.3 | **Redacción de términos propios** (palabras/regex del usuario) | — | M | Bajo |

**Dependencia interna:** 1.1 primero (expone los resultados del analyzer); 1.2 y
1.3 reutilizan ese flujo.
**Hecho cuando:** el usuario ve qué se redactó, puede elegir etiquetas coherentes
y añadir términos propios. Tests nuevos en `test_anonymizer.py`.

---

## Fase 2 — Preparación para LLM (tokens y coste)

*Por qué aquí: refuerza el caso de uso central y es mayormente frontend, sin
tocar el pipeline de conversión.*

| #   | Entregable | Deps | Esf. | Riesgo |
|-----|------------|------|------|--------|
| 2.1 | **Conteo exacto** ("modo preciso") con tokenizers reales | `tiktoken` (opcional, lazy) | M | Bajo |
| 2.2 | **Estimación de coste** €/$ por plataforma | — (tabla de precios) | S | Bajo |

**Hecho cuando:** junto a la heurística aparece el conteo real y un coste
estimado por modelo. Precios en una fuente de verdad única (como
`TOKEN_PLATFORMS`).

---

## Fase 3 — Calidad de conversión (audio + OCR)

*Por qué más tarde: el mayor salto de calidad, pero introduce modelos pesados;
conviene tener CI y rate limiting ya en marcha.*

| #   | Entregable | Deps | Esf. | Riesgo |
|-----|------------|------|------|--------|
| 3.1 | **Transcripción local con Whisper** (sustituye SpeechRecognition online) | `faster-whisper` + modelo | L | Medio |
| 3.2 | **Selector de idioma OCR** en la UI (hoy fijo `spa+eng`) | — | S | Bajo |
| 3.3 | **Detección de PDF escaneado** → rutar páginas-imagen a Tesseract | — (lógica) | M | Medio |

**Dependencia interna:** 3.2 antes que 3.3 (reusa la selección de idioma).
**Hecho cuando:** el audio se transcribe offline con calidad y los PDF escaneados
ya no salen vacíos. Patrón lazy-import + 503; actualizar `install-*.sh` y
CLAUDE.md.

---

## Fase 4 — Expansión de salida

*Por qué al final: depende de un binario externo y no bloquea nada anterior.*

| #   | Entregable | Deps | Esf. | Riesgo |
|-----|------------|------|------|--------|
| 4.1 | **Export round-trip** (md → docx/pdf/html) | `pandoc` (binario sistema) | M | Medio |
| 4.2 | **Vista diff** original vs anonimizado | — | S | Bajo |

**Hecho cuando:** se descarga el resultado en otros formatos además de `.md`.

---

## Fase 5 — Internacionalización de la UI (i18n)

*Por qué al final: es transversal a toda la UI pero no añade motor de backend ni
bloquea nada; conviene hacerlo cuando las features (y por tanto las cadenas de
texto) ya están estables, para no traducir una UI que aún cambia. Mantiene el
principio on-device: nada de servicios de traducción externos.*

| #   | Entregable | Deps | Esf. | Riesgo |
|-----|------------|------|------|--------|
| 5.1 | **Catálogo de cadenas** (fuente de verdad única, p. ej. `frontend/static/i18n/{es,en}.json`); ninguna cadena hardcodeada en HTML/JS | — | M | Bajo |
| 5.2 | **Selector de idioma** ES/EN en la UI, con detección del navegador y persistencia en `localStorage` | — | S | Bajo |

**Dependencia interna:** 5.1 antes que 5.2 (el selector necesita el catálogo).
**Nota de alcance:** solo UI. El contenido convertido (Markdown) y los mensajes
de error del backend quedan fuera; si más adelante se quieren localizar los
errores de API, sería un entregable aparte.
**Hecho cuando:** la UI alterna ES/EN sin cadenas hardcodeadas, con ES por
defecto y la elección persistida. Nuevos smoke-tests de frontend (reusan lo de
0.4).

---

## Cuestiones transversales (en cada fase)

- **On-device:** nada de servicios externos por defecto (Whisper/tiktoken en local).
- **Deps opcionales:** import perezoso + 503 si falta el motor (patrón establecido).
- **Fuentes de verdad únicas:** ampliar `SUPPORTED_EXTENSIONS`/`ENTITY_CONFIG`/`TOKEN_PLATFORMS`, no hardcodear en la UI.
- **Instaladores y docs:** cada dependencia de sistema nueva (pandoc, modelos) →
  actualizar `install-fedora.sh`/`install-ubuntu.sh` + CLAUDE.md, y revalidar en
  contenedor.

---

## Secuencia recomendada

**0 → 1 → 2 → 3 → 4 → 5.** Si se prioriza impacto visible sobre blindaje, se
puede adelantar la **Fase 1** dejando 0.3/0.4 (CI/tests) en paralelo. Lo único
que **no** conviene retrasar es **0.1 (rate limiting)** si la instancia pública
ya recibe tráfico. La **Fase 5 (i18n)** va la última a propósito: traducir la UI
antes de que las features se estabilicen obliga a re-traducir.
