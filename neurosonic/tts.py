"""Local neural text-to-speech (Piper) for NeuroSonic. Runs on the laptop; audio is sent to the phone as WAV.

Engine:  piper-tts 1.8.0 (OHF-Voice/piper1-gpl, GPL-3.0-or-later; bundles espeak-ng for phonemisation)
Voice:   models/tts/en_IN-spicor/en_IN-spicor.onnx  (navgurukul-ai-labs/text-to-speech-en-IN-piper, AGPL-3.0,
         Indian-English voice fine-tuned from the Piper LJSpeech base; 22.05 kHz mono)
No network access: the model and espeak-ng data are local. Generated audio is cached on disk by text hash.
"""
import hashlib
import io
import json
import threading
import time
import wave
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOICE = ROOT / "models" / "tts" / "en_IN-spicor" / "en_IN-spicor.onnx"
MAX_CHARS = 400
CACHE_FILES = 400
# Speaking style (2026-11-02 refinement). Piper's VITS defaults for this voice are noise 0.667 / noise_w 0.8 /
# length 1.0. Slightly slower speech and less random variation give calmer, steadier announcements. These values
# are a subjective tuning choice; they have not been rated by listeners.
STYLE = {"length_scale": 1.08, "noise_scale": 0.6, "noise_w_scale": 0.7}


class TTSError(RuntimeError):
    pass


class PiperTTS:
    def __init__(self, model_path=DEFAULT_VOICE, cache_dir=None, style=None):
        self.model_path = Path(model_path)
        self.style = dict(STYLE if style is None else style)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._voice = None
        self._lock = threading.Lock()
        self.error = None
        self.stats = {"synthesised": 0, "cache_hits": 0, "last_ms": None}
        self._mem = OrderedDict()   # small in-memory cache for repeated alerts

    # ------------------------------------------------------------------ status
    def info(self):
        cfg = self.model_path.with_suffix(".onnx.json")
        meta = {}
        if cfg.exists():
            c = json.loads(cfg.read_text(encoding="utf-8"))
            meta = {"sample_rate": c.get("audio", {}).get("sample_rate"), "espeak_voice": c.get("espeak", {}).get("voice")}
        return {"engine": "piper", "engine_version": _piper_version(), "engine_licence": "GPL-3.0-or-later",
                "voice": self.model_path.stem, "voice_licence": "AGPL-3.0 (navgurukul-ai-labs/text-to-speech-en-IN-piper)",
                "language": "en-IN", "model_present": self.model_path.exists(), "loaded": self._voice is not None,
                "available": self.available(), "error": self.error, "style": dict(self.style), **meta, **self.stats}

    def available(self):
        if not self.model_path.exists():
            self.error = f"voice model missing: {self.model_path}"
            return False
        try:
            import piper  # noqa: F401
        except ImportError as e:
            self.error = f"piper-tts not installed: {e}"
            return False
        return True

    def _load(self):
        if self._voice is None:
            if not self.available():
                raise TTSError(self.error)
            from piper import PiperVoice
            t = time.perf_counter()
            self._voice = PiperVoice.load(str(self.model_path))
            self.stats["load_ms"] = round((time.perf_counter() - t) * 1000)
        return self._voice

    def warm_up(self):
        """Load the voice model now (not on the first request) and check that synthesis works."""
        try:
            with self._lock:
                self._load()
            self.synthesize("Ready.")
            return True
        except TTSError:
            return False

    # ------------------------------------------------------------------ synthesis
    @staticmethod
    def clean(text):
        text = " ".join(str(text).split())
        if not text:
            raise TTSError("empty text")
        if len(text) > MAX_CHARS:
            raise TTSError(f"text longer than {MAX_CHARS} characters")
        return text

    def synthesize(self, text):
        """Returns WAV bytes (16-bit PCM mono)."""
        text = self.clean(text)
        style_id = ",".join(f"{k}={v}" for k, v in sorted(self.style.items()))
        key = hashlib.sha256((self.model_path.name + "\0" + style_id + "\0" + text).encode("utf-8")).hexdigest()
        if key in self._mem:
            self._mem.move_to_end(key)
            self.stats["cache_hits"] += 1
            return self._mem[key]
        path = self.cache_dir / f"{key}.wav" if self.cache_dir else None
        if path is not None and path.exists():
            data = path.read_bytes()
            self.stats["cache_hits"] += 1
        else:
            with self._lock:
                voice = self._load()
                t = time.perf_counter()
                buf = io.BytesIO()
                try:
                    with wave.open(buf, "wb") as w:
                        voice.synthesize_wav(text, w, syn_config=self._syn_config())
                except Exception as e:  # never crash the server on a synthesis failure
                    self.error = f"synthesis failed: {type(e).__name__}: {e}"
                    raise TTSError(self.error)
                self.stats["last_ms"] = round((time.perf_counter() - t) * 1000)
                self.stats["synthesised"] += 1
                self.error = None
            data = buf.getvalue()
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                self._trim_cache()
        self._mem[key] = data
        if len(self._mem) > 64:
            self._mem.popitem(last=False)
        return data

    def _syn_config(self):
        if not self.style:
            return None
        from piper import SynthesisConfig
        return SynthesisConfig(**self.style)

    def _trim_cache(self):
        files = sorted(self.cache_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime)
        for p in files[:-CACHE_FILES]:
            p.unlink(missing_ok=True)


def _piper_version():
    try:
        from importlib.metadata import version
        return version("piper-tts")
    except Exception:
        return None


def wav_duration(data):
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()
