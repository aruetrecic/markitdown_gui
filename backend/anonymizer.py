"""Anonimización de datos sensibles (PII) sobre el Markdown convertido.

Usa Microsoft Presidio (analyzer + anonymizer) con spaCy `es_core_news_lg` para
NER de nombres/ubicaciones en texto libre, más reconocedores propios y
deterministas para los datos estructurados típicos de documentos oficiales
españoles (nóminas, formularios):

- DNI/NIE con validación de la letra de control.
- IBAN español tolerante a espacios/agrupamiento irregular, con checksum mod-97.
- Nombre de persona a partir de etiquetas como "Nombre:" / "Apellidos:" /
  "Titular:", que el NER se salta cuando vienen en MAYÚSCULAS.

Los motores de Presidio son caros de construir, así que se inicializan de forma
perezosa (singleton) en la primera llamada a `anonymize_text`: importar este
módulo no carga el modelo.
"""

from __future__ import annotations

import re
from threading import Lock

# Configuración de tipos soportados. Fuente de verdad para el frontend y para el
# mapeo entidad Presidio -> etiqueta de reemplazo.
# key: clave usada por la API/UI; entity: nombre de entidad en Presidio;
# label: texto legible para la UI; tag: con qué se sustituye en el texto;
# default: si la casilla viene marcada por defecto en la UI.
ENTITY_CONFIG = [
    {
        "key": "dni_nie",
        "entity": "ES_DNI_NIE",
        "label": "DNI / NIE",
        "tag": "[DNI]",
        "default": True,
    },
    {
        "key": "email",
        "entity": "EMAIL_ADDRESS",
        "label": "Email",
        "tag": "[EMAIL]",
        "default": True,
    },
    {
        "key": "person",
        "entity": "PERSON",
        "label": "Nombre de persona",
        "tag": "[NOMBRE]",
        "default": True,
    },
    {
        "key": "phone",
        "entity": "PHONE_NUMBER",
        "label": "Teléfono",
        "tag": "[TELEFONO]",
        "default": True,
    },
    {"key": "iban", "entity": "IBAN_CODE", "label": "IBAN", "tag": "[IBAN]", "default": True},
    {
        "key": "credit_card",
        "entity": "CREDIT_CARD",
        "label": "Tarjeta de crédito",
        "tag": "[TARJETA]",
        "default": True,
    },
    # LOCATION es ruidoso sobre tablas con el NER, por eso viene desmarcado.
    {
        "key": "location",
        "entity": "LOCATION",
        "label": "Dirección / ubicación",
        "tag": "[DIRECCION]",
        "default": False,
    },
    {"key": "ip", "entity": "IP_ADDRESS", "label": "Dirección IP", "tag": "[IP]", "default": True},
    {
        "key": "social_security",
        "entity": "ES_NSS",
        "label": "Nº Seguridad Social",
        "tag": "[NSS]",
        "default": True,
    },
    {
        "key": "company_id",
        "entity": "ES_CIF",
        "label": "CIF / NIF de empresa",
        "tag": "[CIF]",
        "default": True,
    },
    {
        "key": "vehicle_plate",
        "entity": "ES_PLATE",
        "label": "Matrícula",
        "tag": "[MATRICULA]",
        "default": True,
    },
    # DATE_TIME es ruidoso (marca cualquier fecha), por eso viene desmarcado.
    {
        "key": "date",
        "entity": "DATE_TIME",
        "label": "Fecha",
        "tag": "[FECHA]",
        "default": False,
    },
]

_BY_KEY = {e["key"]: e for e in ENTITY_CONFIG}

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"

# Etiquetas que preceden a un nombre de persona en documentos estructurados.
# Captura el valor de la línea (sin la etiqueta), parándose en salto de línea o
# en una barra de tabla markdown.
_NAME_LABEL_RX = re.compile(
    r"(?im)^[ \t>|]*(?:nombre y apellidos|nombre|apellidos?|titular|"
    r"trabajador(?:/?a)?|empleado(?:/?a)?)\s*:\s*(?P<val>\S[^\n|]*?)\s*$"
)

_engines = None  # (analyzer, anonymizer) una vez inicializados
_engines_lock = Lock()


def available_options() -> list[dict]:
    """Lista de tipos disponibles para el frontend: [{key, label, default}]."""
    return [{"key": e["key"], "label": e["label"], "default": e["default"]} for e in ENTITY_CONFIG]


def _valid_dni_nie(text: str) -> bool:
    """Valida un DNI (8 dígitos + letra) o NIE (X/Y/Z + 7 dígitos + letra)
    comprobando la letra de control."""
    t = text.strip().upper()
    if len(t) != 9:
        return False
    body, letter = t[:-1], t[-1]
    if body[0] in ("X", "Y", "Z"):
        num = str("XYZ".index(body[0])) + body[1:]
    else:
        num = body
    if not num.isdigit():
        return False
    return letter == _DNI_LETTERS[int(num) % 23]


def _valid_iban_es(text: str) -> bool:
    """Valida un IBAN español (ES + 22 dígitos) por su checksum mod-97,
    ignorando espacios/separadores."""
    s = re.sub(r"\s+", "", text).upper()
    if not re.fullmatch(r"ES\d{22}", s):
        return False
    rearranged = s[4:] + s[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def _valid_nss(text: str) -> bool:
    """Valida un Nº de la Seguridad Social (12 dígitos): los 2 últimos son el
    control de los 10 primeros (provincia + número) por módulo 97."""
    digits = re.sub(r"\D", "", text)
    if len(digits) != 12:
        return False
    return int(digits[10:]) == int(digits[:10]) % 97


def _valid_cif(text: str) -> bool:
    """Valida un CIF español (letra de organización + 7 dígitos + control)."""
    s = text.strip().upper()
    if not re.fullmatch(r"[ABCDEFGHJKLMNPQRSUVW]\d{7}[0-9A-J]", s):
        return False
    letter, digits, control = s[0], s[1:8], s[8]
    suma_par = sum(int(digits[i]) for i in (1, 3, 5))
    suma_impar = 0
    for i in (0, 2, 4, 6):
        doble = int(digits[i]) * 2
        suma_impar += doble // 10 + doble % 10
    dc = (10 - (suma_par + suma_impar) % 10) % 10
    control_letter = "JABCDEFGHI"[dc]
    if letter in "PQRSNW":  # control siempre letra
        return control == control_letter
    if letter in "ABEH":  # control siempre número
        return control == str(dc)
    return control == str(dc) or control == control_letter


def _build_dni_nie_recognizer():
    from presidio_analyzer import Pattern, PatternRecognizer

    class DniNieRecognizer(PatternRecognizer):
        """Reconocedor de DNI/NIE español con validación de letra de control."""

        def __init__(self):
            patterns = [Pattern("DNI/NIE", r"\b[XYZ]?[0-9]{7,8}[A-Za-z]\b", 0.3)]
            super().__init__(
                supported_entity="ES_DNI_NIE",
                patterns=patterns,
                supported_language="es",
            )

        def validate_result(self, pattern_text: str):
            return _valid_dni_nie(pattern_text)

    return DniNieRecognizer()


def _build_iban_recognizer():
    from presidio_analyzer import Pattern, PatternRecognizer

    class TolerantIbanRecognizer(PatternRecognizer):
        """IBAN español tolerante a espacios/agrupamiento, validado por mod-97."""

        def __init__(self):
            patterns = [Pattern("ES IBAN", r"\bES\d{2}(?:[ \t]*\d){20}\b", 0.5)]
            super().__init__(
                supported_entity="IBAN_CODE",
                patterns=patterns,
                supported_language="es",
            )

        def validate_result(self, pattern_text: str):
            return _valid_iban_es(pattern_text)

    return TolerantIbanRecognizer()


def _build_labeled_person_recognizer():
    from presidio_analyzer import EntityRecognizer, RecognizerResult

    class LabeledPersonRecognizer(EntityRecognizer):
        """Detecta nombres tras etiquetas ("Nombre:", "Apellidos:", "Titular:"),
        que el NER se salta cuando van en MAYÚSCULAS o como 'APELLIDOS, NOMBRE'."""

        def __init__(self):
            super().__init__(
                supported_entities=["PERSON"],
                supported_language="es",
                name="LabeledPersonRecognizer",
            )

        def load(self) -> None:
            pass

        def analyze(self, text, entities, nlp_artifacts=None):
            results = []
            if "PERSON" not in entities:
                return results
            for m in _NAME_LABEL_RX.finditer(text):
                start, end = m.span("val")
                results.append(
                    RecognizerResult(entity_type="PERSON", start=start, end=end, score=0.95)
                )
            return results

    return LabeledPersonRecognizer()


def _build_nss_recognizer():
    from presidio_analyzer import Pattern, PatternRecognizer

    class NssRecognizer(PatternRecognizer):
        """Nº de la Seguridad Social (12 dígitos) validado por módulo 97."""

        def __init__(self):
            patterns = [Pattern("ES NSS", r"\b\d{2}[ /-]?\d{8}[ /-]?\d{2}\b", 0.3)]
            super().__init__(supported_entity="ES_NSS", patterns=patterns, supported_language="es")

        def validate_result(self, pattern_text: str):
            return _valid_nss(pattern_text)

    return NssRecognizer()


def _build_cif_recognizer():
    from presidio_analyzer import Pattern, PatternRecognizer

    class CifRecognizer(PatternRecognizer):
        """CIF/NIF de empresa con validación del dígito/letra de control."""

        def __init__(self):
            patterns = [Pattern("ES CIF", r"\b[ABCDEFGHJKLMNPQRSUVW]\d{7}[0-9A-J]\b", 0.3)]
            super().__init__(supported_entity="ES_CIF", patterns=patterns, supported_language="es")

        def validate_result(self, pattern_text: str):
            return _valid_cif(pattern_text)

    return CifRecognizer()


def _build_plate_recognizer():
    from presidio_analyzer import Pattern, PatternRecognizer

    class PlateRecognizer(PatternRecognizer):
        """Matrícula española actual: 4 dígitos + 3 consonantes (sin vocales ni Q/Ñ)."""

        def __init__(self):
            patterns = [Pattern("ES plate", r"\b\d{4}[ -]?[BCDFGHJKLMNPRSTVWXYZ]{3}\b", 0.4)]
            super().__init__(
                supported_entity="ES_PLATE", patterns=patterns, supported_language="es"
            )

    return PlateRecognizer()


def _build_date_recognizer():
    from presidio_analyzer import Pattern, PatternRecognizer

    meses = (
        "enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        "septiembre|setiembre|octubre|noviembre|diciembre"
    )

    class SpanishDateRecognizer(PatternRecognizer):
        """Fechas en formatos habituales en español (numéricas, ISO y «d de mes de aaaa»)."""

        def __init__(self):
            patterns = [
                Pattern("fecha numérica", r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b", 0.6),
                Pattern("fecha ISO", r"\b\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}\b", 0.6),
                Pattern(
                    "fecha larga", r"(?i)\b\d{1,2}\s+de\s+(?:" + meses + r")\s+de\s+\d{4}\b", 0.7
                ),
            ]
            super().__init__(
                supported_entity="DATE_TIME", patterns=patterns, supported_language="es"
            )

    return SpanishDateRecognizer()


def _get_engines():
    """Construye (una vez) y devuelve (AnalyzerEngine, AnonymizerEngine)."""
    global _engines
    if _engines is not None:
        return _engines
    with _engines_lock:
        if _engines is not None:
            return _engines

        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine

        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "es", "model_name": "es_core_news_lg"}],
            }
        )
        nlp_engine = provider.create_engine()

        registry = RecognizerRegistry(supported_languages=["es"])
        registry.load_predefined_recognizers(languages=["es"])
        registry.add_recognizer(_build_dni_nie_recognizer())
        registry.add_recognizer(_build_iban_recognizer())
        registry.add_recognizer(_build_labeled_person_recognizer())
        registry.add_recognizer(_build_nss_recognizer())
        registry.add_recognizer(_build_cif_recognizer())
        registry.add_recognizer(_build_plate_recognizer())
        registry.add_recognizer(_build_date_recognizer())
        # Mantener el registro y el analyzer consistentes en idioma.
        registry.supported_languages = ["es"]

        analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            registry=registry,
            supported_languages=["es"],
        )
        anonymizer = AnonymizerEngine()
        _engines = (analyzer, anonymizer)
        return _engines


def _make_counter_operator(tag_base: str, values_in_order: list[str]):
    """Operador `custom`: cada valor distinto de `values_in_order` (los hallazgos
    de este tipo, en orden de aparición en el texto) recibe un índice consistente
    -> [tag_base_N]. El mapeo se PREPUEBLA a partir del análisis (no tiene
    estado mutable durante las llamadas de Presidio para el caso normal), pero
    es local a esta llamada (dict nuevo por invocación: sin estado a nivel de
    módulo) y puede CRECER dentro de `operate()` -- ver comentario en `op()`.

    El motor `AnonymizerEngine` invoca la lambda DOS veces por hallazgo -- una
    en `Operator.validate()`, con el valor de sondeo fijo "PII" (para comprobar
    que devuelve `str`), y otra real en `operate()` -- y además procesa los
    hallazgos de atrás hacia adelante para no desplazar offsets ya resueltos.
    Con un contador mutable ingenuo (incrementado en cada llamada) esas dos
    particularidades desordenan y desplazan la numeración; con un mapeo
    prepoblado el sondeo "PII" y el orden de procesamiento no importan."""
    seen: dict[str, int] = {}
    for v in values_in_order:
        norm = v.strip()
        if norm not in seen:
            seen[norm] = len(seen) + 1

    def op(value: str) -> str:
        norm = value.strip()
        idx = seen.get(norm)
        if idx is None:
            # `AnonymizerEngine.anonymize()` puede fusionar en Presidio dos
            # hallazgos adyacentes del mismo tipo separados solo por espacio,
            # o ajustar límites de spans solapados, antes de llamar a
            # `operate()`. El valor resultante entonces no es una clave del
            # mapa prepoblado (que se construyó a partir de los resultados
            # crudos de `analyzer.analyze()`). En vez de caer a un tag plano
            # sin numerar (rompería la garantía de integridad referencial de
            # la pseudonimización), se le asigna aquí un índice nuevo y se
            # guarda, de modo que repeticiones de ese mismo span fusionado
            # sigan recibiendo la misma etiqueta numerada.
            #
            # El sondeo de validación de Presidio (ver docstring de la
            # función) llama a `op("PII")` antes de cada hallazgo real; ese
            # valor fijo también entra aquí y añade una entrada "PII"->N al
            # mapa, pero nunca se emite en la salida real (el resultado del
            # sondeo se descarta), así que es inocuo.
            idx = len(seen) + 1
            seen[norm] = idx
        return f"[{tag_base}_{idx}]"

    return op


def anonymize_text_with_report(
    text: str, entity_keys: list[str], *, pseudonymize: bool = False
) -> tuple[str, dict[str, int]]:
    """Anonimiza `text` y devuelve (texto, informe) con {key: nº} de las
    sustituciones realmente aplicadas (contadas desde el EngineResult de
    Presidio, ya resueltos los solapes). `entity_keys` son claves de
    ENTITY_CONFIG; las desconocidas se ignoran.

    Si `pseudonymize` es True, en lugar de una etiqueta fija (`[DNI]`) numera
    cada valor distinto de forma consistente dentro de esta llamada
    (`[DNI_1]`, `[DNI_2]`…)."""
    keys = [k for k in entity_keys if k in _BY_KEY]
    if not text or not keys:
        return text, {}

    from presidio_anonymizer.entities import OperatorConfig

    analyzer, anonymizer = _get_engines()
    entities = [_BY_KEY[k]["entity"] for k in keys]
    results = analyzer.analyze(text=text, language="es", entities=entities)
    if pseudonymize:
        values_by_entity: dict[str, list[str]] = {}
        for r in sorted(results, key=lambda r: r.start):
            values_by_entity.setdefault(r.entity_type, []).append(text[r.start : r.end])
        operators = {
            _BY_KEY[k]["entity"]: OperatorConfig(
                "custom",
                {
                    "lambda": _make_counter_operator(
                        _BY_KEY[k]["tag"].strip("[]"),
                        values_by_entity.get(_BY_KEY[k]["entity"], []),
                    )
                },
            )
            for k in keys
        }
    else:
        operators = {
            _BY_KEY[k]["entity"]: OperatorConfig("replace", {"new_value": _BY_KEY[k]["tag"]})
            for k in keys
        }
    engine_result = anonymizer.anonymize(text=text, analyzer_results=results, operators=operators)
    entity_to_key = {_BY_KEY[k]["entity"]: k for k in keys}
    report: dict[str, int] = {}
    for item in engine_result.items:
        key = entity_to_key.get(item.entity_type)
        if key:
            report[key] = report.get(key, 0) + 1
    return engine_result.text, report


def anonymize_text(text: str, entity_keys: list[str]) -> str:
    """Wrapper de compatibilidad: solo el texto anonimizado.

    `entity_keys` son claves de ENTITY_CONFIG; las desconocidas se ignoran.
    Si no hay texto o no hay claves válidas, devuelve el texto sin cambios.
    """
    return anonymize_text_with_report(text, entity_keys)[0]
