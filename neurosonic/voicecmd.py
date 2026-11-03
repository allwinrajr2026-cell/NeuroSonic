"""Offline voice commands: Vosk speech recognition (Indian-English small model) on the laptop.

The phone records a short utterance (push-to-talk), sends 16 kHz mono 16-bit WAV, and gets back the recognised
text and an *intent*. Two recognisers run on the same audio:
  * grammar-restricted (command words only) - robust for the fixed commands;
  * free dictation - used for destination names after "navigate to" / "search for".
Destination names are resolved against the offline map's place index (exact/prefix search, then fuzzy matching),
because Vosk's vocabulary does not contain most Vellore place names.

Model: vosk-model-small-en-in-0.4 (Alpha Cephei, Apache-2.0), engine vosk 0.3.45 (Apache-2.0). No network access.
"""
import difflib
import io
import json
import re
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "asr" / "vosk-model-small-en-in-0.4"
MAX_SECONDS = 8
COMMAND_WORDS = ["start", "stop", "navigation", "guidance", "repeat", "instruction", "again", "status", "where", "am",
                 "i", "my", "awareness", "camera", "detection", "search", "for", "find", "navigate", "to", "take", "me",
                 "go", "help", "what", "is", "the", "test", "voice",
                 # online scene description (Sprint 1)
                 "describe", "surroundings", "around", "in", "front", "of", "see", "scene", "there", "can", "you",
                 "[unk]"]
HELP_TEXT = ("You can say: navigate to, followed by a place. Search for, followed by a place. Start navigation. "
             "Stop navigation. Repeat instruction. Start awareness. Stop awareness. Status. Test voice. "
             "Or, with online description allowed: describe surroundings, or ask a question such as is there a bus.")


class VoiceCommandError(RuntimeError):
    pass


# --- sound-alike matching for place names the recogniser cannot spell ("Katpadi" is heard as "cut body")
_SPELLED = {"see": "c", "sea": "c", "si": "c", "em": "m", "him": "m", "am": "m", "vee": "v", "we": "v", "eye": "i",
            "tea": "t", "bee": "b", "dee": "d", "jay": "j", "kay": "k", "ess": "s", "pee": "p", "are": "r", "en": "n"}
_STOP = {"the", "a", "an", "to", "for", "of", "near", "please"}


def phonetic(text):
    """Crude phonetic key: spelled letters -> letters, similar consonants merged, vowels dropped (except first)."""
    words = [_SPELLED.get(w, w) for w in re.findall(r"[a-z]+", str(text).lower()) if w not in _STOP]
    s = "".join(words)
    for a, b in (("ph", "f"), ("th", "t"), ("sh", "s"), ("ch", "c"), ("gh", "g"), ("ck", "k")):
        s = s.replace(a, b)
    out = []
    for i, ch in enumerate(s):
        ch = {"c": "k", "q": "k", "z": "s", "w": "v", "b": "p", "d": "t", "j": "g"}.get(ch, ch)
        if ch in "aeiouyh" and i > 0:
            continue
        if out and out[-1] == ch:
            continue
        out.append(ch)
    return "".join(out)


def place_score(query, name):
    q = " ".join(w for w in query.lower().split() if w not in _STOP)
    n = name.lower()
    text = difflib.SequenceMatcher(None, q, n).ratio()
    pq, pn = phonetic(q), phonetic(n)
    phon = difflib.SequenceMatcher(None, pq, pn).ratio() if pq and pn else 0.0
    # also allow the query to match the start of a longer name ("katpadi" vs "katpadi junction")
    pfx = difflib.SequenceMatcher(None, pq, pn[:len(pq)]).ratio() * 0.95 if len(pq) >= 3 else 0.0
    # (a word-by-word measure was tried and removed: it lowered top-1 accuracy from 10/24 to 8/24)
    return max(text, phon, pfx)


def parse_intent(grammar_text, free_text):
    """-> (intent, query). intent in: navigate, search, start_navigation, stop_navigation, repeat, status,
    awareness_on, awareness_off, help, test_voice, describe_scene, ask_scene, unknown."""
    g = " ".join((grammar_text or "").lower().split())
    f = " ".join((free_text or "").lower().split())
    gw, fw = set(g.split()), set(f.split())
    words = gw | fw
    # destination commands take the free text (names are outside the command grammar)
    m = re.search(r"\b(?:navigate|take me|guide me|go)\s+to\s+(.+)$", f) or re.search(r"\bnavigate\s+(.+)$", f)
    if m and m.group(1).strip() not in ("", "the"):
        return "navigate", m.group(1).strip()
    m = re.search(r"\b(?:search|find|look)\s+(?:for\s+)?(.+)$", f)
    if m and m.group(1).strip():
        return "search", m.group(1).strip()
    # the free recogniser often mangles the command word itself ("navigate to katpadi" -> "they took cut body");
    # the grammar recogniser catches it reliably. The place is then searched in the whole free text.
    lead = {"navigate", "navigation", "to", "search", "for", "find", "take", "me", "go", "please", "the"}
    fw_list = f.split()
    while fw_list and fw_list[0] in lead:     # drop command words heard correctly; the place name must remain
        fw_list.pop(0)
    rest = " ".join(fw_list) or None
    if "navigate" in gw or {"take", "me"} <= gw or ("go" in gw and "to" in gw):
        return "navigate", rest
    if {"search", "find"} & gw:
        return "search", rest
    nav = {"navigation", "guidance", "navigating"} & words
    aware = {"awareness", "camera", "detection"} & words
    if "stop" in words and aware:
        return "awareness_off", None
    if "start" in words and aware:
        return "awareness_on", None
    if "stop" in words and nav:
        return "stop_navigation", None
    if "start" in words and nav:
        return "start_navigation", None
    if "repeat" in words or ("again" in words and len(words) <= 3):
        return "repeat", None
    if "status" in words or (({"where", "why"} & words) and ({"am", "my"} & words)):
        return "status", None
    if "test" in words and "voice" in words:
        return "test_voice", None
    # online scene description (checked after every existing command, so those keep priority)
    if ("describe" in words or "surroundings" in words or "scene" in words or {"around", "me"} <= words
            or {"in", "front"} <= words):
        return "describe_scene", None
    m = re.match(r"^(?:is there|are there|can you see|do you see|what is|what's|where is|how many)\b.*", f)
    if m and len(f.split()) >= 3:
        return "ask_scene", f
    if "help" in words:
        return "help", None
    return "unknown", None


def read_wav16k(data):
    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise VoiceCommandError("audio must be mono 16-bit PCM WAV")
            if w.getframerate() != 16000:
                raise VoiceCommandError("audio must be 16 kHz")
            if w.getnframes() > 16000 * MAX_SECONDS:
                raise VoiceCommandError(f"audio longer than {MAX_SECONDS} s")
            return w.readframes(w.getnframes())
    except (wave.Error, EOFError) as e:
        raise VoiceCommandError(f"invalid WAV: {e}")


class VoiceCommands:
    def __init__(self, model_dir=DEFAULT_MODEL, offline_map=None):
        self.model_dir = Path(model_dir)
        self.offline_map = offline_map
        self._model = None
        self._lock = threading.Lock()
        self.error = None
        self.stats = {"recognised": 0, "last_ms": None, "load_ms": None}

    def available(self):
        if not (self.model_dir / "am").is_dir():
            self.error = f"speech model missing: {self.model_dir}"
            return False
        try:
            import vosk  # noqa: F401
        except ImportError as e:
            self.error = f"vosk not installed: {e}"
            return False
        return True

    def info(self):
        return {"available": self.available(), "engine": "vosk 0.3.45 (Apache-2.0)", "model": self.model_dir.name,
                "language": "en-IN", "offline": True, "error": self.error, "help": HELP_TEXT, **self.stats}

    def _load(self):
        if self._model is None:
            if not self.available():
                raise VoiceCommandError(self.error)
            from vosk import Model, SetLogLevel
            SetLogLevel(-1)
            t = time.perf_counter()
            self._model = Model(str(self.model_dir))
            self.stats["load_ms"] = round((time.perf_counter() - t) * 1000)
        return self._model

    def warm_up(self):
        try:
            with self._lock:
                self._load()
            return True
        except VoiceCommandError:
            return False

    def transcribe(self, pcm16k):
        from vosk import KaldiRecognizer
        with self._lock:
            model = self._load()
            t = time.perf_counter()
            out = []
            for grammar in (json.dumps(COMMAND_WORDS), None):
                rec = KaldiRecognizer(model, 16000, grammar) if grammar else KaldiRecognizer(model, 16000)
                rec.AcceptWaveform(pcm16k)
                out.append(json.loads(rec.FinalResult()).get("text", ""))
            self.stats["last_ms"] = round((time.perf_counter() - t) * 1000)
            self.stats["recognised"] += 1
        return out[0].replace("[unk]", "").strip(), out[1]

    # ------------------------------------------------------------------ places
    def resolve_place(self, query, near=None, limit=3, saved=None):
        if not query:
            return []
        # the user's own saved places first ("home", "office"): ordinary words the recogniser knows
        if saved:
            best = sorted(((place_score(query, p["name"]), p) for p in saved), key=lambda t: -t[0])
            if best and best[0][0] >= 0.75:
                return [dict(best[0][1], match="saved place", kind="saved place")]
        if self.offline_map is None:
            return []
        hits = self.offline_map.search(query, limit=limit, near=near)
        if hits:
            return [dict(h, match="text") for h in hits]
        # sound-alike: speech recognisers misspell local names; score every name by text and phonetic similarity
        names = {}
        for p in self.offline_map.places:
            names.setdefault(p["name"].lower(), p)
        # try the query with 0..4 leading words dropped (left-over, misheard command words) and keep the best
        words = query.lower().split()
        variants = [" ".join(words[i:]) for i in range(0, min(5, len(words)))] or [query]
        # each dropped word costs 10 %: otherwise a lone trailing word ("start") matches the start of many names
        scored = sorted(((max(place_score(v, nm) * (1 - 0.1 * i) for i, v in enumerate(variants)), nm) for nm in names),
                        reverse=True)
        return [dict(names[nm], match="sound-alike", score=round(s, 2)) for s, nm in scored[:limit] if s >= 0.6]

    def handle(self, wav_bytes, near=None, saved=None):
        pcm = read_wav16k(wav_bytes)
        if len(pcm) < 16000 * 2 * 0.3:
            raise VoiceCommandError("recording too short")
        g, f = self.transcribe(pcm)
        intent, query = parse_intent(g, f)
        res = {"heard": f or g, "heard_commands": g, "heard_free": f, "intent": intent, "query": query, "places": []}
        if intent in ("navigate", "search"):
            if not query:
                res["message"] = "I heard the command but not the place name. Please say the place name again."
            else:
                res["places"] = self.resolve_place(query, near=near, saved=saved)
        if intent == "help":
            res["message"] = HELP_TEXT
        elif intent == "unknown":
            res["message"] = (f"Sorry, I did not understand: {f or g or 'nothing heard'}. Say help for the commands."
                              if (f or g) else "Sorry, I did not hear anything. Hold the phone closer and try again.")
        return res
