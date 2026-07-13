# Fase 1 — Diferenciador de privacidad (PII) (diseño)

> Spec de implementación de la **Fase 1** del [roadmap 2026](../plans/roadmap-2026.md).
> Todo el trabajo cae en `backend/anonymizer.py` (una sola zona de código) + su
> cableado en `backend/main.py` + frontend (`anonymize.js`, `results.js`).
> Mantiene los principios del proyecto: **on-device**, import perezoso de los
> motores, **fuentes de verdad únicas** (`ENTITY_CONFIG`) y suite verde.

## Objetivo

Convertir la anonimización de una caja negra ("sale texto con `[NOMBRE]`") en una
herramienta con la que el usuario **ve qué se redactó**, puede pedir **etiquetas
coherentes** para preservar referencias, y puede **añadir sus propios términos**
que el NER no detecta. Es el mayor diferenciador del producto (confianza / RGPD).

**Hecho cuando:** cada archivo anonimizado devuelve un informe `{tipo: nº}` que la
UI muestra; existe un modo opcional de pseudonimización consistente
(`[PERSONA_1]`, `[PERSONA_2]`…); y el usuario puede redactar términos propios.
Tests nuevos en `test_anonymizer.py`.

---

## Estado base relevante

`anonymize_text(text, entity_keys) -> str` (anonymizer.py:369) hace: `analyze` →
construye `operators` (`replace` con el `tag` fijo de cada entidad) → `anonymize`
→ devuelve `.text`. `ENTITY_CONFIG` es la fuente de verdad (key/entity/label/tag/
default). En `main.py`, `_apply_anonymization(raw_text, anonymize, entities)`
llama a `anonymize_text` y el resultado entra en el dict de cada archivo. Ambos
endpoints aceptan `anonymize` (bool) y `anonymize_entities` (CSV de keys) como
`Form`.

---

## 1.1 Informe de anonimización `{tipo: nº ocurrencias}`

**Dónde salen los números:** el `EngineResult` que devuelve
`AnonymizerEngine.anonymize(...)` expone `.items`, una lista de las
sustituciones **realmente aplicadas** (tras la resolución de solapes de
Presidio), cada una con su `entity_type`. Contar desde ahí es exacto (no desde
los resultados crudos del analyzer, que pueden solaparse). Se agrupa por
`entity_type` y se mapea a la `key` de `ENTITY_CONFIG`.

**Nueva API interna** (reemplaza el retorno plano de `anonymize_text`):

```python
def anonymize_text(text, entity_keys, *, pseudonymize=False, custom_terms=None):
    """Devuelve (texto_anonimizado, informe) donde informe es {key: nº}."""
```

- Retorno **tupla** `(str, dict[str, int])`. El informe usa las `key` de
  `ENTITY_CONFIG` (más la key sintética `custom_terms`, ver 1.3). Solo incluye
  tipos con conteo ≥ 1.
- Retrocompatibilidad: los tests actuales que esperan un `str` se actualizan (es
  código interno del repo, no API pública). El endpoint construye la respuesta a
  partir de la tupla.

**Cableado (`main.py`):** `_apply_anonymization` propaga el informe. El dict de
cada archivo gana `anonymization_report: {key: nº}` (solo cuando se anonimiza).
El endpoint no necesita mapear a labels: el frontend ya tiene los labels vía
`/api/anonymizer-options`. Para `custom_terms` se añade una entrada sintética a
esa lista de opciones (o el frontend usa un label fijo "Términos propios").

**Frontend:** en el modal de resultado (`results.js`), bajo el badge de tokens,
una lista compacta "Anonimizado: N nombres, M DNIs, …" a partir de
`anonymization_report`. Sin datos → no se muestra.

---

## 1.2 Pseudonimización consistente (opcional)

**Qué:** en vez de sustituir todas las ocurrencias de un tipo por su `tag` fijo
(`[NOMBRE]`), numerar los **valores distintos** dentro del documento:
`[NOMBRE_1]`, `[NOMBRE_2]`… Así "Juan Pérez" es siempre `[NOMBRE_1]` en todo el
texto, preservando referencias — útil para que un LLM razone sobre el documento
sin ver los datos reales.

**Alcance:** aplica a **todos los tipos seleccionados** (no solo PERSON): dos
DNIs distintos → `[DNI_1]`, `[DNI_2]`. La base de la etiqueta se deriva del `tag`
existente (`[DNI]` → `[DNI_N]`), sin nueva fuente de verdad.

**Cómo:** operador `custom` de Presidio por entidad, con un contador con estado
por tipo. Para cada `key` seleccionada se crea una clausura con su propio
`dict valor→índice`:

```python
def _make_counter_operator(tag_base):        # tag_base = "DNI" (de "[DNI]")
    seen = {}
    def op(value):
        idx = seen.setdefault(value.strip(), len(seen) + 1)
        return f"[{tag_base}_{idx}]"
    return op
# operators[entity] = OperatorConfig("custom", {"lambda": op})
```

El estado vive **por llamada** a `anonymize_text` (por documento) → numeración
consistente dentro del doc, independiente entre documentos. El orden de
numeración depende del recorrido de Presidio; es estable e irrelevante para el
resultado.

**Activación:** nuevo `Form` bool `pseudonymize` (default `False`). Cuando es
`True`, se usan operadores contador; cuando es `False`, el `replace` de tag fijo
de siempre. Nueva casilla en la UI (`anonymize.js`), desmarcada por defecto,
visible solo cuando la anonimización está activa. El informe (1.1) sigue
contando por tipo igual.

---

## 1.3 Redacción de términos propios

**Qué:** el usuario aporta una lista de términos (un nombre de proyecto, un alias
interno…) que el NER no detecta, y se redactan con `[OCULTO]`.

**Decisión de seguridad (default): coincidencia LITERAL, no regex.** El roadmap
decía "palabras/regex", pero aceptar regex arbitrario del usuario en una
instancia **pública** es un vector de ReDoS (coherente con el endurecimiento de
la Fase 0, no lo reintroducimos). Por tanto: cada término se trata como cadena
literal, **case-insensitive**, escapada con `re.escape`, con límites de palabra
cuando el término es alfanumérico. Sustitución → `[OCULTO]`. *(Si en el futuro se
quiere regex, sería un entregable aparte con sandbox/timeout; no aquí.)*

**Entrada:** nuevo `Form` `custom_terms` (texto; términos separados por saltos de
línea o comas). Se parte, se limpian vacíos, se deduplica, y se limita el número
de términos (p. ej. `MAX_CUSTOM_TERMS = 100`) para acotar coste.

**Pipeline:** la redacción de términos se hace **después** de Presidio (sobre el
texto ya anonimizado), como parte de `anonymize_text`, para que: (a) cuente en el
informe bajo la key sintética `custom_terms` (label "Términos propios", tag
`[OCULTO]`); (b) funcione **aunque no haya ninguna entidad Presidio
seleccionada** (hoy `anonymize_text` devuelve el texto intacto si no hay keys —
se refactoriza para correr también si hay términos). El conteo es el nº de
sustituciones hechas por término, sumado.

**Frontend:** un `<textarea>` "Términos a ocultar (uno por línea)" en el panel de
anonimización, enviado en el FormData de cada archivo.

---

## Cableado común (`main.py`)

- Ambos endpoints aceptan dos `Form` nuevos: `pseudonymize: bool = Form(False)` y
  `custom_terms: str = Form("")`.
- `_apply_anonymization(raw_text, anonymize, entities, pseudonymize, custom_terms)`
  decide si hay algo que hacer: se anonimiza si `anonymize and (entities or
  custom_terms)`. Devuelve `(texto, informe)`; el informe se añade al dict del
  archivo como `anonymization_report`.
- Mismo patrón de error que hoy: motor no disponible (ImportError/OSError) →
  503 en single / entry en `errors` en multi.
- La compactación (Fase previa) y el conteo de tokens siguen igual, sobre el
  texto ya anonimizado.

## Fuentes de verdad / configuración

- `ENTITY_CONFIG` sigue siendo la fuente de verdad; el tag base de 1.2 se deriva
  de su `tag`. `custom_terms` es una key sintética documentada (no una entidad
  Presidio); se expone su label a la UI vía `available_options()` o un label fijo.
- Constante nueva `MAX_CUSTOM_TERMS` (100) junto a los límites de hardening.

## Tests (`tests/test_anonymizer.py`)

- 1.1: `anonymize_text` devuelve informe con conteos correctos (p. ej. 2 emails,
  1 DNI); tipos con 0 no aparecen; endpoint incluye `anonymization_report`.
- 1.2: con `pseudonymize=True`, dos valores distintos del mismo tipo → `_1`/`_2`;
  el mismo valor repetido → misma etiqueta; independencia entre llamadas.
- 1.3: términos propios literales se redactan case-insensitive; regex-like
  (`.*`) se trata literal (no como patrón); funciona sin entidades Presidio;
  respeta `MAX_CUSTOM_TERMS`; cuenta en el informe.
- Actualizar los tests existentes que esperaban el retorno `str` de
  `anonymize_text` al nuevo `(str, dict)`.

## Fuera de alcance (Fase 1)

- Regex de usuario (ReDoS) — futuro, con sandbox.
- Persistencia del mapeo de pseudónimos entre documentos/sesiones.
- Detección de nuevos tipos de entidad (eso es evolución de `ENTITY_CONFIG`, no
  esta fase).

## Orden de implementación sugerido

`1.1 (informe)` primero — expone los resultados del analyzer y refactoriza el
retorno a tupla, sobre el que se apoyan 1.2 y 1.3. Luego `1.2` y `1.3` (ambos
añaden un modo al mismo flujo). El plan (writing-plans) fija el orden definitivo.
