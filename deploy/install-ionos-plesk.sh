#!/usr/bin/env bash
#
# Instalador de MarkItDown GUI para un VPS/Servidor de IONOS con Plesk (Ubuntu).
# ---------------------------------------------------------------------------
# Pensado para el subdominio  md.tudominio.es  cuyo home en Plesk es:
#     /var/www/vhosts/tudominio.es/md.tudominio.es
#
# La app NO es PHP: corre como un servicio systemd (uvicorn en 127.0.0.1:PORT)
# y Plesk/Nginx hace de proxy inverso por delante. Este script automatiza TODO
# lo que se hace por SSH como root; el proxy inverso y el certificado SSL se
# configuran luego en el panel de Plesk (ver deploy/plesk-proxy-directives.conf
# y las instrucciones que imprime este script al terminar).
#
# Uso (como root):
#     sudo bash deploy/install-ionos-plesk.sh
#
# Variables que puedes sobreescribir:
#     DOMAIN, BASE_DIR, REPO_URL, PORT, SERVICE
# Ejemplo:  sudo PORT=8011 bash deploy/install-ionos-plesk.sh
#
set -euo pipefail

# Overrides locales (gitignored, NO se publica): pon ahí tu dominio/ruta reales.
# Copia deploy.local.env.example a deploy.local.env y edítalo, o exporta las
# variables al lanzar el script.
_here="$(cd "$(dirname "$0")" && pwd)"
[[ -f "$_here/deploy.local.env" ]] && source "$_here/deploy.local.env"

# --- Configuración (ajústala si reutilizas el script en otro dominio) --------
DOMAIN="${DOMAIN:-md.tudominio.es}"
BASE_DIR="${BASE_DIR:-/var/www/vhosts/tudominio.es/md.tudominio.es}"
REPO_URL="${REPO_URL:-https://github.com/aruetrecic/markitdown_gui.git}"
PORT="${PORT:-8000}"
SERVICE="${SERVICE:-markitdown}"

APP_DIR="$BASE_DIR/markitdown_gui"          # el repo vive aquí (junto a httpdocs)
# Usuario del sistema dueño de la suscripción de Plesk (NO www-data):
VHOST_ROOT="$(dirname "$BASE_DIR")"          # .../vhosts/tudominio.es

echo "==> MarkItDown GUI — instalación para IONOS + Plesk (Ubuntu)"

# --- 0. Comprobaciones previas ----------------------------------------------
if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: ejecútalo como root:  sudo bash deploy/install-ionos-plesk.sh" >&2
  exit 1
fi
if [[ ! -d "$BASE_DIR" ]]; then
  echo "ERROR: no existe $BASE_DIR" >&2
  echo "       Crea antes el subdominio '$DOMAIN' en el panel de Plesk." >&2
  exit 1
fi

# Detecta el usuario del sistema del dominio (el dueño de la carpeta del vhost).
APP_USER="$(stat -c '%U' "$VHOST_ROOT")"
APP_GROUP="$(stat -c '%G' "$VHOST_ROOT")"
echo "    Dominio:           $DOMAIN"
echo "    Carpeta de la app: $APP_DIR"
echo "    Usuario systemd:   $APP_USER:$APP_GROUP  (usuario del dominio en Plesk)"
echo "    Puerto local:      127.0.0.1:$PORT"

# Helper: ejecuta un comando como el usuario del dominio, forzando 'bash' para
# saltarse la shell enjaulada (chrootsh) que Plesk suele asignar a estos usuarios.
run_as_user() { sudo -u "$APP_USER" -H bash -c "$1"; }

# --- 1. Dependencias del sistema (OCR + audio + utilidades) ------------------
echo "==> [1/6] Instalando paquetes del sistema (apt)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  python3 python3-venv python3-pip \
  tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
  ffmpeg \
  git curl

# --- 2. uv (gestor de paquetes de Python), system-wide en /usr/local/bin -----
if ! command -v /usr/local/bin/uv >/dev/null 2>&1; then
  echo "==> [2/6] Instalando uv en /usr/local/bin..."
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
else
  echo "==> [2/6] uv ya está instalado ($(/usr/local/bin/uv --version))"
fi

# --- 3. Clonar / actualizar el repo como el usuario del dominio --------------
if [[ -d "$APP_DIR/.git" ]]; then
  echo "==> [3/6] El repo ya existe; actualizando (git pull)..."
  run_as_user "cd '$APP_DIR' && git pull --ff-only"
else
  echo "==> [3/6] Clonando el repo en $APP_DIR..."
  run_as_user "git clone '$REPO_URL' '$APP_DIR'"
fi

# --- 4. Dependencias de Python con uv (incluye spaCy es_core_news_lg ~570 MB) -
# Forzamos el Python del sistema (UV_PYTHON_PREFERENCE=only-system) para que el
# venv apunte a /usr/bin/python3 (legible por systemd) y uv no descargue su
# propio intérprete en el cache del usuario.
echo "==> [4/6] Instalando dependencias de Python (puede tardar por el modelo)..."
run_as_user "cd '$APP_DIR' && UV_PYTHON_PREFERENCE=only-system /usr/local/bin/uv sync --python /usr/bin/python3"

# --- 5. Servicio systemd -----------------------------------------------------
echo "==> [5/6] Creando el servicio systemd /etc/systemd/system/$SERVICE.service..."
cat > "/etc/systemd/system/$SERVICE.service" <<EOF
# Generado por deploy/install-ionos-plesk.sh para $DOMAIN
[Unit]
Description=MarkItDown GUI ($DOMAIN)
After=network.target

[Service]
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$APP_DIR
Environment=HOME=$BASE_DIR
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=$APP_DIR/.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$SERVICE"

# --- 6. Verificación ---------------------------------------------------------
echo "==> [6/6] Verificando..."
sleep 2
systemctl --no-pager --full status "$SERVICE" | head -n 8 || true
echo "    Probando 127.0.0.1:$PORT ..."
if curl -fsS "http://127.0.0.1:$PORT/api/supported-formats" >/dev/null; then
  echo "    OK: la app responde en 127.0.0.1:$PORT"
else
  echo "    AVISO: la app aún no responde. Revisa:  journalctl -u $SERVICE -n 50 --no-pager" >&2
fi

cat <<EOF

============================================================================
✅ Backend instalado y corriendo como servicio (127.0.0.1:$PORT).

Faltan 2 pasos EN EL PANEL DE PLESK (no se tocan ficheros de Nginx a mano,
Plesk los regenera):

1) PROXY INVERSO
   Plesk → Dominios → $DOMAIN → "Configuración de Apache y nginx"
   Pega las directivas de  deploy/plesk-proxy-directives.conf  (puerto $PORT).
   Ese fichero trae 2 variantes; usa la que te ofrezca el panel:
     • APACHE: si solo ves campos de Apache → pega el bloque ProxyPass en
       "Additional directives for HTTP" y "...for HTTPS".
     • NGINX:  si ves "Modo proxy" → desmárcalo (+ "Procesamiento inteligente
       de archivos estáticos") y pega el bloque location / en las directivas
       de nginx;  valida con:  nginx -t

2) HTTPS (Let's Encrypt vía Plesk, NO uses certbot en Plesk)
   Plesk → Dominios → $DOMAIN → "Certificados SSL/TLS"
     • "Instalar" un certificado gratuito de Let's Encrypt
     • Marca "Redirigir de HTTP a HTTPS"

Luego abre:  https://$DOMAIN

⚠️  La app NO tiene autenticación. Si la dejas pública, protégela (basic auth
    en las directivas de nginx, o limítala por IP).

Operación del servicio:
   systemctl status $SERVICE
   systemctl restart $SERVICE
   journalctl -u $SERVICE -f
Actualizar la app:
   sudo -u $APP_USER -H bash -c "cd $APP_DIR && git pull"
   sudo -u $APP_USER -H bash -c "cd $APP_DIR && UV_PYTHON_PREFERENCE=only-system /usr/local/bin/uv sync --python /usr/bin/python3"
   systemctl restart $SERVICE
============================================================================
EOF
