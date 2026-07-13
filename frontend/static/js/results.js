// Render de resultados, modal <dialog> nativo y descargas (individual + ZIP).
import { state } from './state.js';
import { requestZip } from './api.js';
import { escapeHtml, extOf, formatElapsed, getFileIcon } from './utils.js';
import {
    renderTokenBadges,
    renderTokenRail,
    renderCompressionBadge,
    renderCompressionPanel,
} from './tokens.js';
import { showToast } from './toast.js';
import { anonymizerLabels } from './anonymize.js';

// Línea con el informe de anonimización {key: nº} de un resultado (si lo hay).
function renderAnonReport(report) {
    const entries = Object.entries(report || {});
    if (!entries.length) return '';
    const parts = entries.map(([k, n]) => `${n}× ${escapeHtml(anonymizerLabels[k] || k)}`);
    return `<div class="anon-report">🕵️ Anonimizado: ${parts.join(', ')}</div>`;
}

const progressSection = document.getElementById('progressSection');
const resultsSection = document.getElementById('resultsSection');
const resultsList = document.getElementById('resultsList');
const successInfo = document.getElementById('successInfo');
const errorInfo = document.getElementById('errorInfo');
const successCount = document.getElementById('successCount');
const errorCount = document.getElementById('errorCount');
const downloadAllBtn = document.getElementById('downloadAllBtn');
const contentModal = document.getElementById('contentModal');
const downloadBtn = document.getElementById('downloadBtn');
const copyBtn = document.getElementById('copyBtn');

// Mostrar resultados
export function displayResults(data) {
    progressSection.hidden = true;
    resultsSection.hidden = false;

    // Actualizar información de éxito/error
    if (data.successful > 0) {
        successInfo.hidden = false;
        successCount.textContent = data.successful;
    } else {
        successInfo.hidden = true;
    }

    if (data.failed > 0) {
        errorInfo.hidden = false;
        errorCount.textContent = data.failed;
    } else {
        errorInfo.hidden = true;
    }

    // Renderizar resultados (éxitos primero, luego errores)
    const allResults = [
        ...data.results.map(result => ({ ...result, type: 'success' })),
        ...data.errors.map(error => ({ ...error, type: 'error' })),
    ];

    resultsList.innerHTML = allResults
        .map((result, index) => {
            if (result.type === 'error') {
                const errIcon = getFileIcon(extOf(result.filename));
                return `
                    <div class="result-item">
                        <div class="result-header">
                            <div class="result-info">
                                <div class="result-status">❌</div>
                                <div class="result-details">
                                    <div class="result-filename">${errIcon} ${escapeHtml(result.filename)}</div>
                                    <div class="result-error-message">${escapeHtml(result.error)}</div>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }

            const elapsed = result.elapsed_ms != null ? ` • ${formatElapsed(result.elapsed_ms)}` : '';
            const sourceIcon = getFileIcon(result.extension || extOf(result.original_filename));
            const anonTag = result.anonymized ? ' <span class="anon-tag">🕵️ Anonimizado</span>' : '';
            return `
                <div class="result-item">
                    <div class="result-header">
                        <div class="result-info">
                            <div class="result-status">✓</div>
                            <div class="result-details">
                                <div class="result-filename">${escapeHtml(result.markdown_filename)}${anonTag}</div>
                                <div class="result-format">De: ${sourceIcon} ${escapeHtml(result.original_filename)} (${escapeHtml(result.format)})${elapsed}</div>
                                ${renderTokenBadges(result.markdown_content, renderCompressionBadge(result.compacted, result.original_chars, result.markdown_content))}
                                ${renderAnonReport(result.anonymization_report)}
                            </div>
                        </div>
                        <div class="result-actions">
                            <button class="result-btn view" type="button" data-action="view" data-index="${index}">Ver</button>
                            <button class="result-btn download" type="button" data-action="download" data-index="${index}">Descargar</button>
                        </div>
                    </div>
                </div>
            `;
        })
        .join('');

    // Guardar solo los resultados exitosos para descargas individuales y ZIP.
    // Sus índices coinciden con los data-index porque van primero en la lista.
    state.conversionResults = data.results;
    document.getElementById('convertBtn').disabled = false;
}

// Ver contenido en el modal <dialog>
function viewContent(index) {
    const result = state.conversionResults[index];
    state.currentModalData = result;
    const text = result.markdown_content || '';

    document.getElementById('modalTitle').textContent = result.markdown_filename;

    // Icono del archivo de origen (SVG seguro, no contenido del usuario)
    const sourceIcon = getFileIcon(result.extension || extOf(result.original_filename));
    document.getElementById('modalIcon').innerHTML = sourceIcon;

    // Subtítulo: origen + formato + tiempo + anonimización
    const elapsed = result.elapsed_ms != null ? ` · ${formatElapsed(result.elapsed_ms)}` : '';
    const anon = result.anonymized ? ' · <span class="modal-sub-tag">🕵️ Anonimizado</span>' : '';
    document.getElementById('modalSubtitle').innerHTML =
        `De ${escapeHtml(result.original_filename)} · ${escapeHtml(result.format)}${elapsed}${anon}`;

    // Estadísticas del propio Markdown
    const nf = (n) => n.toLocaleString('es-ES');
    const chars = text.length;
    const words = (text.trim().match(/\S+/g) || []).length;
    const lines = text ? text.split('\n').length : 0;
    document.getElementById('modalStats').textContent =
        `${nf(chars)} caracteres · ${nf(words)} palabras · ${nf(lines)} líneas`;

    // Carril lateral: compactación (si la hubo) + estimación de tokens + informe de anonimización
    document.getElementById('modalRail').innerHTML =
        renderCompressionPanel(result.compacted, result.original_chars, text) +
        renderTokenRail(text) +
        renderAnonReport(result.anonymization_report);

    const preview = document.getElementById('modalPreview');
    preview.textContent = text || '(Sin contenido de texto extraído)';
    preview.classList.toggle('is-empty', !text);

    contentModal.showModal();
}

// Disparar descarga de un resultado y mostrar confirmación
function triggerDownload(result) {
    const element = document.createElement('a');
    element.setAttribute(
        'href',
        'data:text/markdown;charset=utf-8,' + encodeURIComponent(result.markdown_content)
    );
    element.setAttribute('download', result.markdown_filename);
    element.hidden = true;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
    showToast(`Descargado: ${result.markdown_filename}`, 'ok');
}

// Copiar el contenido Markdown del modal al portapapeles.
// Usa la Clipboard API y cae a execCommand si no está disponible (p. ej. en
// orígenes http no seguros distintos de localhost).
async function copyModalContent() {
    const text = state.currentModalData?.markdown_content;
    if (!text) return;

    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
        } else {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
        showToast('Markdown copiado al portapapeles', 'ok');
    } catch (error) {
        showToast(`No se pudo copiar: ${error.message}`, 'err');
    }
}

// Descargar todos los resultados exitosos como un único ZIP (pedido al backend)
async function downloadAll() {
    const all = state.conversionResults || [];
    if (all.length === 0) {
        showToast('No hay archivos para descargar', 'err');
        return;
    }

    downloadAllBtn.disabled = true;
    const originalLabel = downloadAllBtn.textContent;
    downloadAllBtn.textContent = 'Generando ZIP…';

    try {
        const outcome = await requestZip(
            all.map((r) => ({
                filename: r.markdown_filename,
                content: r.markdown_content,
            }))
        );

        if (!outcome.ok) {
            showToast(`Error generando ZIP: ${outcome.detail}`, 'err');
            return;
        }

        const url = URL.createObjectURL(outcome.blob);
        const element = document.createElement('a');
        element.setAttribute('href', url);
        element.setAttribute('download', 'conversiones.zip');
        element.hidden = true;
        document.body.appendChild(element);
        element.click();
        document.body.removeChild(element);
        URL.revokeObjectURL(url);

        showToast(`ZIP descargado (${all.length} archivos)`, 'ok');
    } catch (error) {
        showToast(`Error generando ZIP: ${error.message}`, 'err');
    } finally {
        downloadAllBtn.disabled = false;
        downloadAllBtn.textContent = originalLabel;
    }
}

// Cablear listeners de resultados, modal y descargas.
export function setupResults() {
    // Delegación: botones "Ver" / "Descargar" de cada resultado
    resultsList.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const index = Number(btn.dataset.index);
        if (btn.dataset.action === 'view') viewContent(index);
        else if (btn.dataset.action === 'download') triggerDownload(state.conversionResults[index]);
    });

    downloadAllBtn.addEventListener('click', downloadAll);

    // Descargar desde el modal
    downloadBtn.addEventListener('click', () => {
        triggerDownload(state.currentModalData);
    });

    // Copiar el Markdown del modal al portapapeles (pie y barra del documento)
    copyBtn.addEventListener('click', () => copyModalContent());
    document.getElementById('copyInlineBtn').addEventListener('click', () => copyModalContent());

    // Cerrar el <dialog> con los botones marcados (cabecera y pie)
    contentModal.querySelectorAll('[data-action="close-modal"]').forEach((el) => {
        el.addEventListener('click', () => contentModal.close());
    });

    // Cerrar al hacer clic en el backdrop (fuera de .modal-content).
    // El <dialog> recibe el clic del backdrop directamente sobre sí mismo.
    contentModal.addEventListener('click', (e) => {
        if (e.target === contentModal) contentModal.close();
    });
    // Esc lo gestiona el navegador de forma nativa en <dialog>.
}

// Cerrar el modal de forma programática (usado al reiniciar la UI).
export function closeModal() {
    if (contentModal.open) contentModal.close();
}
