import { createPrintEffects } from './print-effects.js';
import { createAnimationRenderer } from './renderer.js';
import { branchSettings, caduceusSettings, defaultSettings, settingsFromPreset } from './preset.js';
import { limits } from './limits.js';
export { branchSettings, settingsFromPreset } from './preset.js';

function normalize(settings, patch) {
  const next = { ...settings };
  for (const [key, value] of Object.entries(patch || {})) {
    if (!(key in defaultSettings)) continue;
    if (limits[key] && Number.isFinite(Number(value))) {
      next[key] = Math.min(limits[key][1], Math.max(limits[key][0], Number(value)));
      if (key === 'detail') next[key] = Math.round(next[key]);
    } else if (typeof defaultSettings[key] === 'boolean' && typeof value === 'boolean') {
      next[key] = value;
    } else if (['ink', 'background'].includes(key) && /^#[\da-f]{6}$/i.test(value)) {
      next[key] = value;
    } else if (key === 'glyphs' && ['balanced', 'fine', 'minimal', 'math', 'digits'].includes(value)) {
      next[key] = value;
    }
  }
  return next;
}

/** Mount the original ASCII artwork into a DOM element. No libraries required. */
export function mountAntidoteAscii(container, options = {}) {
  if (!container?.appendChild) throw new TypeError('Pass a container DOM element.');
  const artwork = options.artwork === 1 ? 1 : 2;
  let settings = normalize(artwork === 2 ? branchSettings : caduceusSettings,
    options.preset ? settingsFromPreset(options.preset, artwork) : options.settings);
  const canvas = document.createElement('canvas');
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', options.label || (artwork === 2 ? 'Animated ASCII branches' : 'Animated ASCII caduceus'));
  canvas.style.cssText = 'display:block;width:100%;height:auto;aspect-ratio:3/2;margin-inline:auto;';
  const context = canvas.getContext('2d');
  if (!context) throw new Error('This browser does not support Canvas 2D.');
  const renderer = createAnimationRenderer(createPrintEffects());
  const media = matchMedia('(prefers-reduced-motion: reduce)');
  const fps = Math.max(1, Math.min(60, Number(options.fps) || 25));
  let width = 0, height = 0, handle = 0, seconds = 0, lastTime = null, figureBounds = null;
  let paused = options.autoplay === false, inView = true, destroyed = false, finished = false;

  function draw() {
    if (destroyed || !width || !height) return;
    context.clearRect(0, 0, width, height);
    finished = renderer.render(context, width, height, artwork, settings, seconds, media.matches, figureBounds) === true;
  }
  function resize() {
    if (destroyed) return;
    canvas.style.maxWidth = `${Math.max(1, Number(options.maxWidth) || settings.size)}px`;
    canvas.style.background = settings.background;
    const bounds = canvas.getBoundingClientRect();
    width = bounds.width;
    height = bounds.height;
    const figure = options.figureElement?.getBoundingClientRect();
    figureBounds = figure?.width > 0 && figure?.height > 0 ? {
      x: figure.left - bounds.left, y: figure.top - bounds.top,
      width: figure.width, height: figure.height,
      align: getComputedStyle(options.figureElement).getPropertyValue('--ascii-align').trim()
    } : null;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    draw();
  }
  const shouldRun = () => !destroyed && !finished && !paused && inView && !document.hidden && !media.matches && width > 0;
  function schedule() {
    if (shouldRun()) {
      if (!handle) handle = requestAnimationFrame(tick);
    } else {
      if (handle) cancelAnimationFrame(handle);
      handle = 0;
      lastTime = null;
    }
  }
  function tick(time) {
    handle = 0;
    if (!shouldRun()) { schedule(); return; }
    if (lastTime === null) lastTime = time;
    if (time - lastTime >= 1000 / fps) {
      seconds += Math.min(.1, (time - lastTime) / 1000);
      lastTime = time;
      draw();
    }
    schedule();
  }
  function handleResize() { resize(); schedule(); }
  function handleMotion() { draw(); schedule(); }
  container.appendChild(canvas);
  const observer = new ResizeObserver(handleResize);
  observer.observe(container);
  const visibility = typeof IntersectionObserver === 'function' ? new IntersectionObserver(entries => {
    inView = entries[0]?.isIntersecting ?? true;
    schedule();
  }) : null;
  visibility?.observe(canvas);
  media.addEventListener('change', handleMotion);
  document.addEventListener('visibilitychange', schedule);
  window.addEventListener('resize', handleResize);
  resize();
  schedule();

  return {
    canvas,
    get settings() { return { ...settings }; },
    update(patch) {
      if (destroyed) return;
      finished = false;
      settings = normalize(settings, patch);
      resize();
      schedule();
    },
    applyPreset(preset) { this.update(settingsFromPreset(preset, artwork)); },
    pause() { paused = true; schedule(); },
    play() { paused = false; schedule(); },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      schedule();
      observer.disconnect();
      visibility?.disconnect();
      media.removeEventListener('change', handleMotion);
      document.removeEventListener('visibilitychange', schedule);
      window.removeEventListener('resize', handleResize);
      canvas.remove();
    }
  };
}
