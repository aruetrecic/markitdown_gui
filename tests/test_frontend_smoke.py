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
