"""SceneAssistant: on-demand online scene description, independent of the cloud provider.

Flow for one request (`describe`):
  validate + shrink the image (in memory only; never stored)  ->  consent / configured / breaker / rate checks
  ->  provider.analyze(): every attempt gets the FULL per-attempt timeout (never a leftover fraction of the budget);
      at most `max_retries` retries, only for a quick ProviderUnavailable (503 / 5xx / network error) and only if a
      full attempt still fits in the budget; a timed-out request (incl. 504 DEADLINE_EXCEEDED) is never repeated
  ->  safety filter (no distances, no "safe" / "no obstacles" claims)  ->  short spoken sentence (<= 400 chars).

Every outcome returns a dict with `ok` and a ready-to-speak `text`, so the phone can always say something
clear, including "Online scene description is unavailable right now. Local walking guidance continues."

Local walking guidance (awareness.py / pathguide.py) does not use this module at all.
"""
import os
import random
import re
import threading
import time

import cv2
import numpy as np

from .base import (BadResponse, NotConfigured, ProviderRateLimited, ProviderTimeout, ProviderUnavailable, Rejected,
                   SceneRequest, VisionError, scrub)

MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_SIDE = 1024            # images are re-encoded to at most 1024 px on the long side before upload
MIN_SIDE = 64
MAX_QUESTION = 300
MAX_SPOKEN = 400           # Piper / /api/tts limit
# Timeouts (2026-11-02 fix). The Gemini SDK sends the per-attempt timeout to the server as its deadline, and the
# server needs at least 10 s; the previous 12 s / 15 s values produced 504 DEADLINE_EXCEEDED and retries with a 4 s
# deadline (400 INVALID_ARGUMENT). 30 s / 45 s are assumptions (one live request already failed at 25 s), not
# measurements; override with NEUROSONIC_VISION_TIMEOUT_S / NEUROSONIC_VISION_BUDGET_S.
DEFAULT_ATTEMPT_TIMEOUT_S = 30.0
DEFAULT_BUDGET_S = 45.0
TIMEOUT_ENV, BUDGET_ENV = "NEUROSONIC_VISION_TIMEOUT_S", "NEUROSONIC_VISION_BUDGET_S"


def _env_seconds(name, default, log):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        v = float(raw)
        if v > 0:
            return v
    except ValueError:
        pass
    log(f"[vision] ignoring {name}={raw!r} (not a positive number); using {default:g} s")
    return default

TEXT = {
    "unavailable": "Online scene description is unavailable right now. Local walking guidance continues.",
    "timeout": "The online description took too long. Local walking guidance continues.",
    "paused": "Online scene description is paused after repeated failures. Local walking guidance continues.",
    "rate_limited": "Please wait a few seconds before asking again.",
    "hourly_cap": "The hourly limit for online descriptions has been reached. Local walking guidance continues.",
    "provider_rate_limited": "The online service is busy. Please try again in a minute. Local walking guidance continues.",
    "rejected": "The online service rejected the request. Online scene description is not working.",
    "bad_response": "The online description could not be understood. Local walking guidance continues.",
    "not_configured": "Online scene description is not set up on the laptop. Local walking guidance continues.",
    "disabled": "Online scene description is switched off. Local walking guidance continues.",
    "consent": "Online scene description is off until you allow sending camera images to the online service.",
    "error": "Online scene description failed. Local walking guidance continues.",
}

SYSTEM = (
    "You are NeuroSonic, an assistant for a blind or visually impaired pedestrian. You receive one photo from the "
    "person's phone camera. Describe only what is visible. Rules: "
    "1) Give positions only as left, centre or right of the image. "
    "2) Never estimate distances in metres, feet, steps or time, and never say how far something is. "
    "3) Never say that a path or crossing is safe, clear or free of obstacles; you cannot know that from one photo. "
    "4) Mention possible hazards (vehicles, steps, kerbs, holes, poles, water, crowds) only if they are visible, and "
    "call them possible. "
    "5) If the image is dark, blurred or unclear, say so in uncertainty and set image_quality accordingly. "
    "6) Use short, plain sentences suitable for being read aloud. "
    "Reply only with JSON in the requested format."
)

# --------------------------------------------------------------------- safety filter
_BANNED = [
    r"\bsafe(ly)?\b", r"\bsafety is\b", r"\bno (obstacles?|hazards?|dangers?)\b", r"\bobstacle[- ]free\b",
    r"\bfree (of|from) (obstacles?|hazards?)\b", r"\b(path|way|road|crossing|route) (is|looks|seems|appears) (clear|free|empty)\b",
    r"\bclear (path|way)\b", r"\bnothing (is )?in (your|the) way\b", r"\byou can (walk|cross|go|proceed)\b",
    r"\b\d+([.,]\d+)?\s*(m|cm|km|metres?|meters?|feet|foot|ft|yards?|steps?|paces?|seconds?)\b",
    r"\b(a few|few|couple of|several|one|two|three|four|five|ten) (metres|meters|feet|steps|paces|yards)\b",
    r"\b(close to you|right in front of you|very close|far away from you|nearby you)\b",
]
_BANNED_RE = re.compile("|".join(_BANNED), re.I)
CAUTION = "Please check the path yourself."


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def filter_text(text):
    """Drop sentences that claim safety/absence of obstacles or give distances. Returns (text, removed_count)."""
    kept, removed = [], 0
    for s in _sentences(text):
        if _BANNED_RE.search(s):
            removed += 1
        else:
            kept.append(s if s[-1] in ".!?" else s + ".")
    return " ".join(kept), removed


def is_spoken_text_safe(text):
    return not _BANNED_RE.search(text or "")


POS_WORDS = {
    "chest": {"left": "on the left", "centre": "in the centre", "right": "on the right", "unknown": ""},
    "handheld": {"left": "on the left of the camera view", "centre": "in the centre of the camera view",
                 "right": "on the right of the camera view", "unknown": ""},
}


def compose_speech(scene, question="", mode="chest"):
    """Structured scene -> one short spoken text (<= MAX_SPOKEN chars) + the filtered scene."""
    removed = 0
    if scene.get("image_quality") == "unusable":
        return "AI description: the image is too dark or blurred to describe. " + CAUTION, scene, 0
    main, r = filter_text(scene.get("answer") if question and scene.get("answer") else scene.get("summary", ""))
    removed += r
    words = POS_WORDS.get(mode, POS_WORDS["chest"])
    objs = []
    for o in scene.get("objects", [])[:4]:
        name, _ = filter_text(o["name"])
        if not name:
            removed += 1
            continue
        name = name.rstrip(".")
        w = words.get(o["position"], "")
        objs.append(f"{name} {w}".strip())
    hazards = []
    for h in scene.get("hazards", [])[:2]:
        t, r = filter_text(h)
        removed += r
        if t:
            hazards.append(t.rstrip("."))
    unc, r = filter_text(scene.get("uncertainty", ""))
    removed += r
    parts = ["AI description:"]
    if main:
        parts.append(main)
    if objs:
        parts.append("I can see " + (", ".join(objs[:-1]) + " and " + objs[-1] if len(objs) > 1 else objs[0]) + ".")
    if hazards:
        parts.append("Possible hazards: " + "; ".join(hazards) + ".")
    if scene.get("image_quality") == "poor":
        parts.append("The image is unclear.")
    elif unc:
        parts.append(_sentences(unc)[0] if _sentences(unc) else "")
    if removed:
        parts.append(CAUTION)
    text = " ".join(p for p in parts if p)
    if len(parts) == 1:
        text = "AI description: I could not describe this image. " + CAUTION
    if len(text) > MAX_SPOKEN:   # cut at a sentence boundary, keep the caution if it was needed
        tail = (" " + CAUTION) if removed else ""
        cut = ""
        for s in _sentences(text):
            if len(cut) + len(s) + 1 + len(tail) > MAX_SPOKEN:
                break
            cut = (cut + " " + s).strip()
        text = (cut + tail).strip()[:MAX_SPOKEN]
    return text, scene, removed


# --------------------------------------------------------------------- image handling (memory only)
def prepare_image(data, max_side=MAX_SIDE):
    """Validate a JPEG/PNG, downscale to <= max_side, re-encode as JPEG. Returns (jpeg_bytes, w, h)."""
    if not data:
        raise ValueError("empty image")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image too large")
    im = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        raise ValueError("not a readable JPEG or PNG image")
    h, w = im.shape[:2]
    if min(h, w) < MIN_SIDE:
        raise ValueError(f"image too small ({w}x{h})")
    s = min(1.0, max_side / max(h, w))
    if s < 1.0:
        im = cv2.resize(im, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("could not encode image")
    return buf.tobytes(), im.shape[1], im.shape[0]


def clean_question(q):
    q = re.sub(r"[\x00-\x1f\x7f]", " ", str(q or ""))
    return re.sub(r"\s+", " ", q).strip()[:MAX_QUESTION]


def build_prompt(question, mode):
    carry = ("The phone is worn on the chest, facing the walking direction." if mode == "chest" else
             "The phone is handheld; the camera may not point in the walking direction.")
    task = (f'The user asks: "{question}". Answer it in "answer" using only what is visible; if the photo cannot '
            "answer it, say so." if question else
            'Describe the surroundings in "summary"; leave "answer" empty.')
    return (f"{carry} {task} List up to 6 relevant objects with their position (left, centre or right of the "
            "image) and visible possible hazards. State uncertainty honestly.")


# --------------------------------------------------------------------- the assistant
class SceneAssistant:
    def __init__(self, provider, enabled=True, budget_s=None, per_try_timeout_s=None, max_retries=1,
                 min_interval_s=5.0, hourly_cap=60, breaker_threshold=3, breaker_cooldown_s=60.0,
                 clock=time.monotonic, sleep=time.sleep, rng=None, log=print):
        self.provider = provider
        self.enabled = enabled
        if per_try_timeout_s is None:
            per_try_timeout_s = _env_seconds(TIMEOUT_ENV, DEFAULT_ATTEMPT_TIMEOUT_S, log)
        if budget_s is None:
            budget_s = _env_seconds(BUDGET_ENV, DEFAULT_BUDGET_S, log)
        # an attempt is never shorter than the provider's minimum server deadline, and never longer than the budget
        per_try_timeout_s = max(float(per_try_timeout_s), getattr(provider, "min_timeout_s", 0.0) or 0.0)
        budget_s = max(float(budget_s), per_try_timeout_s)
        self.budget_s, self.per_try_timeout_s, self.max_retries = budget_s, per_try_timeout_s, max_retries
        self.min_interval_s, self.hourly_cap = min_interval_s, hourly_cap
        self.breaker_threshold, self.breaker_cooldown_s = breaker_threshold, breaker_cooldown_s
        self.clock, self.sleep = clock, sleep
        self.rng = rng or random.Random()
        self.log = log
        self._lock = threading.Lock()
        self._last_by_session = {}
        self._recent = []                 # start times of provider requests (hourly cap)
        self._fails = 0
        self._open_until = None
        self.stats = {"requests": 0, "ok": 0, "provider_calls": 0, "failures": {}, "last_latency_ms": None,
                      "last_error": None, "last_ok_at": None, "filtered_sentences": 0}

    # ------------------------------------------------------------ status (no secrets)
    def breaker_state(self):
        now = self.clock()
        if self._open_until is not None and now < self._open_until:
            return "open"
        return "closed" if self._fails == 0 else "half-open" if self._open_until is not None else "closed"

    def info(self):
        p = self.provider
        configured = bool(p and p.configured())
        now = self.clock()
        used = len([t for t in self._recent if now - t < 3600])
        return {
            "available": bool(self.enabled and configured and self.breaker_state() != "open"),
            "enabled": self.enabled, "configured": configured,
            "provider": getattr(p, "name", None), "model": getattr(p, "model", None),
            "problem": None if configured else (p.problem() if p else "no provider"),
            "breaker": self.breaker_state(),
            "retry_after_s": max(0, round(self._open_until - now)) if self.breaker_state() == "open" else 0,
            "requests_this_hour": used, "hourly_cap": self.hourly_cap, "min_interval_s": self.min_interval_s,
            "attempt_timeout_s": self.per_try_timeout_s, "budget_s": self.budget_s, "max_retries": self.max_retries,
            "requires_internet": True, "requires_consent": True, "stores_images": False,
            "limits": "positions are left/centre/right only; no distances; never confirms that a path is safe",
            **{k: v for k, v in self.stats.items()},
        }

    # ------------------------------------------------------------ helpers
    def _fail(self, code, detail=None, retry_after=None, **extra):
        self.stats["failures"][code] = self.stats["failures"].get(code, 0) + 1
        if detail:
            self.stats["last_error"] = f"{code}: {scrub(detail)}"
        out = {"ok": False, "code": code, "text": TEXT.get(code, TEXT["error"]), "provider": getattr(self.provider, "name", None),
               "model": getattr(self.provider, "model", None), "cloud": True}
        if retry_after is not None:
            out["retry_after_s"] = retry_after
        out.update(extra)
        return out

    def _record_provider_failure(self):
        self._fails += 1
        if self._fails >= self.breaker_threshold:
            self._open_until = self.clock() + self.breaker_cooldown_s

    def _record_provider_success(self):
        self._fails = 0
        self._open_until = None

    # ------------------------------------------------------------ main entry
    def describe(self, image_bytes, question="", mode="chest", session="default", consent=False):
        mode = mode if mode in ("chest", "handheld") else "chest"
        question = clean_question(question)
        with self._lock:
            self.stats["requests"] += 1
            if not self.enabled:
                return self._fail("disabled")
            if not consent:
                return self._fail("consent")
            if not self.provider or not self.provider.configured():
                return self._fail("not_configured", self.provider.problem() if self.provider else "no provider")
            now = self.clock()
            if self.breaker_state() == "open":
                return self._fail("paused", retry_after=max(1, round(self._open_until - now)))
            last = self._last_by_session.get(session)
            if last is not None and now - last < self.min_interval_s:
                return self._fail("rate_limited", retry_after=max(1, round(self.min_interval_s - (now - last))))
            self._recent = [t for t in self._recent if now - t < 3600]
            if len(self._recent) >= self.hourly_cap:
                return self._fail("hourly_cap")
            self._last_by_session[session] = now
            self._recent.append(now)
        # image validation outside the lock (CPU work); raises ValueError -> HTTP 400 at the server
        jpeg, w, h = prepare_image(image_bytes)
        req = SceneRequest(image=jpeg, question=question, mode=mode, width=w, height=h)
        prompt = build_prompt(question, mode)
        t0 = self.clock()
        attempt, last_err = 0, None
        while True:
            attempt += 1
            self.stats["provider_calls"] += 1
            try:
                # always the full per-attempt timeout: a shrunken deadline is rejected by the server (< 10 s) or
                # just times out sooner
                reply = self.provider.analyze(req, prompt, SYSTEM, self.per_try_timeout_s)
            except VisionError as e:
                last_err = e
                if e.retryable and attempt <= self.max_retries:
                    backoff = 0.8 + 0.8 * self.rng.random()           # short jittered pause, then one more try
                    if self.budget_s - (self.clock() - t0) - backoff >= self.per_try_timeout_s:
                        self.sleep(backoff)
                        continue                                      # a full attempt still fits
                break
            except Exception as e:                                    # unexpected provider bug: never crash the server
                last_err = VisionError(f"{type(e).__name__}: {e}")
                break
            latency = int((self.clock() - t0) * 1000)
            with self._lock:
                self._record_provider_success()
                text, scene, removed = compose_speech(reply.scene, question, mode)
                self.stats.update(ok=self.stats["ok"] + 1, last_latency_ms=latency, last_ok_at=time.time(),
                                  filtered_sentences=self.stats["filtered_sentences"] + removed)
            self.log(f"[vision] {session}: ok in {latency} ms ({self.provider.name}/{reply.model}, "
                     f"{attempt} attempt{'s' if attempt > 1 else ''}, {removed} sentence(s) filtered)")
            return {"ok": True, "code": "ok", "text": text, "summary": scene["summary"], "answer": scene["answer"],
                    "objects": scene["objects"], "hazards": scene["hazards"], "uncertainty": scene["uncertainty"],
                    "image_quality": scene["image_quality"], "filtered_sentences": removed,
                    "question": question, "provider": self.provider.name, "model": reply.model or self.provider.model,
                    "latency_ms": latency, "attempts": attempt, "cloud": True,
                    "notice": "AI-generated description. It may be wrong and does not confirm that any path is safe."}
        # failure
        latency = int((self.clock() - t0) * 1000)
        with self._lock:
            if isinstance(last_err, (ProviderUnavailable, ProviderTimeout, ProviderRateLimited, BadResponse)) or \
                    type(last_err) is VisionError:
                self._record_provider_failure()
            self.stats["last_latency_ms"] = latency
            code = getattr(last_err, "code", "error")
            out = self._fail(code, str(last_err), attempts=attempt, latency_ms=latency)
        self.log(f"[vision] {session}: FAILED {code} after {attempt} attempt(s), {latency} ms: {scrub(last_err)}")
        return out


__all__ = ["SceneAssistant", "compose_speech", "filter_text", "is_spoken_text_safe", "prepare_image", "build_prompt",
           "SYSTEM", "TEXT", "NotConfigured", "Rejected"]
