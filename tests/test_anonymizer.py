"""Tests de anonimización de datos sensibles (PII).

Las pruebas de email y DNI/NIE son deterministas. Las de PERSON/teléfono
dependen del modelo spaCy; se marcan como tolerantes.
"""

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
    assert "ana@example.com" in body["markdown_content"]
