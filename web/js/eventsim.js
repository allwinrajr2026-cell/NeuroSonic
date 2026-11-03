// Event-camera SIMULATION by frame differencing (demonstration only - not the WOAD model, not obstacle
// detection). An "event" is a pixel whose brightness changed by more than `threshold` since the last frame.
// Pure functions are unit-tested in Node.

export function toGray(rgba, n) {
  const g = new Uint8ClampedArray(n);
  for (let i = 0, j = 0; i < n; i++, j += 4) g[i] = (rgba[j] * 77 + rgba[j + 1] * 150 + rgba[j + 2] * 29) >> 8;
  return g;
}

// Returns {on, off, polarity(Int8Array: +1/-1/0), thirds:[left, middle, right] event fractions}
export function diffEvents(prev, cur, width, height, threshold = 25) {
  const n = width * height;
  const polarity = new Int8Array(n);
  const counts = [0, 0, 0];
  let on = 0, off = 0;
  const t1 = Math.floor(width / 3), t2 = Math.floor((2 * width) / 3);
  for (let i = 0; i < n; i++) {
    const d = cur[i] - prev[i];
    if (d > threshold) { polarity[i] = 1; on++; } else if (d < -threshold) { polarity[i] = -1; off++; } else continue;
    const x = i % width;
    counts[x < t1 ? 0 : x < t2 ? 1 : 2]++;
  }
  const colsize = [t1, t2 - t1, width - t2].map((w) => w * height);
  return { on, off, polarity, thirds: counts.map((c, k) => c / colsize[k]) };
}

const NAMES = ["left", "ahead", "right"];
const TEXT = { left: "Motion on the left.", ahead: "Motion ahead.", right: "Motion on the right." };

// Stateful detector of sustained motion per third, with cooldown and a "camera moving" guard.
export class MotionAlerter {
  constructor({ level = 0.04, frames = 2, cooldownMs = 4000, globalLevel = 0.25 } = {}) {
    Object.assign(this, { level, frames, cooldownMs, globalLevel });
    this.streak = [0, 0, 0];
    this.lastAlert = [-Infinity, -Infinity, -Infinity];
    this.lastGlobal = -Infinity;
  }

  update(thirds, now) {
    if (thirds.every((f) => f >= this.globalLevel)) {
      this.streak = [0, 0, 0];
      if (now - this.lastGlobal >= this.cooldownMs * 2) {
        this.lastGlobal = now;
        return [{ position: null, text: "Whole image changing. Camera moving or lighting changed." }];
      }
      return [];
    }
    const out = [];
    thirds.forEach((f, k) => {
      this.streak[k] = f >= this.level ? this.streak[k] + 1 : 0;
      if (this.streak[k] >= this.frames && now - this.lastAlert[k] >= this.cooldownMs) {
        this.lastAlert[k] = now;
        out.push({ position: NAMES[k], text: TEXT[NAMES[k]], level: f });
      }
    });
    return out;
  }
}

// Paint a DVS-style event image: ON events green, OFF events red, black background.
export function paintEvents(polarity, rgbaOut) {
  for (let i = 0, j = 0; i < polarity.length; i++, j += 4) {
    const p = polarity[i];
    rgbaOut[j] = p < 0 ? 255 : 0; rgbaOut[j + 1] = p > 0 ? 255 : 0; rgbaOut[j + 2] = 0; rgbaOut[j + 3] = 255;
  }
}
