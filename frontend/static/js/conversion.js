// Bucle de conversión archivo a archivo y log de progreso por archivo.
import { state } from './state.js';
import { convertSingle } from './api.js';
import { formatElapsed } from './utils.js';
import { getAnonymizeSelection } from './anonymize.js';
import { displayResults } from './results.js';

const filesSection = document.getElementById('filesSection');
const progressSection = document.getElementById('progressSection');
const convertBtn = document.getElementById('convertBtn');
const progressFill = document.getElementById('progressFill');
const progressText = document.getElementById('progressText');
const progressCurrent = document.getElementById('progressCurrent');
const progressLog = document.getElementById('progressLog');

// Añadir línea al log de progreso
function appendLog(text, kind) {
    const div = document.createElement('div');
    div.className = `progress-log-item ${kind}`;
    div.textContent = text;
    progressLog.appendChild(div);
    progressLog.scrollTop = progressLog.scrollHeight;
}

// Reemplazar la última línea del log (transición pending → ok/err)
function replaceLastLog(text, kind) {
    const last = progressLog.lastElementChild;
    if (!last) {
        appendLog(text, kind);
        return;
    }
    last.className = `progress-log-item ${kind}`;
    last.textContent = text;
}

// Convertir archivos uno a uno, mostrando progreso y tiempo por archivo
async function convertFiles() {
    if (state.selectedFiles.length === 0) {
        alert('Selecciona al menos un archivo');
        return;
    }

    filesSection.hidden = true;
    progressSection.hidden = false;
    convertBtn.disabled = true;

    const total = state.selectedFiles.length;
    const results = [];
    const errors = [];
    const anon = getAnonymizeSelection();

    progressFill.style.width = '0%';
    progressText.textContent = `0/${total} archivos procesados`;
    progressCurrent.textContent = '';
    progressLog.innerHTML = '';

    for (let i = 0; i < total; i++) {
        const file = state.selectedFiles[i];
        progressCurrent.textContent = `Procesando ${i + 1}/${total}: ${file.name}`;
        appendLog(`⏳ ${file.name}…`, 'pending');

        const formData = new FormData();
        formData.append('file', file);
        if (anon.anonymize) {
            formData.append('anonymize', 'true');
            formData.append('anonymize_entities', anon.entities.join(','));
            formData.append('pseudonymize', anon.pseudonymize ? 'true' : 'false');
            formData.append('custom_terms', anon.customTerms || '');
        }

        const compact = document.getElementById('compactCheck')?.checked;
        formData.append('compact', compact ? 'true' : 'false');

        const start = performance.now();
        try {
            const outcome = await convertSingle(formData);
            const elapsedMs = performance.now() - start;

            if (outcome.ok) {
                const result = outcome.result;
                result.elapsed_ms = elapsedMs;
                results.push(result);
                replaceLastLog(`✓ ${file.name} — ${formatElapsed(elapsedMs)}`, 'ok');
            } else {
                errors.push({ filename: file.name, error: outcome.detail, elapsed_ms: elapsedMs });
                replaceLastLog(`✗ ${file.name} — ${outcome.detail}`, 'err');
            }
        } catch (error) {
            const elapsedMs = performance.now() - start;
            errors.push({ filename: file.name, error: error.message, elapsed_ms: elapsedMs });
            replaceLastLog(`✗ ${file.name} — ${error.message}`, 'err');
        }

        const done = i + 1;
        progressFill.style.width = `${(done / total) * 100}%`;
        progressText.textContent = `${done}/${total} archivos procesados`;
    }

    progressCurrent.textContent = '';
    displayResults({
        results,
        errors,
        total_files: total,
        successful: results.length,
        failed: errors.length,
    });
}

// Cablear el botón de convertir.
export function setupConversion() {
    convertBtn.addEventListener('click', convertFiles);
}
