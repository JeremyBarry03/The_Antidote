// Original setting types plus your approved per-artwork configuration.
import savedBranchSettings from './settings.js';
export const defaultSettings = Object.freeze({
    size: 760,
    detail: 120,
    framing: 100,
    tiltX: -8,
    tiltY: 15,
    tiltZ: 0,
    perspective: 1,
    shading: 2.2,
    lightAngle: -35,
    spinSpeed: 1,
    growth: 1,
    loopGrowth: true,
    reverseGrowth: false,
    imageBrightness: 0,
    imageContrast: 1,
    imageGamma: 1,
    invert: false,
    invertAscii: false,
    dither: false,
    glyphs: 'balanced',
    surfaceLighting: false,
    exposure: .72,
    contrast: 2.12,
    threshold: .41,
    edges: .40,
    opacity: 1.06,
    ink: '#20458b',
    background: '#ffffff',
    motion: 1,
    backgroundTexture: true,
    backgroundFade: 0,
    fitFigure: false,
    stemCrop: 0
  });
export const branchSettings = Object.freeze({ ...savedBranchSettings });
export const caduceusSettings = Object.freeze({
  "size": 760,
  "detail": 150,
  "framing": 125,
  "tiltX": -14,
  "tiltY": 12,
  "tiltZ": 10,
  "perspective": 1,
  "shading": 2.2,
  "lightAngle": -35,
  "spinSpeed": 1,
  "growth": 1,
  "imageBrightness": 0,
  "imageContrast": 1,
  "imageGamma": 1,
  "invert": false,
  "invertAscii": false,
  "dither": false,
  "glyphs": "fine",
  "exposure": 0.64,
  "contrast": 2.08,
  "threshold": 0.55,
  "edges": 0.24,
  "opacity": 1.06,
  "ink": "#ffffff",
  "background": "#000000",
  "motion": 3
});

export function settingsFromPreset(preset, artwork = 2) {
  const settings = preset?.artworks?.[artwork] ?? preset?.settings ?? preset;
  if (!settings || typeof settings !== 'object' || Array.isArray(settings)) {
    throw new TypeError('Use the settings JSON downloaded with Save preset.');
  }
  return settings;
}
