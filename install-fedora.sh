#!/usr/bin/env bash
#
# Instalación desde cero de MarkItDown GUI en Fedora.
#
# Instala las dependencias del sistema (Tesseract para OCR de imágenes, ffmpeg
# para transcripción de audio), el gestor de paquetes `uv` si falta, y todas las
# dependencias de Python (markitdown[all], pymupdf4llm para PDF, Presidio,
# spaCy + modelo es_core_news_lg ~570 MB y pytesseract).
#
# Uso:  ./install-fedora.sh
#
set -euo pipefail

cd "$(dirname "$0")"

echo "==> MarkItDown GUI — instalación para Fedora"

# 1. Dependencias del sistema (requiere sudo)
#    - tesseract + idiomas spa/eng : OCR del texto de las imágenes
#    - ffmpeg-free                 : transcripción de audio mp3/mp4
#      (si necesitas códecs propietarios, usa RPM Fusion + 'sudo dnf install ffmpeg')
#    - git, curl                   : utilidades / instalador de uv
echo "==> Instalando paquetes del sistema (sudo)..."
sudo dnf install -y \
  python3 \
  tesseract tesseract-langpack-spa tesseract-langpack-eng \
  ffmpeg-free \
  git curl

# 2. uv (gestor de paquetes de Python)
#    uv gestiona su propio Python: aunque el sistema traiga una versión muy nueva
#    (p. ej. Fedora 43 trae 3.14, sin wheels de spaCy 3.8), uv baja un Python
#    compatible (3.13) al sincronizar. Por eso el python3 del sistema es solo un
#    respaldo.
uv_recien_instalado=0
if ! command -v uv >/dev/null 2>&1; then
  echo "==> Instalando uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  uv_recien_instalado=1
fi

# 3. Dependencias de Python (set de producción; incluye el modelo de spaCy,
#    ~570 MB: puede tardar). Para las herramientas de desarrollo: uv sync --all-extras
echo "==> Sincronizando dependencias de Python con uv..."
uv sync

# 4. Verificación rápida
echo "==> Verificando instalación..."
tesseract --version | head -n 1
ffmpeg -version | head -n 1
uv run python -c "import markitdown, pymupdf4llm, pytesseract, presidio_analyzer; print('Dependencias de Python OK')"
# El modelo de spaCy es la pieza grande y frágil: si no se descargó, el import de
# arriba pasa igual pero la anonimización fallaría en runtime. Lo cargamos aquí.
uv run python -c "import spacy; spacy.load('es_core_news_lg'); print('Modelo spaCy es_core_news_lg OK')"

cat <<'EOF'

✅ Instalación completa.

Arranca la aplicación con:
   ./run.sh
   (equivale a: uv run python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000)

Luego abre http://localhost:8000
EOF

if [ "$uv_recien_instalado" = "1" ]; then
  cat <<'EOF'

⚠️  Se acaba de instalar uv. Si './run.sh' dice "uv: command not found",
   abre una terminal nueva o ejecuta primero:  source ~/.bashrc
EOF
fi
