// Push-to-talk microphone capture for offline voice commands.
// Records until the speaker stops (about 1 s of silence after speech) or MAX_S, then returns 16 kHz mono 16-bit
// WAV bytes for the laptop's Vosk recogniser. Pure helpers (downsample, encodeWav, EndOfSpeech) are unit-tested.

export const TARGET_RATE = 16000;
export const MAX_S = 6;

// Average-based decimation to 16 kHz (input usually 44.1 or 48 kHz).
export function downsample(float32, inRate, outRate = TARGET_RATE) {
  if (inRate === outRate) return Float32Array.from(float32);
  const ratio = inRate / outRate, n = Math.floor(float32.length / ratio), out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * ratio), b = Math.min(float32.length, Math.floor((i + 1) * ratio));
    let s = 0;
    for (let j = a; j < b; j++) s += float32[j];
    out[i] = b > a ? s / (b - a) : 0;
  }
  return out;
}

export function encodeWav(float32, rate = TARGET_RATE) {
  const n = float32.length, buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const str = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); str(8, "WAVE"); str(12, "fmt "); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const x = Math.max(-1, Math.min(1, float32[i]));
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
  }
  return new Uint8Array(buf);
}

export function rms(block) {
  let s = 0;
  for (let i = 0; i < block.length; i++) s += block[i] * block[i];
  return Math.sqrt(s / Math.max(1, block.length));
}

// Decides when an utterance has ended: speech must have started (level above an adaptive threshold) and then
// stayed quiet for `silenceMs`. Also stops after `maxMs`.
export class EndOfSpeech {
  constructor({ silenceMs = 1000, maxMs = MAX_S * 1000, minSpeechMs = 250, floor = 0.01 } = {}) {
    Object.assign(this, { silenceMs, maxMs, minSpeechMs, floor });
    this.t = 0; this.speechMs = 0; this.quietMs = 0; this.noise = null;
  }
  // level: RMS of a block; ms: block duration. Returns "continue" | "end" | "timeout".
  push(level, ms) {
    this.t += ms;
    if (this.noise === null) this.noise = level;
    const thr = Math.max(this.floor, this.noise * 3);
    if (level > thr) { this.speechMs += ms; this.quietMs = 0; }
    else {
      this.quietMs += ms;
      if (this.speechMs === 0) this.noise = 0.9 * this.noise + 0.1 * level;   // learn background noise before speech
    }
    if (this.t >= this.maxMs) return "timeout";
    if (this.speechMs >= this.minSpeechMs && this.quietMs >= this.silenceMs) return "end";
    return "continue";
  }
  get heardSpeech() { return this.speechMs >= this.minSpeechMs; }
}

// Browser glue: record one utterance. Resolves {wav: Uint8Array, seconds, heardSpeech}.
export async function recordUtterance({ onLevel = () => {} } = {}) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error(window.isSecureContext ? "microphone not supported by this browser" : "microphone needs HTTPS");
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") await ctx.resume();
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  const eos = new EndOfSpeech();
  return new Promise((resolve, reject) => {
    let finished = false;
    const finish = (err) => {
      if (finished) return; finished = true;
      try { proc.disconnect(); src.disconnect(); } catch (e) { /* ignore */ }
      stream.getTracks().forEach((t) => t.stop());
      const rate = ctx.sampleRate;
      ctx.close();
      if (err) return reject(err);
      const total = chunks.reduce((n, c) => n + c.length, 0), all = new Float32Array(total);
      let o = 0; chunks.forEach((c) => { all.set(c, o); o += c.length; });
      resolve({ wav: encodeWav(downsample(all, rate)), seconds: total / rate, heardSpeech: eos.heardSpeech });
    };
    proc.onaudioprocess = (ev) => {
      const block = new Float32Array(ev.inputBuffer.getChannelData(0));
      chunks.push(block);
      const level = rms(block);
      onLevel(level);
      const state = eos.push(level, (block.length / ctx.sampleRate) * 1000);
      if (state !== "continue") finish();
    };
    src.connect(proc); proc.connect(ctx.destination);
    setTimeout(() => finish(), (MAX_S + 1) * 1000);   // hard stop
  });
}
