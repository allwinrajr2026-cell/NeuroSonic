"""Provider-independent foundation for online scene description (Sprint 1, 2026-11-02).

A *provider* (Gemini, a mock, later others) only has to turn one image + a prompt into the JSON object described by
SCENE_SCHEMA. Everything else - prompts, retries, rate limits, the circuit breaker, safety filtering and the spoken
sentence - lives in assistant.py and is the same for every provider.

Errors are typed so the assistant can decide what to retry and what to tell the user. Messages must never contain
an API key: providers pass every message through scrub().
"""
import json
import re
from dataclasses import dataclass, field


# ------------------------------------------------------------------ errors
class VisionError(Exception):
    """Base class. `code` is a short machine-readable reason; `retryable` says whether one more try may help."""
    code = "error"
    retryable = False


class NotConfigured(VisionError):
    code = "not_configured"


class ProviderUnavailable(VisionError):      # HTTP 5xx (e.g. Gemini 503), network down, DNS failure
    code = "unavailable"
    retryable = True


class ProviderTimeout(VisionError):           # includes HTTP 504 DEADLINE_EXCEEDED
    code = "timeout"
    retryable = False    # a timed-out request already used its time; repeating a slow request only doubles the wait


class ProviderRateLimited(VisionError):      # HTTP 429 from the provider: retrying at once does not help
    code = "provider_rate_limited"


class Rejected(VisionError):                 # HTTP 400/401/403/404: bad key, unknown model, invalid request
    code = "rejected"


class BadResponse(VisionError):              # the reply could not be parsed / did not match the schema
    code = "bad_response"


# ------------------------------------------------------------------ request / reply
@dataclass
class SceneRequest:
    image: bytes                 # JPEG bytes (already validated and size-limited by the assistant)
    mime: str = "image/jpeg"
    question: str = ""           # optional natural-language question about the surroundings
    mode: str = "chest"          # chest | handheld (how the phone is carried)
    width: int = 0
    height: int = 0


@dataclass
class ProviderReply:
    scene: dict                  # parsed and normalised (see parse_scene)
    model: str = ""
    latency_ms: int = 0
    raw_chars: int = 0
    extra: dict = field(default_factory=dict)


class VisionProvider:
    """Interface. Subclasses set `name` and `model` and implement configured() and analyze()."""
    name = "base"
    model = ""
    min_timeout_s = 0.0          # shortest deadline the provider's server accepts (Gemini: 10 s)

    def configured(self):
        """True if the provider can be called (e.g. an API key exists). Must not reveal the key."""
        return False

    def problem(self):
        """Short human-readable reason why configured() is False (never containing secrets)."""
        return "not configured"

    def analyze(self, request, prompt, system, timeout_s):
        """One call. Returns ProviderReply or raises a VisionError subclass. Must not retry by itself."""
        raise NotConfigured(self.problem())


# ------------------------------------------------------------------ the structured answer
POSITIONS = ("left", "centre", "right", "unknown")
QUALITIES = ("good", "poor", "unusable")
SCENE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "one or two short sentences describing the scene"},
        "answer": {"type": "string", "description": "direct answer to the user's question, or empty if none"},
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "position": {"type": "string", "enum": list(POSITIONS)},
                    "note": {"type": "string"},
                },
                "required": ["name", "position"],
            },
        },
        "hazards": {"type": "array", "items": {"type": "string"}},
        "uncertainty": {"type": "string"},
        "image_quality": {"type": "string", "enum": list(QUALITIES)},
    },
    "required": ["summary", "objects", "hazards", "uncertainty", "image_quality"],
}


def _text(v, limit=300):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def parse_scene(text):
    """Model output (JSON, possibly inside a ``` fence) -> normalised dict. Raises BadResponse."""
    if not isinstance(text, str) or not text.strip():
        raise BadResponse("empty reply")
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            raise BadResponse("reply is not JSON")
        try:
            d = json.loads(t[i:j + 1])
        except json.JSONDecodeError:
            raise BadResponse("reply is not valid JSON")
    if not isinstance(d, dict) or "summary" not in d:
        raise BadResponse("reply does not match the scene format")
    objects = []
    for o in d.get("objects") or []:
        if isinstance(o, dict) and _text(o.get("name"), 60):
            pos = str(o.get("position", "unknown")).lower().replace("center", "centre")
            objects.append({"name": _text(o["name"], 60), "position": pos if pos in POSITIONS else "unknown",
                            "note": _text(o.get("note"), 120)})
    q = str(d.get("image_quality", "good")).lower()
    return {
        "summary": _text(d.get("summary")),
        "answer": _text(d.get("answer")),
        "objects": objects[:12],
        "hazards": [_text(h, 160) for h in (d.get("hazards") or []) if _text(h, 160)][:6],
        "uncertainty": _text(d.get("uncertainty"), 200),
        "image_quality": q if q in QUALITIES else "good",
    }


# ------------------------------------------------------------------ secrets
_KEYLIKE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|(?i:(?:api[_-]?key|key|token)=)[^&\s\"']+")


def scrub(message, *secrets):
    """Remove API keys (given explicitly, and anything key-like) from a message before it is logged or returned."""
    s = str(message)
    for sec in secrets:
        if sec:
            s = s.replace(sec, "[REDACTED]")
    return _KEYLIKE.sub("[REDACTED]", s)[:300]
