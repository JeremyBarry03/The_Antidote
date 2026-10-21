export const MODEL_NAMES = Object.freeze({A: 'Quadratic regression', B: 'Standard XGBoost', C: 'Degradation-aware XGBoost'});
export const MODEL_COLORS = Object.freeze({A: '#e8b46a', B: '#9ba7ff', C: '#54d9ba'});
export const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';

/** @param {string} value */
export function utcDate(value) {
  return new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`);
}

/** @param {string | null | undefined} value @param {boolean} [seconds] */
export function clock(value, seconds = false) {
  if (!value) return 'Unavailable';
  return utcDate(value).toLocaleTimeString('en-GB', {timeZone: 'UTC', hour: '2-digit', minute: '2-digit',
    ...(seconds ? {second: '2-digit'} : {})});
}

/** @param {string} value */
export function dateLabel(value) {
  return utcDate(value).toLocaleDateString('en-GB', {timeZone: 'UTC', day: '2-digit', month: 'short', year: 'numeric'});
}

/** @param {number | null | undefined} value @param {number} [digits] */
export function number(value, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

/** @param {string | null} value @param {string | null} reference */
export function minutesBetween(value, reference) {
  return value && reference ? (utcDate(value).getTime() - utcDate(reference).getTime()) / 60_000 : null;
}

/** @param {number | null} value */
export function signedMinutes(value) {
  return value == null || !Number.isFinite(value) ? 'Unavailable' : `${value >= 0 ? '+' : ''}${number(value)} min`;
}

/** @param {keyof HTMLElementTagNameMap} tag @param {string} [text] @param {string} [className] */
export function node(tag, text = '', className = '') {
  const element = document.createElement(tag);
  element.textContent = text;
  element.className = className;
  return element;
}

/** @template {keyof SVGElementTagNameMap} T @param {T} tag @param {Record<string, string | number>} attributes */
export function svgNode(tag, attributes) {
  const element = document.createElementNS(SVG_NAMESPACE, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

/** @param {HTMLSelectElement} select @param {{value: string, label: string}[]} choices */
export function setOptions(select, choices) {
  select.replaceChildren(...choices.map(({value, label}) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    return option;
  }));
}

