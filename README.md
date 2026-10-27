# MarkItDown GUI

Interfaz web para convertir documentos (PDF, Office, HTML, EPUB, imágenes, audio…) a **Markdown**, construida sobre [Microsoft MarkItDown](https://github.com/microsoft/markitdown).

Va más allá de la conversión: **OCR** del texto de imágenes con Tesseract, **anonimización** de datos sensibles (DNI, nombres, emails, IBAN…) con [Microsoft Presidio](https://github.com/microsoft/presidio), **compactación sin pérdida** para reducir tokens, y **estimación de tokens** por plataforma (ChatGPT, Claude, Gemini/NotebookLM, Kimi). Todo se procesa **en local y de forma efímera**: sin cuentas, sin almacenamiento y sin enviar tus documentos a terceros.

> Pensada para preparar documentos —incluidos PDF reales como nóminas o formularios— antes de pegarlos en un LLM, quitando lo sensible y ajustando el tamaño.

## 🎯 Características

- ✅ **Carga de múltiples archivos** - Arrastra y suelta o selecciona; un botón **«Añadir más archivos»** permite ir acumulando documentos a la lista (deduplica por nombre+tamaño)
- 🔍 **Detección automática de extensiones** - Identifica el formato automáticamente
- 🚀 **Conversión por lote** - Cada archivo se procesa de forma aislada; un fallo no aborta el resto
- 🖼️ **OCR de imágenes** - Extrae el texto de imágenes (PNG, JPG, GIF, BMP, WebP) con [Tesseract](https://github.com/tesseract-ocr/tesseract) en local, sin servicios externos
- 📋 **Vista previa** - Visualiza el Markdown convertido antes de descargar (modal `<dialog>` nativo)
- 💾 **Descarga individual o como ZIP** - Guarda cada `.md` por separado o todos en `conversiones.zip`
- 🔢 **Estimación de tokens** - Calcula (heurística, en el navegador) cuántos tokens ocuparía cada documento en ChatGPT, Claude, Gemini/NotebookLM y Kimi, con indicador de si cabe en su ventana de contexto
- 🗜️ **Compactación del Markdown** - Limpieza sin pérdida (colapsa líneas en blanco, espacios sobrantes y comentarios HTML, y quita filas de tabla vacías, respetando los bloques de código) que reduce los tokens; activada por defecto y con el **% de ahorro mostrado junto a la estimación de tokens**
- 🕵️ **Anonimización de datos sensibles** - Opción para quitar PII (DNI/NIE, Nº Seguridad Social, CIF/NIF de empresa, emails, nombres, teléfonos, IBAN, tarjetas, matrículas, fechas, direcciones, IPs) del Markdown resultante mediante [Microsoft Presidio](https://github.com/microsoft/presidio). Se aplica también sobre el texto extraído por OCR
- 🎨 **Interfaz moderna** - Diseño responsivo y accesible (contraste WCAG AA), sin build step ni framework: JavaScript en módulos ES nativos y CSS en parciales con `@layer`

## 📦 Formatos Soportados

### Documentos
- PDF — convertido con **pymupdf4llm**, que respeta el maquetado (títulos, tablas) y conserva el texto de **cabecera y pie**; si falla, recae en MarkItDown
- Word (.docx, .doc)
- PowerPoint (.pptx, .ppt)
- Excel (.xlsx, .xls)

### Imágenes
- JPEG, PNG, GIF, WebP, BMP — el texto se extrae por **OCR con Tesseract** (requiere el binario `tesseract` y los paquetes de idioma; ver Requisitos)

### Audio
- MP3, WAV, M4A — transcripción mediante MarkItDown; mp3/m4a necesitan **ffmpeg** instalado

### Texto y Datos
- TXT, CSV, JSON, XML
- HTML, EPUB
- ZIP files
- Markdown

## 🚀 Requisitos Previos

- **Python 3.10 o superior**
- **`uv`** (gestor de paquetes) - [Instalar uv](https://docs.astral.sh/uv/getting-started/installation/)
- **Dependencias del sistema** (binarios, no paquetes de Python):
  - **Tesseract OCR** + paquetes de idioma (`spa`, `eng`) — necesario para extraer texto de imágenes.
  - **ffmpeg** — necesario para transcribir audio comprimido (mp3/m4a).

  > Los scripts de instalación de abajo instalan todo esto por ti. Si el binario falta, la conversión de imágenes responde `503` («OCR no disponible») en vez de fallar de forma opaca; el resto de formatos funciona igual.

  > **PDF:** se convierten con `pymupdf4llm` (dependencia de Python, sin binario de sistema; la librería MuPDF va embebida y la instala `uv sync`). Ten en cuenta que **PyMuPDF/MuPDF es AGPL** (MarkItDown es MIT).

## 📥 Instalación

### 1. Clonar el proyecto

```bash
git clone https://github.com/aruetrecic/markitdown_gui.git
cd markitdown_gui
```

### 2a. Instalación automática desde cero (recomendado)

Instala dependencias del sistema (Tesseract + idiomas, ffmpeg), `uv` si falta, y todas las dependencias de Python:

```bash
# Fedora
./install-fedora.sh

# Ubuntu / Debian
./install-ubuntu.sh
```

### 2b. Instalación manual

```bash
# Dependencias del sistema — Fedora
sudo dnf install tesseract tesseract-langpack-spa tesseract-langpack-eng ffmpeg-free
# Dependencias del sistema — Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng ffmpeg

# Dependencias de Python (incluye pymupdf4llm para PDF y el modelo de spaCy
# es_core_news_lg, ~570 MB)
uv sync
# (con extras de desarrollo: pytest, black, ruff)
uv sync --all-extras
```

## 🎮 Uso

### Opción 1: Ejecutar con el script

```bash
# En Windows (PowerShell)
.\run.ps1

# En Linux/Mac
./run.sh
```

### Opción 2: Ejecutar manualmente

```bash
# Activar entorno virtual (si lo creaste)
source .venv/bin/activate  # Linux/Mac
# o
.venv\Scripts\activate      # Windows

# Ejecutar la aplicación
python -m uvicorn backend.main:app --reload
```

### Opción 3: Usar `uv` directamente

```bash
# Ejecutar sin activar el entorno
uv run python -m uvicorn backend.main:app --reload
```

La aplicación estará disponible en: **http://localhost:8000**

## 🚀 Despliegue (producción)

Para servirla en un (sub)dominio con HTTPS, la app corre como servicio local (uvicorn en `127.0.0.1:8000`) y **Nginx** delante hace de proxy. En [deploy/](deploy/) tienes plantillas listas: `markitdown.service` (systemd) y `nginx-md.tudominio.es.conf` (Nginx).

```bash
# 1. Instalar en el servidor (ej. en /opt)
cd /opt && sudo git clone https://github.com/aruetrecic/markitdown_gui.git
sudo chown -R $USER:$USER markitdown_gui && cd markitdown_gui
./install-ubuntu.sh

# 2. Servicio (arranque automático). Ajusta User/rutas dentro del fichero.
sudo cp deploy/markitdown.service /etc/systemd/system/markitdown.service
sudo systemctl daemon-reload && sudo systemctl enable --now markitdown

# 3. Nginx + HTTPS (cambia el dominio si no es md.tudominio.es)
sudo cp deploy/nginx-md.tudominio.es.conf /etc/nginx/sites-available/md.tudominio.es
sudo ln -s /etc/nginx/sites-available/md.tudominio.es /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d md.tudominio.es
```

**Notas importantes:**
- El servicio fija `WorkingDirectory` en la raíz del repo (la app usa rutas relativas) y arranca **sin `--reload`**.
- `client_max_body_size 100M` en Nginx deja margen sobre el límite de 50 MB por archivo de la app.
- **La app no tiene autenticación.** Si la expones en público, protégela (p. ej. *basic auth* en Nginx; ver comentarios en el `.conf`).
- Con anonimización activa se carga el modelo de spaCy (~570 MB) por proceso; con 1 worker uvicorn va bien.

### Despliegue en IONOS con Plesk (Ubuntu)

En los VPS/Servidores de IONOS con **Plesk** la ruta del (sub)dominio es del tipo `/var/www/vhosts/tudominio.es/md.tudominio.es` y **Nginx lo gestiona Plesk** (no se editan a mano los ficheros de `/etc/nginx`, los regenera). Para ese caso usa el instalador específico [deploy/install-ionos-plesk.sh](deploy/install-ionos-plesk.sh), que ejecuta como root todo lo que va por SSH:

```bash
# Como root, con el subdominio ya creado en el panel de Plesk
cd /tmp && git clone https://github.com/aruetrecic/markitdown_gui.git
sudo bash /tmp/markitdown_gui/deploy/install-ionos-plesk.sh
# (puerto a medida:  sudo PORT=8011 bash .../install-ionos-plesk.sh)
```

El script detecta el usuario del dominio en Plesk (el servicio corre con ese usuario, **no** `www-data`), instala Tesseract/ffmpeg/`uv`, clona el repo en `…/md.tudominio.es/markitdown_gui`, hace `uv sync` y crea el servicio systemd `markitdown` en `127.0.0.1:8000`. Después, **en el panel de Plesk**:

1. **Proxy inverso** — Dominios → `md.tudominio.es` → «Configuración de Apache y nginx». Pega lo que corresponda de [deploy/plesk-proxy-directives.conf](deploy/plesk-proxy-directives.conf), que trae dos variantes: **Apache** (`ProxyPass` en «Additional directives for HTTP» y «…HTTPS» — el caso habitual en IONOS, donde nginx no se expone por dominio) o **nginx** (desmarcando «Modo proxy» y pegando un `location /`). Usa la que te ofrezca el panel.
2. **HTTPS** — «Certificados SSL/TLS»: instala un Let's Encrypt gratuito y marca «Redirigir de HTTP a HTTPS». En Plesk usa **su** Let's Encrypt, **no** `certbot --nginx` (rompería la gestión de certificados de Plesk).

### Actualizar la app desplegada

Primero sube los cambios desde tu máquina (`git add -A && git commit && git push`). Luego, en el servidor por SSH como root, **lo que ejecutes depende de qué hayas tocado**:

| Cambiaste… | En el servidor |
|---|---|
| Solo **frontend** (HTML/CSS/JS) | `git pull` → recargar el navegador (Ctrl+R basta) |
| Código **Python** de `backend/` | `git pull` → `systemctl restart markitdown` |
| **`pyproject.toml`** (dependencias) | `git pull` → `uv sync …` → `systemctl restart markitdown` |

Los ficheros estáticos se sirven directos de disco y la app manda `Cache-Control: no-cache`, así que un cambio de frontend **no necesita reiniciar el servicio ni `Ctrl+Shift+R`**: con un `git pull` y recargar la página basta.

```bash
# Comandos (como root). El git pull corre como el usuario del dominio.
APP=/var/www/vhosts/tudominio.es/md.tudominio.es/markitdown_gui
U=$(systemctl show -p User --value markitdown)
sudo -u "$U" -H bash -c "cd $APP && git pull --ff-only"

# Solo si cambió backend/ (Python):
systemctl restart markitdown

# Solo si cambió pyproject.toml (dependencias):
sudo -u "$U" -H bash -c "cd $APP && UV_PYTHON_PREFERENCE=only-system /usr/local/bin/uv sync --python /usr/bin/python3"
systemctl restart markitdown
```

## 📁 Estructura del Proyecto

```
markitdown_gui/
├── backend/
│   ├── main.py              # Servidor FastAPI (endpoints + saneo + ZIP + no-cache)
│   ├── anonymizer.py        # Anonimización de PII con Presidio (perezoso)
│   ├── ocr.py               # OCR de imágenes con Tesseract (perezoso)
│   ├── pdf_markdown.py      # PDF → Markdown con pymupdf4llm (perezoso; fallback a MarkItDown)
│   └── compactor.py         # Compactación sin pérdida del Markdown
├── frontend/
│   ├── index.html           # Interfaz HTML (carga módulos ESM; modal <dialog>)
│   └── static/
│       ├── styles.css       # Índice CSS: declara @layer e importa los parciales
│       ├── script.js        # Punto de entrada JS: import './js/main.js'
│       ├── favicon.svg      # Favicon (servido también en /favicon.ico)
│       ├── js/              # Módulos ES nativos
│       │   ├── main.js       #   bootstrap: carga inicial + cableado de eventos
│       │   ├── state.js      #   estado compartido (objeto único)
│       │   ├── api.js        #   llamadas fetch a /api/*
│       │   ├── utils.js      #   helpers puros (escape, formato, iconos)
│       │   ├── tokens.js     #   estimación de tokens (badges + tabla)
│       │   ├── anonymize.js  #   casillas y selección de anonimización
│       │   ├── files.js      #   selección/drag-drop, lista, añadir más
│       │   ├── conversion.js #   bucle de conversión + log de progreso
│       │   ├── results.js    #   resultados, modal <dialog>, descargas
│       │   └── toast.js      #   notificaciones
│       └── css/             # Parciales CSS por capa/componente
│           ├── theme.css     #   variables :root + dark mode (contraste WCAG AA)
│           ├── base.css, layout.css, utilities.css
│           └── components/   #   upload, files, anonymize, progress, results,
│                             #   tokens, modal, toast, buttons, admonition, formats
├── tests/
│   ├── test_api.py          # Tests del API (pytest + httpx)
│   ├── test_anonymizer.py   # Tests de anonimización (DNI/NIE, email, endpoints)
│   ├── test_ocr.py          # Tests de OCR (enrutado, 503, errores en lote, OCR real)
│   ├── test_pdf_markdown.py # Tests del enrutado PDF→pymupdf4llm y sus fallbacks
│   └── test_compactor.py    # Tests de compactación (reglas lossless + endpoints)
├── docs/                    # Specs/planes de diseño y documentos de ejemplo (compactación, OCR)
├── deploy/                  # Plantillas de despliegue (systemd + Nginx, e instalador IONOS/Plesk)
├── install-fedora.sh        # Instalación desde cero en Fedora
├── install-ubuntu.sh        # Instalación desde cero en Ubuntu/Debian
├── pyproject.toml           # Configuración de dependencias (uv)
├── uv.lock                  # Lockfile reproducible (uv)
├── run.sh                   # Script para ejecutar (Linux/Mac)
├── run.ps1                  # Script para ejecutar (Windows)
└── README.md                # Este archivo
```

## 🔌 API Endpoints

### GET `/`
Sirve la interfaz web principal

### GET `/api/supported-formats`
Retorna lista de formatos soportados
```json
{
  "formats": {".pdf": "PDF", ".docx": "Word", ...},
  "extensions": [".pdf", ".docx", ...]
}
```

### GET `/api/anonymizer-options`
Retorna los tipos de datos sensibles que se pueden anonimizar
```json
{ "options": [ { "key": "dni_nie", "label": "DNI / NIE" }, { "key": "email", "label": "Email" }, ... ] }
```

### POST `/api/convert`
Convierte múltiples archivos
- **Parámetro**: `files` (FormData con múltiples archivos)
- **Opcional**: `anonymize` (`true`/`false`), `anonymize_entities` (claves separadas por coma, p. ej. `email,dni_nie,person`) y `compact` (`true`/`false`, por defecto `true`)
- **Retorna**: Array de resultados con contenido Markdown (cada resultado incluye `anonymized: bool` y `original_chars`, la longitud antes de compactar, para calcular el % de ahorro). Las imágenes se procesan por OCR; si el motor OCR no está disponible para un archivo, ese archivo aparece en `errors` sin abortar el resto.

### POST `/api/convert-single`
Convierte un único archivo
- **Parámetro**: `file` (FormData con un archivo)
- **Opcional**: `anonymize`, `anonymize_entities` y `compact` (igual que en `/api/convert`)
- **Retorna**: Resultado con contenido Markdown (incluye `original_chars`). Devuelve `503` si se pidió procesar una imagen y el motor OCR (Tesseract) no está disponible, o si se pidió anonimizar y el motor de anonimización no lo está.

### POST `/api/zip`
Empaqueta varios .md generados por el cliente en un único `conversiones.zip`.
- **Body** (JSON): `{ "files": [ { "filename": "...", "content": "..." } ] }`
- **Retorna**: `application/zip` con `Content-Disposition: attachment; filename="conversiones.zip"`
- Aplica las mismas mitigaciones que el resto: límite de archivos por lote, saneado de nombres (incluye strip de `/` y `\` para prevenir zip-slip), y dedup automático de nombres en colisión (`doc.md`, `doc (2).md`, …).

## 🔄 Cómo procesa los archivos

El servidor es **stateless**: no hay carpeta de uploads, ni de outputs, ni base de datos. Nada se persiste entre requests.

### Ciclo de vida del archivo de entrada (PDF, DOCX, etc.)

1. El cliente sube el archivo vía `multipart/form-data`.
2. FastAPI lo expone como un `UploadFile` (un `SpooledTemporaryFile` en memoria/disco que limpia Starlette al cerrar la request).
3. El backend lo vuelca a un `tempfile.NamedTemporaryFile(delete=False, suffix=<extensión original>)` **en streaming, por trozos de 1 MB** (`_stream_to_tempfile`), sin cargar el archivo entero en memoria — típicamente en `/tmp` (Linux/Mac) o `%TEMP%` (Windows). El límite de 50 MB se aplica al vuelo: si se supera mientras se escribe, se aborta y se borra el temp.
4. Preservar la extensión original es **load-bearing**: MarkItDown despacha el conversor por sufijo. Sin la extensión correcta, devolvería contenido vacío o erróneo.
5. `_extract_markdown(tmp_path, ext)` extrae el contenido: las **imágenes** pasan por **OCR (Tesseract)** y el resto por `MarkItDown.convert(tmp_path)`. Después, el texto pasa por **anonimización** (si se pidió) y **compactación** (si se pidió) antes de devolverse.
6. Un `finally` ejecuta `os.unlink(tmp_path)`. Tras la respuesta no queda rastro del archivo en disco.

### Ciclo de vida del Markdown de salida

1. `result.text_content` se devuelve como **string dentro del JSON de respuesta** — nunca se escribe a disco en el servidor.
2. El campo `markdown_filename` (`<nombre>.md`) es solo una sugerencia de nombre de descarga.
3. El frontend construye un `data:text/markdown;...` URL y dispara la descarga en el navegador. El `.md` solo existe en el cliente, donde lo guarde el usuario. Si no se descarga, se pierde al cerrar la pestaña.

### Manejo de errores por lote (`/api/convert`)

Cada archivo se procesa en su propio `try/except`: un error en uno no aborta el resto. La respuesta siempre es `200 OK` con dos arrays:

```json
{
  "results": [ ... archivos convertidos con éxito ... ],
  "errors":  [ { "filename": "...", "error": "..." } ],
  "total_files": N,
  "successful": M,
  "failed": N - M
}
```

`/api/convert-single`, en cambio, levanta `HTTPException` (400 si la extensión no está soportada, 413 si excede el tamaño, 503 si el motor de OCR o de anonimización no está disponible, 500 si la conversión falla).

### Caveats

- **Crash entre los pasos 3 y 6** (p. ej. `kill -9` o panic del proceso): el temp file queda huérfano en `/tmp`. Solo el `try/finally` cubre el caso normal, no la muerte abrupta.
- **Memoria**: la subida se vuelca al disco **en streaming por trozos** (`_stream_to_tempfile`), así que el archivo no se mantiene entero en RAM y el límite de 50 MB se aplica al vuelo. Aun así, un proxy delante (Nginx, Caddy) sigue siendo recomendable para cortar uploads abusivos antes de llegar al worker.
- **CORS**: no hay middleware de CORS. El frontend lo sirve la propia app en `/` y llama a `/api/*` en el mismo origen, así que no hace falta. Si algún día mueves el frontend a otro origen, añade `CORSMiddleware` con orígenes explícitos (nunca `allow_origins=["*"]`).
- **Caché del navegador**: la app envía `Cache-Control: no-cache` en todas las respuestas, de modo que el navegador revalida (ETag) y carga el frontend nuevo en cuanto cambia, sin necesidad de `Ctrl+Shift+R`.
- **Compresión gzip**: `GZipMiddleware` comprime las respuestas (Markdown, JSON y estáticos de texto) cuando el cliente acepta gzip, ahorrando ancho de banda de bajada. Los binarios ya comprimidos (ZIP) no ganan nada; el grueso del ahorro es el Markdown y el CSS/JS.

## ⚙️ Configuración Avanzada

### Instalar dependencias opcionales específicas

```bash
# Solo para PDF
uv pip install markitdown[pdf]

# Para múltiples formatos
uv pip install markitdown[pdf,docx,pptx,xlsx]

# Todos los formatos (default en el proyecto)
uv pip install 'markitdown[all]'
```

## 🛡️ Consideraciones de Seguridad

⚠️ **Importante**: MarkItDown realiza operaciones de I/O con los privilegios del proceso actual.
En ambientes no confiables:

- Valida y sanitiza las rutas de archivo
- Limita los esquemas de URI permitidos
- Restringe el acceso a recursos privados/locales
- Usa la función de conversión más específica que necesites

### Mitigaciones implementadas en esta app

- **Límite de tamaño por archivo**: 50 MB. Por encima → `413 Request Entity Too Large`.
- **Límite de archivos por lote**: 50 en `/api/convert`. Por encima → `400`.
- **Saneamiento de nombres reflejados**: los caracteres de control ASCII se eliminan del `filename` antes de devolverlo en la respuesta y de usarlo como sugerencia de descarga.
- **Escapado HTML en el frontend**: cualquier nombre de archivo o mensaje de error se escapa (`& < > " '`) antes de inyectarse en `innerHTML`. Defensa contra XSS reflejado por nombres maliciosos como `<img src=x onerror=...>.txt`.
- **`enable_plugins=False`** en el constructor de `MarkItDown`: no se cargan plugins externos. Reduce superficie de RCE si el entorno se ve comprometido.
- **`tempfile.NamedTemporaryFile`** con nombre aleatorio: el atacante no controla la ruta del archivo en disco. La extensión sí (load-bearing para el dispatcher de MarkItDown), pero está validada contra una whitelist.
- **Borrado del temp file** en `finally`: nada se persiste tras la conversión.

### Riesgos residuales conocidos

- **Sin timeout en `md.convert()`**. Un PDF/Office malformado puede colgar el worker. Mitigación operacional: ejecutar tras un proxy con timeout (Nginx, Caddy) o un supervisor que reinicie workers colgados.
- **XXE / SSRF en formatos XML-like** (`.xml`, `.html`, `.htm`, `.epub`). El comportamiento depende de la lib upstream. Si vas a procesar documentos no confiables, considera deshabilitar esas extensiones eliminándolas de `SUPPORTED_EXTENSIONS`.
- **Zip slip / zip bomb en `.zip`**. Misma consideración que XML.
- **Macros en Office docs**: MarkItDown extrae texto, no ejecuta macros, pero los parsers de Office son superficie de ataque histórica (CVEs). Mantén la dependencia actualizada.
- **Sin autenticación**: no la hay. Cualquiera con acceso al puerto puede convertir archivos. Pon delante un reverse-proxy con auth si lo expones.

## 🐛 Solución de Problemas

### Error: "Python 3.10 not found"
```bash
# Especificar versión de Python explícitamente
uv venv --python 3.11
```

### Error: "Module not found: markitdown"
```bash
# Reinstalar dependencias
uv sync --force
```

### La interfaz no carga
- Verifica que el servidor esté ejecutándose en http://localhost:8000
- Abre la consola del navegador (F12) para revisar errores
- Asegúrate de que el puerto 8000 no esté en uso

## 📝 Desarrollo

### Ejecutar tests

```bash
uv sync --all-extras
uv run --all-extras pytest
```

### Formatear código

```bash
uv run black backend/ tests/
uv run ruff check backend/ tests/
```

## 🤝 Contribuir

Las contribuciones son bienvenidas. Por favor:

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 📄 Licencia

Este proyecto usa [MarkItDown](https://github.com/microsoft/markitdown) que está bajo licencia MIT.

## 👤 Autor

**Antonio Rueda** — [@aruetre](https://github.com/aruetre) · antonio.rueda@gmail.com

Repositorio: <https://github.com/aruetrecic/markitdown_gui>

## 🙏 Créditos

- [Microsoft MarkItDown](https://github.com/microsoft/markitdown) - Librería de conversión
- [FastAPI](https://fastapi.tiangolo.com/) - Framework web
- [Uvicorn](https://www.uvicorn.org/) - Servidor ASGI

## 📧 Soporte

Si encuentras problemas:

1. Revisa el [README de MarkItDown](https://github.com/microsoft/markitdown)
2. Consulta los [Problemas conocidos](https://github.com/microsoft/markitdown/issues)
3. Abre un issue en este repositorio

---

**Hecho con ❤️ usando MarkItDown y FastAPI**
