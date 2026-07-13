"""Tests de anonimización de datos sensibles (PII).

Las pruebas de email y DNI/NIE son deterministas. Las de PERSON/teléfono
dependen del modelo spaCy; se marcan como tolerantes.
"""

import re

from fastapi.testclient import TestClient

from backend.anonymizer import (
    _valid_cif,
    _valid_dni_nie,
    _valid_nss,
    anonymize_text,
    anonymize_text_with_report,
    available_options,
)
from backend.main import app

client = TestClient(app)


# --- Validación de DNI/NIE (determinista) ---


def test_dni_valido():
    assert _valid_dni_nie("12345678Z") is True


def test_dni_letra_incorrecta():
    assert _valid_dni_nie("12345678A") is False


def test_nie_valido():
    assert _valid_dni_nie("X1234567L") is True


def test_dni_formato_invalido():
    assert _valid_dni_nie("1234567Z") is False  # solo 7 dígitos
    assert _valid_dni_nie("ABCDEFGHZ") is False


# --- Validación de Nº Seguridad Social y CIF (determinista) ---


def test_nss_valido_e_invalido():
    base = "2801234567"  # 10 dígitos (provincia + número)
    valido = base + f"{int(base) % 97:02d}"
    assert _valid_nss(valido) is True
    assert _valid_nss(valido[:-2] + ("99" if valido[-2:] != "99" else "00")) is False
    assert _valid_nss("123") is False  # longitud incorrecta


def test_cif_valido_e_invalido():
    assert _valid_cif("A58818501") is True
    assert _valid_cif("A58818502") is False  # control erróneo
    assert _valid_cif("12345678Z") is False  # eso es un DNI, no un CIF


# --- available_options ---


def test_available_options_shape():
    opts = available_options()
    assert isinstance(opts, list) and opts
    for o in opts:
        assert set(o.keys()) == {"key", "label", "default"}
    keys = {o["key"] for o in opts}
    assert {"dni_nie", "email", "person"} <= keys


def test_location_no_marcada_por_defecto():
    by_key = {o["key"]: o for o in available_options()}
    assert by_key["location"]["default"] is False
    assert by_key["email"]["default"] is True


# --- anonymize_text (email y DNI deterministas) ---


def test_anonymize_email_y_dni():
    txt = "Mi correo es ana@example.com y mi DNI 12345678Z."
    out = anonymize_text(txt, ["email", "dni_nie"])
    assert "[EMAIL]" in out
    assert "[DNI]" in out
    assert "ana@example.com" not in out
    assert "12345678Z" not in out


def test_anonymize_seleccion_solo_email_no_toca_dni():
    txt = "correo ana@example.com y DNI 12345678Z."
    out = anonymize_text(txt, ["email"])
    assert "[EMAIL]" in out
    assert "12345678Z" in out  # el DNI no se pidió, se conserva


def test_anonymize_sin_entidades_devuelve_igual():
    txt = "correo ana@example.com"
    assert anonymize_text(txt, []) == txt


def test_anonymize_numero_no_dni_no_se_trata():
    # 8 dígitos con letra de control inválida no debe tratarse como DNI
    txt = "El pedido 12345678A está listo."
    out = anonymize_text(txt, ["dni_nie"])
    assert "12345678A" in out


def test_anonymize_iban_con_espacios_irregulares():
    # IBAN con dobles espacios y grupos irregulares (como en una nómina real)
    txt = "Número de cuenta:ES27  0049  6794  01  2116034467"
    out = anonymize_text(txt, ["iban"])
    assert "[IBAN]" in out
    assert "2116034467" not in out


def test_anonymize_iban_invalido_no_se_trata():
    txt = "Ref ES0000000000000000000000 fin"  # checksum mod-97 inválido
    out = anonymize_text(txt, ["iban"])
    assert "[IBAN]" not in out


def test_anonymize_nombre_por_etiqueta_en_mayusculas():
    # El NER se salta nombres en MAYÚSCULAS; el reconocedor por etiqueta no.
    txt = "Nombre: RUEDA TREVIÑO, ANTONIO\nOtro campo"
    out = anonymize_text(txt, ["person"])
    assert "[NOMBRE]" in out
    assert "RUEDA TREVIÑO" not in out


def test_anonymize_nss():
    base = "2801234567"
    nss = base + f"{int(base) % 97:02d}"
    out = anonymize_text(f"Nº afiliación: {nss}", ["social_security"])
    assert "[NSS]" in out and nss not in out


def test_anonymize_cif():
    out = anonymize_text("Empresa con CIF A58818501 en nómina", ["company_id"])
    assert "[CIF]" in out and "A58818501" not in out


def test_anonymize_matricula():
    out = anonymize_text("Vehículo 1234 BCD aparcado", ["vehicle_plate"])
    assert "[MATRICULA]" in out and "1234 BCD" not in out


def test_anonymize_fecha():
    out = anonymize_text("Fecha de alta: 12/01/2024.", ["date"])
    assert "[FECHA]" in out and "12/01/2024" not in out


# --- anonymize_text_with_report (informe de conteos) ---


def test_report_cuenta_por_tipo():
    txt = "correos a@x.com y b@y.com; DNI 12345678Z."
    out, report = anonymize_text_with_report(txt, ["email", "dni_nie"])
    assert "[EMAIL]" in out and "[DNI]" in out
    assert report["email"] == 2
    assert report["dni_nie"] == 1
    assert "person" not in report  # tipos con 0 no aparecen


def test_report_vacio_sin_entidades():
    out, report = anonymize_text_with_report("hola", [])
    assert out == "hola" and report == {}


def test_anonymize_text_sigue_devolviendo_str():
    # el wrapper de compatibilidad no se rompe
    out = anonymize_text("correo a@x.com", ["email"])
    assert isinstance(out, str) and "[EMAIL]" in out


# --- pseudonimización consistente (opcional) ---


def test_pseudonimizacion_numera_valores_distintos():
    txt = "DNI 12345678Z y DNI 87654321X en el mismo doc."
    out, _ = anonymize_text_with_report(txt, ["dni_nie"], pseudonymize=True)
    assert "[DNI_1]" in out and "[DNI_2]" in out
    assert "[DNI]" not in out  # numerado, no tag fijo


def test_pseudonimizacion_mismo_valor_misma_etiqueta():
    txt = "Titular: 12345678Z ... beneficiario 12345678Z otra vez."
    out, _ = anonymize_text_with_report(txt, ["dni_nie"], pseudonymize=True)
    assert out.count("[DNI_1]") == 2 and "[DNI_2]" not in out


def test_pseudonimizacion_nunca_emite_tag_plano_con_valores_adyacentes():
    # Dos DNIs distintos separados solo por un espacio: AnonymizerEngine puede
    # fusionar los dos hallazgos adyacentes en un único span que no coincide
    # con ninguna clave del mapa precalculado. La invariante es que, aun así,
    # pseudonymize nunca debe caer al tag plano sin numerar.
    txt = "DNI 12345678Z 87654321X aquí"
    out, _ = anonymize_text_with_report(txt, ["dni_nie"], pseudonymize=True)
    assert "12345678Z" not in out and "87654321X" not in out
    assert "[DNI]" not in out  # nunca un tag plano sin numerar
    assert re.search(r"\[DNI\](?!_)", out) is None


def test_pseudonimizacion_numeracion_independiente_por_tipo():
    txt = "DNI 12345678Z, correo a@x.com"
    out, _ = anonymize_text_with_report(txt, ["dni_nie", "email"], pseudonymize=True)
    assert "[DNI_1]" in out
    assert "[EMAIL_1]" in out


# --- términos propios (redacción literal) ---


def test_terminos_propios_literal_case_insensitive():
    txt = "El proyecto Fénix y su alias fenix son secretos."
    out, report = anonymize_text_with_report(txt, [], custom_terms=["Fénix"])
    assert "Fénix" not in out and "fenix" not in out
    assert out.count("[OCULTO]") == 2
    assert report["custom_terms"] == 2


def test_terminos_propios_se_tratan_literales_no_regex():
    txt = "coste 100 y algo(.*) raro"
    out, _ = anonymize_text_with_report(txt, [], custom_terms=[".*"])
    # '.*' se trata literal: solo redacta la secuencia literal '.*'
    assert out.count("[OCULTO]") == 1
    assert "coste 100" in out  # no borró todo por interpretar regex


def test_terminos_propios_funciona_sin_entidades_presidio():
    out, report = anonymize_text_with_report("hola Fenix mundo", [], custom_terms=["fenix"])
    assert out == "hola [OCULTO] mundo"
    assert report == {"custom_terms": 1}


def test_terminos_propios_combinado_con_presidio():
    txt = "correo a@x.com, proyecto Fenix"
    out, report = anonymize_text_with_report(txt, ["email"], custom_terms=["Fenix"])
    assert "[EMAIL]" in out
    assert "[OCULTO]" in out
    assert report["email"] == 1
    assert report["custom_terms"] == 1


def test_terminos_propios_multiples_solapados_y_adyacentes():
    # "friend" contiene "end" como subcadena, pero al exigir \b en ambos
    # extremos alfanuméricos, "end" no debe consumirse dentro de "friend"
    # (el carácter previo a "end" ahí es alfanumérico -> sin frontera). El
    # "end" independiente al final sí es una palabra completa y se redacta
    # aparte. "Fenix" y "Proyecto" están separados solo por una coma
    # (adyacentes, sin espacio) y ambos deben redactarse.
    txt = "Fenix,Proyecto y tambien mi friend end"
    out, report = anonymize_text_with_report(
        txt, [], custom_terms=["fenix", "proyecto", "end", "friend"]
    )
    assert out.count("[OCULTO]") == 4
    assert report["custom_terms"] == 4
    assert "Fenix" not in out and "Proyecto" not in out and "friend" not in out
    assert out == "[OCULTO],[OCULTO] y tambien mi [OCULTO] [OCULTO]"


def test_terminos_propios_extremo_no_alfanumerico_sigue_siendo_literal():
    # "C++": el extremo inicial ('C') es alfanumérico -> exige \b ahí; el
    # extremo final ('+') no lo es -> sin \b esa banda. Debe seguir
    # tratándose como cadena literal (el '+' no se interpreta como regex) y
    # no debe redactar "C++" cuando aparece pegado a otro alfanumérico antes
    # (viola la frontera de palabra inicial), aunque comparta el sufijo.
    txt = "Usamos C++ en el proyecto, no confundir con XC++Y ni con Cpp"
    out, report = anonymize_text_with_report(txt, [], custom_terms=["C++"])
    assert out.count("[OCULTO]") == 1
    assert report["custom_terms"] == 1
    assert out == "Usamos [OCULTO] en el proyecto, no confundir con XC++Y ni con Cpp"


def test_terminos_propios_punto_literal_no_regex_con_ambos_extremos_alfanumericos():
    # "a.b": ambos extremos son alfanuméricos -> \b en los dos lados. El '.'
    # debe tratarse literal (no "cualquier carácter"), así que "axb" -- que
    # coincidiría si '.' fuera un comodín de regex -- no debe redactarse.
    txt = "el valor es a.b aqui, no axb"
    out, report = anonymize_text_with_report(txt, [], custom_terms=["a.b"])
    assert out.count("[OCULTO]") == 1
    assert report["custom_terms"] == 1
    assert "axb" in out
    assert "a.b" not in out


def test_terminos_propios_vacios_no_generan_entrada_en_informe():
    out, report = anonymize_text_with_report("hola mundo", [], custom_terms=["noexiste", "  "])
    assert out == "hola mundo"
    assert "custom_terms" not in report


def test_available_options_incluye_custom_terms():
    opts = {o["key"]: o for o in available_options()}
    assert opts["custom_terms"]["label"] == "Términos propios"
    assert opts["custom_terms"]["default"] is False


# --- API ---


def test_anonymizer_options_endpoint():
    r = client.get("/api/anonymizer-options")
    assert r.status_code == 200
    opts = r.json()["options"]
    assert any(o["key"] == "email" for o in opts)


def test_convert_single_anonymiza_email():
    r = client.post(
        "/api/convert-single",
        files={"file": ("c.txt", b"escribe a ana@example.com", "text/plain")},
        data={"anonymize": "true", "anonymize_entities": "email"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["anonymized"] is True
    assert "[EMAIL]" in body["markdown_content"]
    assert "ana@example.com" not in body["markdown_content"]


def test_convert_single_incluye_informe_de_anonimizacion():
    r = client.post(
        "/api/convert-single",
        files={
            "file": (
                "c.txt",
                b"correos a@x.com y b@y.com",
                "text/plain",
            )
        },
        data={"anonymize": "true", "anonymize_entities": "email"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["anonymization_report"]["email"] == 2


def test_convert_single_sin_anonimizar_conserva_contenido():
    r = client.post(
        "/api/convert-single",
        files={"file": ("c.txt", b"escribe a ana@example.com", "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("anonymized") is False


def test_convert_single_redacta_terminos_propios_sin_entidades():
    # anonymize=true pero sin marcar ningún tipo de Presidio: debe funcionar
    # solo con custom_terms (el master switch permite el camino terms-only).
    r = client.post(
        "/api/convert-single",
        files={"file": ("c.txt", b"El proyecto Fenix sigue en marcha", "text/plain")},
        data={"anonymize": "true", "anonymize_entities": "", "custom_terms": "Fenix"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["anonymized"] is True
    assert "[OCULTO]" in body["markdown_content"]
    assert "Fenix" not in body["markdown_content"]
    assert body["anonymization_report"]["custom_terms"] == 1
