// Voice + audio cues. Pure queue logic (SpeechQueue) is separate from the browser glue (Announcer)
// so it can be unit-tested in Node.

export const PRIORITY = { urgent: 4, system: 3, obstacle: 2, motion: 1, navigation: 1, scene: 1, info: 0, description: 0 };
// Messages older than this when their turn comes are dropped (an old obstacle warning is misleading).
// scene: an on-demand online description; it may arrive seconds after the request, but is dropped if it waits
// in the queue for more than 30 s (the surroundings will have changed).
export const MAX_AGE_MS = { urgent: 2500, system: 15000, obstacle: 4000, motion: 3000, navigation: 15000, scene: 30000, info: 10000, description: 3000 };
// The same sentence is not repeated within this time (per category): routine messages wait longest.
export const COOLDOWN_MS = { urgent: 3000, system: 8000, obstacle: 6000, motion: 4000, navigation: 4000, scene: 2000, info: 20000, description: 8000 };
// Pause between two spoken messages, so announcements do not run into each other.
export const GAP_MS = 250;
// Categories that may cut off a lower-priority message that is already playing.
export const INTERRUPTING = { urgent: true, obstacle: true, system: true };

export const TEST_SENTENCE = "Hello. This is NeuroSonic. Your voice assistant is working correctly.";

export class SpeechQueue {
  // dedupeMs (optional) overrides the per-category COOLDOWN_MS for every category
  constructor({ dedupeMs = null, maxLength = 6 } = {}) {
    this.items = [];
    this.lastSaid = new Map(); // text -> time
    this.dedupeMs = dedupeMs;
    this.maxLength = maxLength;
  }

  cooldown(category) {
    if (this.dedupeMs != null) return this.dedupeMs;
    return category in COOLDOWN_MS ? COOLDOWN_MS[category] : 4000;
  }

  // key (optional): messages with the same key replace each other while queued ("latest wins"), e.g. "path" for
  // walking-path states, so an outdated "Caution" is never spoken after the path has become clear.
  push(text, category, now, key) {
    if (!text) return false;
    const last = this.lastSaid.get(text);
    if (last !== undefined && now - last < this.cooldown(category)) return false;
    if (key) this.items = this.items.filter((i) => i.key !== key);
    if (this.items.some((i) => i.text === text)) return false;
    this.items.push({ text, category, key: key || null, priority: category in PRIORITY ? PRIORITY[category] : 0, t: now });
    // keep the queue short: drop the lowest-priority, oldest items first
    this.items.sort((a, b) => b.priority - a.priority || a.t - b.t);
    if (this.items.length > this.maxLength) this.items.length = this.maxLength;
    return true;
  }

  next(now) {
    while (this.items.length) {
      const item = this.items.shift();
      if (now - item.t <= (item.category in MAX_AGE_MS ? MAX_AGE_MS[item.category] : 5000)) {
        this.lastSaid.set(item.text, now);
        return item;
      }
    }
    return null;
  }

  clear() { this.items = []; }

  // Should a new message of `category` stop the message that is playing now?
  shouldInterrupt(current, category) {
    if (!current || !INTERRUPTING[category]) return false;
    const p = category in PRIORITY ? PRIORITY[category] : 0;
    return p > current.priority;
  }

  // Put an interrupted message back (once), keeping its original time so stale-dropping still applies.
  requeue(item) {
    if (!item || item.requeued || item.category === "urgent" || item.category === "obstacle") return false;
    this.items.push(Object.assign({}, item, { requeued: true }));
    this.items.sort((a, b) => b.priority - a.priority || a.t - b.t);
    this.lastSaid.delete(item.text);
    return true;
  }
}

export function panFor(position) {
  return position === "left" ? -0.8 : position === "right" ? 0.8 : 0;
}

// A tiny silent WAV (0.05 s) used to "unlock" the audio element inside a user gesture (iOS requirement).
export function silentWavBytes(sampleRate = 8000, seconds = 0.05) {
  const n = Math.round(sampleRate * seconds), buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const str = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); str(8, "WAVE"); str(12, "fmt "); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, n * 2, true);
  return new Uint8Array(buf);
}

// Browser glue. Primary voice: the laptop's local neural voice (Piper) fetched as WAV and played through one
// reusable <audio> element. Fallback: the browser's own speechSynthesis. Plus short WebAudio tones.
export class Announcer {
  constructor(settings) {
    this.settings = settings; // {engine: "neural"|"browser", voice, rate, volume, speech, beeps}
    this.queue = new SpeechQueue();
    this.speaking = false;
    this.ctx = null;
    this.neuralAvailable = false;
    this.unlocked = false;
    this.onSpeak = () => {};
    this.onStatus = () => {};     // (status) => void: speaking indicator
    this.onReport = () => {};     // (report) => void: playback results (sent to the server)
    this.status = { speaking: false, engine: null, text: null, lastError: null, lastOk: null };
    this.supported = typeof window !== "undefined" && "speechSynthesis" in window;
    this.audio = typeof Audio !== "undefined" ? new Audio() : null;
    if (this.audio) { this.audio.preload = "auto"; this.audio.setAttribute("playsinline", ""); }
    this.blobs = new Map();       // text -> object URL (small client cache)
  }

  voices() { return this.supported ? window.speechSynthesis.getVoices() : []; }
  canSpeak() { return (this.neuralAvailable && this.settings.engine !== "browser") || this.supported; }

  _setStatus(patch) { Object.assign(this.status, patch); this.onStatus(Object.assign({}, this.status)); }

  // iOS (Safari and Chrome are both WebKit) only plays audio first started inside a user gesture.
  // Call from a tap handler: blesses the <audio> element, resumes WebAudio and primes speechSynthesis.
  unlock() {
    if (this.unlocked) return;
    this.unlocked = true;
    try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch (e) { /* Safari 17+ only */ }
    try {
      this.ctx = this.ctx || new (window.AudioContext || window.webkitAudioContext)();
      if (this.ctx.state === "suspended") this.ctx.resume();
    } catch (e) { /* no WebAudio */ }
    if (this.audio) {
      try {
        this.audio.src = URL.createObjectURL(new Blob([silentWavBytes()], { type: "audio/wav" }));
        const p = this.audio.play(); if (p && p.catch) p.catch(() => {});
      } catch (e) { /* ignore */ }
    }
    if (this.supported) {
      try { const u = new SpeechSynthesisUtterance(" "); u.volume = 0; window.speechSynthesis.speak(u); } catch (e) { /* ignore */ }
    }
  }

  beep(position = "ahead", category = "obstacle") {
    if (!this.settings.beeps) return;
    try {
      this.ctx = this.ctx || new (window.AudioContext || window.webkitAudioContext)();
      if (this.ctx.state === "suspended") this.ctx.resume();
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      const pan = this.ctx.createStereoPanner ? this.ctx.createStereoPanner() : null;
      osc.frequency.value = category === "system" ? 330 : category === "motion" ? 660 : 880;
      gain.gain.value = 0.15 * this.settings.volume;
      osc.connect(gain);
      if (pan) { pan.pan.value = panFor(position); gain.connect(pan); pan.connect(this.ctx.destination); }
      else gain.connect(this.ctx.destination);
      const t = this.ctx.currentTime;
      gain.gain.setTargetAtTime(0, t + 0.12, 0.03);
      osc.start(t); osc.stop(t + 0.25);
    } catch (e) { /* audio not available: speech/text still work */ }
  }

  say(text, category = "info", position = null, opts = {}) {
    this.onSpeak(text, category);
    if (category !== "navigation" && category !== "info" && category !== "description" && category !== "scene") this.beep(position || "ahead", category);
    if (!this.settings.speech) return;
    if (opts.force) this.queue.lastSaid.delete(text);
    if (this.queue.push(text, category, Date.now(), opts.key)) {
      if (this.speaking && this.queue.shouldInterrupt(this.current, category)) this.interrupt();
      else this._pump();
    }
  }

  // Stop the message that is playing now (it is re-queued once if it was routine, e.g. a navigation step).
  interrupt() {
    if (!this.speaking || !this._abort) return;
    this._interruptedItem = this.current;
    this._abort();
  }

  async _pump() {
    if (this.speaking) return;
    const item = this.queue.next(Date.now());
    if (!item) return;
    this.speaking = true;
    this.current = item;
    const neural = !!(this.neuralAvailable && this.settings.engine !== "browser" && this.audio);
    const t0 = Date.now();
    try {
      this._setStatus({ speaking: true, engine: neural ? "neural" : "browser", text: item.text });
      if (neural) await this._playNeural(item.text);
      else await this._playBrowser(item.text);
      this._setStatus({ lastOk: `${neural ? "Neural voice" : "Browser voice"} played at ${new Date().toLocaleTimeString()}`, lastError: null });
      this.onReport({ engine: neural ? "neural" : "browser", ok: true, text: item.text, duration: (Date.now() - t0) / 1000 });
    } catch (e) {
      if (e && e.interrupted) {          // cut off by a more urgent message: not an error
        this.queue.requeue(this._interruptedItem);
        this._interruptedItem = null;
        return;                          // finally{} continues with the urgent message
      }
      const msg = `${neural ? "Neural" : "Browser"} voice failed: ${e && e.message ? e.message : e}`;
      this._setStatus({ lastError: msg });
      this.onReport({ engine: neural ? "neural" : "browser", ok: false, error: msg, text: item.text });
      if (neural && this.supported) {           // fallback: the browser's own voice
        try { this._setStatus({ engine: "browser" }); await this._playBrowser(item.text); } catch (e2) { /* reported above */ }
      }
    } finally {
      this.speaking = false;
      this.current = null;
      this._abort = null;
      this._setStatus({ speaking: false, text: null });
      setTimeout(() => this._pump(), GAP_MS);
    }
  }

  // Fetch the neural audio for fixed warning sentences in advance, so an urgent "Stop" is not delayed by synthesis
  // and download when it is first needed. Errors are ignored (the browser voice remains the fallback).
  prefetch(texts) {
    if (!this.neuralAvailable || this.settings.engine === "browser") return;
    texts.reduce((p, t) => p.then(() => this._neuralUrl(t)).catch(() => {}), Promise.resolve());
  }

  async _neuralUrl(text) {
    if (this.blobs.has(text)) return this.blobs.get(text);
    const res = await fetch("/api/tts?text=" + encodeURIComponent(text));
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { detail = (await res.json()).error || detail; } catch (e) { /* not JSON */ }
      throw new Error(detail);
    }
    const url = URL.createObjectURL(await res.blob());
    this.blobs.set(text, url);
    if (this.blobs.size > 40) {
      const first = this.blobs.entries().next().value;
      URL.revokeObjectURL(first[1]); this.blobs.delete(first[0]);
    }
    return url;
  }

  _playNeural(text) {
    return this._neuralUrl(text).then((url) => new Promise((resolve, reject) => {
      const a = this.audio;
      let timer = null;
      const cleanup = () => { clearTimeout(timer); a.onended = a.onerror = a.onloadedmetadata = null; };
      a.onended = () => { cleanup(); resolve(); };
      this._abort = () => { cleanup(); try { a.pause(); } catch (e) { /* ignore */ } reject(Object.assign(new Error("interrupted"), { interrupted: true })); };
      a.onerror = () => { cleanup(); reject(new Error("audio element error " + (a.error ? a.error.code : ""))); };
      a.onloadedmetadata = () => {   // guard: never let one stuck clip block the queue
        clearTimeout(timer);
        const ms = ((a.duration || 10) * 1000) / (a.playbackRate || 1) + 4000;
        timer = setTimeout(() => { cleanup(); a.pause(); reject(new Error("playback did not finish")); }, ms);
      };
      timer = setTimeout(() => { cleanup(); a.pause(); reject(new Error("playback did not start")); }, 15000);
      a.src = url;
      a.volume = this.settings.volume;
      a.playbackRate = this.settings.rate || 1;
      const p = a.play();
      if (p && p.catch) {
        p.catch((e) => {
          cleanup();
          reject(new Error(e && e.name === "NotAllowedError" ? "audio blocked: tap the screen once to enable sound" : (e && e.message) || "play failed"));
        });
      }
    }));
  }

  _playBrowser(text) {
    return new Promise((resolve, reject) => {
      if (!this.supported) return reject(new Error("speech synthesis not supported"));
      const u = new SpeechSynthesisUtterance(text);
      u.rate = this.settings.rate; u.volume = this.settings.volume;
      const v = this.voices().find((x) => x.name === this.settings.voice);
      if (v) u.voice = v;
      let done = false;
      const timer = setTimeout(() => { done = true; resolve(); }, 1000 + text.length * 120);   // some WebKit versions never fire onend
      u.onend = () => { if (done) return; done = true; clearTimeout(timer); resolve(); };
      u.onerror = (e) => { if (done) return; done = true; clearTimeout(timer); reject(new Error((e && e.error) || "speech error")); };
      this._abort = () => {
        if (done) return; done = true; clearTimeout(timer);
        window.speechSynthesis.cancel();
        reject(Object.assign(new Error("interrupted"), { interrupted: true }));
      };
      window.speechSynthesis.speak(u);
    });
  }

  stop() {
    this.queue.clear();
    if (this.audio) { try { this.audio.pause(); } catch (e) { /* ignore */ } }
    if (this.supported) window.speechSynthesis.cancel();
    this.speaking = false;
    this._setStatus({ speaking: false, text: null });
  }
}
