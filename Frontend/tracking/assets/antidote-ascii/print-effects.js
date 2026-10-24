export function createPrintEffects() {
  const clamp = value => Math.max(0, Math.min(1, value));
  const palettes = new Map();
  const shadeFields = new Map();
  const buffers = new WeakMap();
  const bayer = [
    0, 48, 12, 60, 3, 51, 15, 63,
    32, 16, 44, 28, 35, 19, 47, 31,
    8, 56, 4, 52, 11, 59, 7, 55,
    40, 24, 36, 20, 43, 27, 39, 23,
    2, 50, 14, 62, 1, 49, 13, 61,
    34, 18, 46, 30, 33, 17, 45, 29,
    10, 58, 6, 54, 9, 57, 5, 53,
    42, 26, 38, 22, 41, 25, 37, 21
  ];

  function palette(ink) {
    if (!palettes.has(ink)) {
      const base = [1, 3, 5].map(index => parseInt(ink.slice(index, index + 2), 16));
      const shadow = base.map(channel => Math.round(channel * .76));
      const highlight = base.map(channel => Math.round(channel + (255 - channel) * .18));
      const colors = Array.from({ length: 33 }, (_, index) => {
        const level = index / 32;
        if (level <= .5) {
          const mix = level * 2;
          return base.map((channel, component) => Math.round(shadow[component] + (channel - shadow[component]) * mix));
        }
        const mix = (level - .5) * 2;
        return base.map((channel, component) => Math.round(channel + (highlight[component] - channel) * mix));
      });
      palettes.set(ink, { base, stops: [shadow, base, highlight], colors });
    }
    return palettes.get(ink);
  }

  function fillDensity(value, invertAscii = false) {
    return invertAscii ? 1 - clamp(value) : value;
  }

  function shade(ink, level) {
    const color = palette(ink).colors[Math.round(clamp(level) * 32)];
    return `rgb(${color.join(',')})`;
  }

  function hash(x, y) {
    const value = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
    return value - Math.floor(value);
  }

  function noise(x, y) {
    const left = Math.floor(x), top = Math.floor(y);
    const dx = x - left, dy = y - top;
    const sx = dx * dx * (3 - 2 * dx), sy = dy * dy * (3 - 2 * dy);
    const upper = hash(left, top) * (1 - sx) + hash(left + 1, top) * sx;
    const lower = hash(left, top + 1) * (1 - sx) + hash(left + 1, top + 1) * sx;
    return upper * (1 - sy) + lower * sy;
  }

  // A stable, softly mottled ink field extends over the entire print. The image
  // contributes gently to the colors; glyph density still describes its form.
  function colorLevels(tones, columns, rows) {
    const key = `${columns}:${rows}`;
    if (!shadeFields.has(key)) {
      const field = new Float32Array(columns * rows);
      for (let row = 0; row < rows; row++) {
        for (let column = 0; column < columns; column++) {
          field[row * columns + column] = (noise(column * .13, row * .16) - .5) * 1.1
            + (noise(column * .48 + 19, row * .43 + 7) - .5) * .35
            + (hash(column + 31, row + 17) - .5) * .20;
        }
      }
      shadeFields.set(key, field);
    }
    const field = shadeFields.get(key);
    const levels = new Float32Array(columns * rows);
    for (let index = 0; index < levels.length; index++) {
      levels[index] = clamp(.5 + (tones[index] - .5) * .35 + field[index]);
    }
    return levels;
  }

  function dither(context, width, height, columns, rows, tones, settings, surfaces = null, mask = null) {
    const pixelWidth = Math.max(1, Math.round(settings.detail * 3));
    const pixelHeight = Math.max(1, Math.round(pixelWidth * height / width));
    let buffer = buffers.get(context);
    if (!buffer) {
      const canvas = document.createElement('canvas');
      buffer = { canvas, context: canvas.getContext('2d') };
      buffers.set(context, buffer);
    }
    if (!buffer.image || buffer.canvas.width !== pixelWidth || buffer.canvas.height !== pixelHeight) {
      buffer.canvas.width = pixelWidth;
      buffer.canvas.height = pixelHeight;
      buffer.image = buffer.context.createImageData(pixelWidth, pixelHeight);
    }
    const pixels = buffer.image.data;
    pixels.fill(0);
    const colors = palette(settings.ink);
    const levels = colorLevels(tones, columns, rows);
    const strengths = new Float32Array(columns * rows);
    for (let row = 0; row < rows; row++) {
      for (let column = 0; column < columns; column++) {
        const index = row * columns + column;
        const left = tones[row * columns + Math.max(0, column - 1)];
        const right = tones[row * columns + Math.min(columns - 1, column + 1)];
        const up = tones[Math.max(0, row - 1) * columns + column];
        const down = tones[Math.min(rows - 1, row + 1) * columns + column];
        const edge = Math.min(1, (Math.abs(left - right) + Math.abs(up - down)) * 1.5);
        strengths[index] = clamp((settings.exposure - tones[index]) * settings.contrast + edge * settings.edges);
      }
    }
    for (let y = 0; y < pixelHeight; y++) {
      const sourceY = Math.max(0, Math.min(rows - 1, (y + .5) * rows / pixelHeight - .5));
      const top = Math.floor(sourceY), bottom = Math.min(rows - 1, top + 1), fy = sourceY - top;
      for (let x = 0; x < pixelWidth; x++) {
        const sourceX = Math.max(0, Math.min(columns - 1, (x + .5) * columns / pixelWidth - .5));
        const left = Math.floor(sourceX), right = Math.min(columns - 1, left + 1), fx = sourceX - left;
        const a = top * columns + left, b = top * columns + right;
        const c = bottom * columns + left, d = bottom * columns + right;
        const sample = field => (field[a] * (1 - fx) + field[b] * fx) * (1 - fy)
          + (field[c] * (1 - fx) + field[d] * fx) * fy;
        const threshold = (bayer[(y & 7) * 8 + (x & 7)] + .5) / 64;
        if (mask && sample(mask) <= threshold) continue;
        const strength = sample(strengths);
        const surface = surfaces ? clamp(sample(surfaces)) : 1;
        const fieldDensity = strength >= settings.threshold ? .15 + .50 * strength : 0;
        const cutStrength = clamp((strength - settings.threshold * .35) / (1 - settings.threshold * .35));
        const surfaceDensity = .68 + .24 * cutStrength;
        const density = fillDensity(clamp((fieldDensity * (1 - surface) + surfaceDensity * surface) * settings.opacity), settings.invertAscii);
        if (density <= threshold) continue;
        const level = clamp(sample(levels));
        const interval = Math.min(1, Math.floor(level * 2));
        const fraction = level * 2 - interval;
        const colorThreshold = (bayer[((y + 5) & 7) * 8 + ((x + 3) & 7)] + .5) / 64;
        const color = colors.stops[interval + (fraction > colorThreshold ? 1 : 0)];
        const pixel = (y * pixelWidth + x) * 4;
        for (let channel = 0; channel < 3; channel++) {
          pixels[pixel + channel] = color[channel];
        }
        pixels[pixel + 3] = 255;
      }
    }
    buffer.context.putImageData(buffer.image, 0, 0);
    const smoothing = context.imageSmoothingEnabled;
    const alpha = context.globalAlpha;
    context.imageSmoothingEnabled = false;
    context.globalAlpha = 1;
    context.drawImage(buffer.canvas, 0, 0, width, height);
    context.globalAlpha = alpha;
    context.imageSmoothingEnabled = smoothing;
  }

  return { shade, dither, colorLevels, fillDensity };
}
