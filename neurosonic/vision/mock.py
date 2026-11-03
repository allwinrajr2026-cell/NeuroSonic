"""Deterministic mock provider for tests and offline demonstrations. Makes no network access.

`script` is a list of outcomes consumed one per call (the last one repeats):
  "ok"        a fixed street scene
  "503"       ProviderUnavailable (like Gemini's "503 UNAVAILABLE")
  "timeout"   ProviderTimeout
  "429"       ProviderRateLimited
  "rejected"  Rejected (e.g. invalid key / unknown model)
  "bad"       a malformed reply -> BadResponse
  "unsafe"    a reply that claims the path is safe and gives distances (to test the safety filter)
  "dark"      image_quality "unusable"
  "slowN"     answer after N seconds of real time (e.g. "slow20"); ProviderTimeout if N exceeds the timeout
  a dict      returned as the scene (parsed like real output)
"""
import json
import time

from .base import (BadResponse, ProviderRateLimited, ProviderReply, ProviderTimeout, ProviderUnavailable,
                   Rejected, VisionProvider, parse_scene)

STREET_SCENE = {
    "summary": "A street with parked cars and a few people walking on the left side.",
    "answer": "",
    "objects": [
        {"name": "person", "position": "left", "note": "walking towards the camera"},
        {"name": "car", "position": "right", "note": "parked"},
        {"name": "motorcycle", "position": "centre", "note": "moving"},
    ],
    "hazards": ["A motorcycle appears to be moving in the centre of the view."],
    "uncertainty": "Objects far away are hard to identify.",
    "image_quality": "good",
}
UNSAFE_SCENE = {
    "summary": "The path ahead is clear and safe to walk. There are no obstacles.",
    "answer": "Yes, you can walk forward safely for about 10 metres.",
    "objects": [{"name": "bench", "position": "left", "note": "2 metres away"}],
    "hazards": ["A kerb about 3 steps ahead."],
    "uncertainty": "",
    "image_quality": "good",
}


class MockProvider(VisionProvider):
    name = "mock"

    def __init__(self, script=("ok",), model="mock-vision-1", latency_s=0.0, configured=True):
        self.model = model
        self.script = list(script) or ["ok"]
        self.latency_s = latency_s
        self._configured = configured
        self.calls = []            # (question, image_bytes_len, prompt) per call - never the image itself

    def configured(self):
        return self._configured

    def problem(self):
        return "mock provider disabled" if not self._configured else ""

    def analyze(self, request, prompt, system, timeout_s):
        self.calls.append({"question": request.question, "image_bytes": len(request.image), "prompt": prompt,
                           "timeout_s": timeout_s})
        outcome = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if self.latency_s:
            time.sleep(min(self.latency_s, timeout_s))
            if self.latency_s > timeout_s:
                raise ProviderTimeout(f"mock: no reply within {timeout_s:.1f} s")
        if isinstance(outcome, str) and outcome.startswith("slow"):
            delay = float(outcome[4:] or 0)
            time.sleep(min(delay, timeout_s))
            if delay > timeout_s:
                raise ProviderTimeout(f"mock: no reply within {timeout_s:.1f} s")
            outcome = "ok"
        if outcome == "503":
            raise ProviderUnavailable("503 UNAVAILABLE. The model is overloaded. Please try again later.")
        if outcome == "timeout":
            raise ProviderTimeout(f"mock: no reply within {timeout_s:.1f} s")
        if outcome == "429":
            raise ProviderRateLimited("429 RESOURCE_EXHAUSTED")
        if outcome == "rejected":
            raise Rejected("400 INVALID_ARGUMENT")
        if outcome == "bad":
            return ProviderReply(scene=parse_scene("Sorry, I cannot help with that."), model=self.model)
        scene = {"unsafe": UNSAFE_SCENE, "dark": dict(STREET_SCENE, objects=[], hazards=[], image_quality="unusable",
                                                     summary="The image is too dark to see anything.")}.get(
            outcome, outcome if isinstance(outcome, dict) else STREET_SCENE)
        scene = dict(scene)
        if request.question and not scene.get("answer"):
            scene["answer"] = f"Regarding your question: {STREET_SCENE['summary']}"
        text = json.dumps(scene)
        return ProviderReply(scene=parse_scene(text), model=self.model, latency_ms=int(self.latency_s * 1000),
                             raw_chars=len(text))


__all__ = ["MockProvider", "STREET_SCENE", "UNSAFE_SCENE", "BadResponse"]
