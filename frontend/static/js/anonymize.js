// Carga de opciones de anonimización y lectura de la selección del usuario.
import { fetchAnonymizerOptions } from './api.js';
import { escapeHtml } from './utils.js';

// Mapa key -> label de los tipos anonimizables, para renderizar el informe
// de resultados sin volver a llamar al endpoint (poblado por loadAnonymizerOptions).
export const anonymizerLabels = {};

// Cargar tipos de datos anonimizables y montar las casillas (según su `default`).
// La caja de opciones se muestra/oculta con el atributo `hidden` al marcar el toggle.
export async function loadAnonymizerOptions() {
    const check = document.getElementById('anonymizeCheck');
    const optionsBox = document.getElementById('anonymizeOptions');
    const typesBox = document.getElementById('anonymizeTypes');

    check.addEventListener('change', () => {
        optionsBox.hidden = !check.checked;
    });

    try {
        const data = await fetchAnonymizerOptions();
        (data.options || []).forEach(opt => { anonymizerLabels[opt.key] = opt.label; });
        typesBox.innerHTML = (data.options || [])
            .map(opt => `
                <label class="anonymize-type">
                    <input type="checkbox" value="${escapeHtml(opt.key)}" ${opt.default ? 'checked' : ''}>
                    <span>${escapeHtml(opt.label)}</span>
                </label>
            `)
            .join('');
    } catch (error) {
        console.error('Error loading anonymizer options:', error);
        typesBox.innerHTML = '<div class="format-loading">Error al cargar opciones</div>';
    }
}

// Lee el estado de anonimización: { anonymize, entities, pseudonymize, customTerms }
export function getAnonymizeSelection() {
    const check = document.getElementById('anonymizeCheck');
    if (!check || !check.checked) {
        return { anonymize: false, entities: [], pseudonymize: false, customTerms: '' };
    }
    const entities = Array.from(
        document.querySelectorAll('#anonymizeTypes input[type="checkbox"]:checked')
    ).map(el => el.value);
    const pseudonymize = document.getElementById('pseudonymizeCheck')?.checked || false;
    const customTerms = (document.getElementById('customTerms')?.value || '').trim();
    return {
        anonymize: entities.length > 0 || customTerms.length > 0,
        entities,
        pseudonymize,
        customTerms,
    };
}
