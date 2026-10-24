export function createAnimationRenderer(PrintEffects) {
  'use strict';

  // Geometry adapted from the two self-contained animations supplied by the user.
  const caduceus = [];
  const trees = [];
  function point(list, x, y, z, value = 1, depth = 0, nx = 0, ny = 0, nz = 1, twoSided = false) {
    const length = Math.hypot(nx, ny, nz) || 1;
    list.push({ x, y, z, value, depth, nx: nx / length, ny: ny / length, nz: nz / length, twoSided });
  }

  for (let y = -1.38; y < 1.28; y += .013) {
    for (let angle = 0; angle < 6.28; angle += .32) {
      point(caduceus, Math.cos(angle) * .042, y, Math.sin(angle) * .042,
        .8, 0, Math.cos(angle), 0, Math.sin(angle));
    }
  }
  for (let snake = 0; snake < 2; snake++) {
    for (let step = 0; step <= 1; step += .0025) {
      const y = -1.12 + step * 2.12;
      const angle = step * Math.PI * 4.6 + snake * Math.PI;
      const radius = .23 + .18 * step;
      for (let cross = 0; cross < 6.28; cross += .42) {
        const tube = .06 + .025 * step;
        const ring = radius + Math.cos(cross) * tube;
        const ringSlope = .18 + Math.cos(cross) * .025;
        const sx = Math.cos(angle) * ringSlope - Math.sin(angle) * Math.PI * 4.6 * ring;
        const sy = 2.12 + Math.sin(cross) * .025;
        const sz = Math.sin(angle) * ringSlope + Math.cos(angle) * Math.PI * 4.6 * ring;
        const cx = -Math.cos(angle) * Math.sin(cross) * tube;
        const cy = Math.cos(cross) * tube;
        const cz = -Math.sin(angle) * Math.sin(cross) * tube;
        point(caduceus,
          Math.cos(angle) * (radius + Math.cos(cross) * tube),
          y + Math.sin(cross) * tube,
          Math.sin(angle) * (radius + Math.cos(cross) * tube),
          1, 0, cy * sz - cz * sy, cz * sx - cx * sz, cx * sy - cy * sx);
      }
    }
  }
  for (const side of [-1, 1]) {
    for (let feather = 0; feather < 11; feather++) {
      const rootX = side * .06;
      const rootY = .88 - feather * .017;
      const endX = side * (1.15 - feather * .067);
      const endY = 1.35 - feather * .057;
      for (let step = 0; step < 1; step += .007) {
        for (let across = -1; across <= 1; across += .23) {
          const width = Math.sin(step * Math.PI) * .058;
          const tx = endX - rootX;
          const ty = endY - rootY + across * Math.cos(step * Math.PI) * Math.PI * .058;
          const tz = .33 * Math.cos(step * 3);
          const az = -Math.sign(across) * .07;
          const facing = side;
          point(caduceus,
            rootX + (endX - rootX) * step,
            rootY + (endY - rootY) * step + across * width,
            .11 * Math.sin(step * 3) - Math.abs(across) * .07,
            .7 + .3 * step, 0,
            (ty * az - tz * width) * facing,
            -tx * az * facing, tx * width * facing, true);
        }
      }
    }
  }
  for (let angle = 0; angle < 6.28; angle += .09) {
    for (let cross = 0; cross < 3.14; cross += .12) {
      point(caduceus,
        .095 * Math.cos(angle) * Math.sin(cross),
        1.32 + .095 * Math.cos(cross),
        .095 * Math.sin(angle) * Math.sin(cross),
        1, 0, Math.cos(angle) * Math.sin(cross), Math.cos(cross),
        Math.sin(angle) * Math.sin(cross));
    }
  }

  function branch(x, y, z, dx, dy, dz, depth, seed) {
    const length = Math.hypot(dx, dy, dz);
    const tx = dx / length;
    const ty = dy / length;
    const tz = dz / length;
    const helper = Math.abs(ty) < .9 ? [0, 1, 0] : [1, 0, 0];
    const ux = helper[1] * tz - helper[2] * ty;
    const uy = helper[2] * tx - helper[0] * tz;
    const uz = helper[0] * ty - helper[1] * tx;
    const unitLength = Math.hypot(ux, uy, uz);
    const u = [ux / unitLength, uy / unitLength, uz / unitLength];
    const v = [ty * u[2] - tz * u[1], tz * u[0] - tx * u[2], tx * u[1] - ty * u[0]];
    const baseRadius = .065 * Math.pow(.68, depth);
    const taper = depth === 4 ? .94 : .32;
    for (let step = 0; step <= 1; step += .006 / length) {
      const radius = baseRadius * (1 - taper * step);
      const slope = baseRadius * taper / length;
      for (let side = 0; side < 16; side++) {
        const angle = side * Math.PI / 8;
        const nx = u[0] * Math.cos(angle) + v[0] * Math.sin(angle);
        const ny = u[1] * Math.cos(angle) + v[1] * Math.sin(angle);
        const nz = u[2] * Math.cos(angle) + v[2] * Math.sin(angle);
        point(trees,
          x + dx * step + nx * radius,
          y + dy * step + ny * radius,
          z + dz * step + nz * radius,
          1, depth + step, nx + tx * slope, ny + ty * slope, nz + tz * slope);
      }
    }
    const endX = x + dx;
    const endY = y + dy;
    const endZ = z + dz;
    if (depth < 4) {
      const nextLength = .69 * Math.pow(.68, depth);
      const angle = seed * 1.76 + depth * .8;
      for (const side of [-1, 1]) {
        branch(endX, endY, endZ,
          side * Math.cos(angle) * nextLength,
          nextLength * .72,
          side * Math.sin(angle) * nextLength,
          depth + 1, seed + .6);
      }
    }
  }
  for (let index = 0; index < 3; index++) {
    branch((index - 1) * .65, -1.25, (index % 2) * .35, 0, .64, 0, 0, index * .9 + .1);
  }

  // Frame the whole, fully grown sculpture, so the crop stays still as it grows.
  const treeCenter = ['x', 'y', 'z'].map(axis => {
    let min = Infinity, max = -Infinity;
    for (const item of trees) {
      min = Math.min(min, item[axis]);
      max = Math.max(max, item[axis]);
    }
    return (min + max) / 2;
  });

  const alphabets = {
    balanced: ' .:-=+*#%@',
    fine: ' .,:;irsXA253hMHGS#9B&@',
    minimal: ' .-*#@',
    math: ' −+=×÷1234567890∑√∞',
    digits: ' 1234567890'
  };
  const clamp = value => Math.max(0, Math.min(1, value));
  const smoothstep = (start, end, value) => {
    const t = clamp((value - start) / (end - start));
    return t * t * (3 - 2 * t);
  };
  const backgroundCache = new Map();
  const sceneClocks = new Map();
  let branchFrameCache = null;
  const occlusionOffsets = [[-1, 0], [1, 0], [0, -1], [0, 1], [-2, -1], [2, -1], [-2, 1], [2, 1]];

  function branchFrame(width, height, pitch, roll, perspectiveAmount, fixedYaw = null, stemCrop = 0) {
    const key = [width, height, pitch, roll, perspectiveAmount, fixedYaw, stemCrop].join(':');
    if (branchFrameCache?.key === key) return branchFrameCache;
    const cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, croppedMaxY = -Infinity;
    // Fit the complete tree, never the currently growing tips. A stationary
    // view can use its actual orientation instead of reserving a full turn.
    const rotations = fixedYaw === null
      ? Array.from({ length: 24 }, (_, index) => index * Math.PI / 12)
      : [fixedYaw];
    for (const angle of rotations) {
      const cosine = Math.cos(angle), sine = Math.sin(angle);
      for (let index = 0; index < trees.length; index += 4) {
        const item = trees[index];
        const mx = item.x - treeCenter[0], my = item.y - treeCenter[1], mz = item.z - treeCenter[2];
        const yawX = mx * cosine + mz * sine, yawZ = -mx * sine + mz * cosine;
        const py = my * cp - yawZ * sp, z = my * sp + yawZ * cp;
        const perspective = 1 / Math.max(.35, 1 - z * perspectiveAmount / 4.6);
        const x = (yawX * cr - py * sr) * perspective;
        const y = (yawX * sr + py * cr) * perspective;
        minX = Math.min(minX, x); maxX = Math.max(maxX, x);
        minY = Math.min(minY, y); maxY = Math.max(maxY, y);
        if (item.depth >= stemCrop) croppedMaxY = Math.max(croppedMaxY, y);
      }
    }
    const paddingX = Math.max(12, width * .03), paddingY = Math.max(12, height * .04);
    branchFrameCache = { key, x: (minX + maxX) / 2, y: (minY + maxY) / 2,
      minY, croppedMaxY, spanX: maxX - minX,
      widthScale: Math.max(1, width - 2 * paddingX) / (maxX - minX),
      scale: Math.min(width * .90 / (maxX - minX), height * .86 / (maxY - minY)),
      fitScale: Math.min(Math.max(1, width - 2 * paddingX) / (maxX - minX),
        Math.max(1, height - 2 * paddingY) / (maxY - minY)) };
    return branchFrameCache;
  }

  function noise(x, y) {
    const hash = (a, b) => {
      const value = Math.sin(a * 127.1 + b * 311.7) * 43758.5453;
      return value - Math.floor(value);
    };
    const left = Math.floor(x);
    const top = Math.floor(y);
    const dx = x - left;
    const dy = y - top;
    const sx = dx * dx * (3 - 2 * dx);
    const sy = dy * dy * (3 - 2 * dy);
    const upper = hash(left, top) * (1 - sx) + hash(left + 1, top) * sx;
    const lower = hash(left, top + 1) * (1 - sx) + hash(left + 1, top + 1) * sx;
    return upper * (1 - sy) + lower * sy;
  }

  function render(context, width, height, artwork, settings, seconds, reducedMotion, figureBounds = null) {
    if (!width || !height) return;
    const view = figureBounds || { x: 0, y: 0, width, height };
    // Keep the figure's character resolution when its backdrop spans the banner.
    const columns = Math.max(1, Math.round(settings.detail * width / view.width));
    const cellWidth = width / columns;
    const rows = Math.max(1, Math.round(settings.detail * .625 / 1.5 * height / view.height));
    const cellHeight = height / rows;
    const fontSize = cellHeight * 1.08;
    const cacheKey = `${columns}:${rows}`;
    if (!backgroundCache.has(cacheKey)) {
      const background = new Float32Array(columns * rows);
      for (let row = 0; row < rows; row++) {
        for (let column = 0; column < columns; column++) {
          const x = column / columns;
          const y = row / rows;
          background[row * columns + column] = .20 + noise(x * 7, y * 5) * .16
            + noise(x * 24 + 9, y * 18 + 13) * .07
            + noise(column * .8, row * .8) * .025;
        }
      }
      backgroundCache.set(cacheKey, background);
    }
    const background = backgroundCache.get(cacheKey);
    const depth = new Float32Array(columns * rows).fill(-999);
    const tones = new Float32Array(columns * rows);
    const coverage = new Float32Array(columns * rows);
    const motion = reducedMotion ? 0 : settings.motion;
    const spinSpeed = reducedMotion ? 0 : (settings.spinSpeed ?? 1);
    const growthSpeed = reducedMotion ? 0 : (settings.growth ?? 1);
    if (!sceneClocks.has(artwork)) sceneClocks.set(artwork, { last: seconds, rotation: 0, growth: 0 });
    const clock = sceneClocks.get(artwork);
    const delta = Math.max(0, Math.min(.1, seconds - clock.last));
    clock.last = seconds;
    // Geometry has two independent clocks; Motion only changes the texture.
    clock.rotation += delta * spinSpeed * .27;
    clock.growth += delta * growthSpeed;
    const angle = (settings.tiltY ?? 15) * Math.PI / 180 + (reducedMotion ? 0 : clock.rotation);
    const cosine = Math.cos(angle);
    const sine = Math.sin(angle);
    const pitch = (settings.tiltX ?? -8) * Math.PI / 180;
    const roll = (settings.tiltZ ?? 0) * Math.PI / 180;
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    const cr = Math.cos(roll), sr = Math.sin(roll);
    const perspectiveAmount = settings.perspective ?? 1;
    const shading = settings.shading ?? 2.2;
    const lightAngle = (settings.lightAngle ?? -35) * Math.PI / 180;
    const lx = Math.sin(lightAngle) * .76;
    const ly = .65;
    const lz = Math.cos(lightAngle) * .76;
    const halfLength = Math.hypot(lx, ly, lz + 1);
    const hx = lx / halfLength, hy = ly / halfLength, hz = (lz + 1) / halfLength;
    const zoom = 1 + (settings.framing - 100) * .004;
    const stemCrop = clamp(settings.stemCrop ?? 0);
    const frame = artwork === 2 ? branchFrame(view.width, view.height, pitch, roll,
      perspectiveAmount, (settings.fitFigure || stemCrop) && spinSpeed === 0 ? angle : null, stemCrop) : null;
    // Keep the outer branches inside the art area, even when height-based
    // cropping would otherwise make the sculpture wider than the panel.
    const baselineInset = Math.max(2, fontSize * .55);
    const scale = frame && stemCrop > 0
      ? Math.min(frame.widthScale, Math.max(1, view.height - baselineInset) / (frame.croppedMaxY - frame.minY))
      : frame && settings.fitFigure ? frame.fitScale
      : (frame ? frame.scale : Math.min(view.width / 3.5, view.height / 3.4)) * zoom;
    const scaleX = scale;
    const centerX = view.x + (frame && view.align === 'start'
      ? Math.max(12, view.width * .03) + frame.spanX * scaleX * .5
      : view.width * .5);
    const looping = settings.loopGrowth !== false;
    const reversing = looping && settings.reverseGrowth === true;
    const cycle = looping ? (clock.growth + 3) % (reversing ? 23 : 24) : Math.min(14, clock.growth + 3);
    const growing = !reducedMotion && growthSpeed > 0;
    // Grow, hold briefly, then retract from the branch tips back to the roots.
    // Both ends of the loop meet at the same growth, without a whole-tree fade.
    // Retract to the visible top stems when the upper roots are cropped, so the
    // artwork never spends part of its cycle completely outside the banner.
    const restingGrowth = stemCrop > 0 ? stemCrop + .22 : 0;
    const growthRange = 5.3 - restingGrowth;
    const reversibleGrowth = restingGrowth + growthRange * (cycle < 10 ? smoothstep(0, 10, cycle)
      : cycle < 13 ? 1 : 1 - smoothstep(13, 23, cycle));
    const growth = growing ? (reversing ? reversibleGrowth : Math.min(5.3, cycle * 5.3 / 14)) : 6;
    const treeOpacity = growing && looping && !reversing ? 1 - smoothstep(21, 24, cycle) : 1;
    // Finish the growth once, but keep the supplied character shimmer alive.
    const complete = artwork === 2 && !looping && growing && cycle >= 14 && spinSpeed === 0 && motion === 0;
    const points = artwork === 1 ? caduceus : trees;

    for (const item of points) {
      const visibility = artwork === 2 ? smoothstep(0, .22, growth - item.depth) * treeOpacity : 1;
      if (!visibility) continue;
      const modelX = item.x - (artwork === 2 ? treeCenter[0] : 0);
      const modelY = item.y - (artwork === 2 ? treeCenter[1] : 0);
      const modelZ = item.z - (artwork === 2 ? treeCenter[2] : 0);
      const yawX = modelX * cosine + modelZ * sine;
      const yawZ = -modelX * sine + modelZ * cosine;
      const pitchY = modelY * cp - yawZ * sp;
      const z = modelY * sp + yawZ * cp;
      const x = yawX * cr - pitchY * sr;
      const y = yawX * sr + pitchY * cr;
      const perspective = 1 / Math.max(.35, 1 - z * perspectiveAmount / 4.6);
      const pixelX = centerX + (x * perspective - (frame?.x ?? 0)) * scaleX;
      const pixelY = frame && stemCrop > 0
        ? view.y + view.height - baselineInset - (y * perspective - frame.minY) * scale
        : view.y + view.height * (frame ? .5 : .51) - (y * perspective - (frame?.y ?? 0)) * scale;
      if (stemCrop > 0 && (pixelX < view.x || pixelX >= view.x + view.width
        || pixelY < view.y || pixelY >= view.y + view.height)) continue;
      const column = Math.floor(pixelX / cellWidth);
      const row = Math.floor(pixelY / cellHeight);
      if (column < 0 || column >= columns || row < 0 || row >= rows) continue;
      const index = row * columns + column;
      if (z > depth[index]) {
        depth[index] = z;
        coverage[index] = visibility;
        const yawNX = item.nx * cosine + item.nz * sine;
        const yawNZ = -item.nx * sine + item.nz * cosine;
        const pitchNY = item.ny * cp - yawNZ * sp;
        let nz = item.ny * sp + yawNZ * cp;
        let nx = yawNX * cr - pitchNY * sr;
        let ny = yawNX * sr + pitchNY * cr;
        // The feather ribbons have two visible faces; closed tubes use their
        // actual surface normals and the depth buffer hides their far sides.
        if (item.twoSided && nz < 0) {
          nx = -nx; ny = -ny; nz = -nz;
        }
        const diffuse = Math.max(0, nx * lx + ny * ly + nz * lz);
        const specular = Math.pow(Math.max(0, nx * hx + ny * hy + nz * hz), 22);
        tones[index] = clamp((.12 + diffuse * .74 + specular * .14) * (.85 + item.value * .15));
      }
    }

    // Treat the moving geometry as a pale figure. The supplied full texture is
    // optional so compact product banners can show only the sculpture.
    const imageTones = new Float32Array(columns * rows);
    for (let row = 0; row < rows; row++) {
      for (let column = 0; column < columns; column++) {
        const index = row * columns + column;
        let tone = settings.backgroundTexture === false && depth[index] === -999 ? 1 : background[index];
        if (depth[index] !== -999) {
          let occlusion = 0;
          let samples = 0;
          for (const [dx, dy] of occlusionOffsets) {
            const nx = column + dx, ny = row + dy;
            if (nx < 0 || nx >= columns || ny < 0 || ny >= rows) continue;
            const neighbor = depth[ny * columns + nx];
            if (neighbor !== -999 && neighbor > depth[index] + .06) {
              occlusion += clamp((neighbor - depth[index]) * 1.5);
            }
            samples++;
          }
          const surfaceTone = clamp(.60 + (tones[index] - .5) * .4 * shading
            - occlusion / Math.max(1, samples) * .16 * shading);
          tone += (surfaceTone - tone) * coverage[index];
        } else {
          let nearby = 0;
          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              const nx = column + dx;
              const ny = row + dy;
              if (nx >= 0 && nx < columns && ny >= 0 && ny < rows) {
                nearby = Math.max(nearby, tones[ny * columns + nx] * coverage[ny * columns + nx]);
              }
            }
          }
          if (nearby) tone += .09 * nearby;
        }
        const sourceTone = settings.invert ? 1 - tone : tone;
        tone = clamp((sourceTone - .5) * settings.imageContrast + .5 + settings.imageBrightness);
        imageTones[index] = Math.pow(tone, settings.imageGamma);
      }
    }

    if (settings.dither) {
      PrintEffects.dither(context, width, height, columns, rows, imageTones, settings, coverage);
      return;
    }

    context.font = `${fontSize}px Menlo, Monaco, Consolas, monospace`;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillStyle = settings.ink;
    const glyphs = alphabets[settings.glyphs] || alphabets.balanced;
    const colorLevels = PrintEffects.colorLevels(imageTones, columns, rows);
    // A darker body and pale highlights follow the actual surface lighting,
    // rather than relying on differently shaped characters to imply depth.
    const inkChannels = [1, 3, 5].map(offset => parseInt(settings.ink.slice(offset, offset + 2), 16));
    const lightingPalette = settings.surfaceLighting ? Array.from({ length: 33 }, (_, index) => {
      const mix = index / 32;
      const channels = inkChannels.map(channel => {
        const shadow = channel * .44;
        const highlight = channel + (255 - channel) * .75;
        return Math.round(shadow + (highlight - shadow) * mix);
      });
      return `rgb(${channels.join(',')})`;
    }) : null;
    for (let row = 0; row < rows; row++) {
      for (let column = 0; column < columns; column++) {
        const index = row * columns + column;
        const tone = imageTones[index];
        const left = imageTones[row * columns + Math.max(0, column - 1)];
        const right = imageTones[row * columns + Math.min(columns - 1, column + 1)];
        const up = imageTones[Math.max(0, row - 1) * columns + column];
        const down = imageTones[Math.min(rows - 1, row + 1) * columns + column];
        const edge = Math.min(1, (Math.abs(left - right) + Math.abs(up - down)) * 1.5);
        const surface = depth[index] !== -999;
        if (!surface && settings.backgroundTexture === false) continue;
        // Thin the background with a stable character mask, not lower opacity.
        // Geometry cells stay intact as the branches grow into them.
        if (!surface && settings.backgroundFade > 0) {
          const hash = Math.sin(column * 127.1 + row * 311.7) * 43758.5453;
          if (hash - Math.floor(hash) < clamp(settings.backgroundFade)) continue;
        }
        const strength = clamp((settings.exposure - tone) * settings.contrast
          + edge * settings.edges * (surface ? .5 : 1));
        if (!settings.invertAscii && !surface && strength < settings.threshold) continue;
        const shimmer = motion ? Math.sin(column * .28 + row * .53 + seconds * motion * 1.6) * .025 : 0;
        const amount = coverage[index];
        const density = PrintEffects.fillDensity(
          strength + (Math.max(strength, .24 + (1 - tone) * .66) - strength) * amount, settings.invertAscii);
        const glyphIndex = Math.min(glyphs.length - 1,
          Math.max(settings.invertAscii ? 0 : 1, Math.round((density + shimmer) * (glyphs.length - 1))));
        const fieldAlpha = Math.min(1, Math.pow(strength, 2.15) * settings.opacity);
        context.globalAlpha = settings.invertAscii ? Math.min(1, density * settings.opacity)
          : fieldAlpha + (Math.min(1, settings.opacity) - fieldAlpha) * amount;
        context.fillStyle = surface && lightingPalette
          ? lightingPalette[Math.round(smoothstep(.18, .78, tones[index]) * 32)]
          : PrintEffects.shade(settings.ink, colorLevels[index]);
        context.fillText(glyphs[glyphIndex],
          (column + .5) * cellWidth, (row + .5) * cellHeight);
      }
    }
    context.globalAlpha = 1;
    return complete;
  }

  return { render };
}
