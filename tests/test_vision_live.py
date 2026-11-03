"""OPT-IN live test of the real Gemini provider. Skipped unless NEUROSONIC_LIVE_VISION=1.

Makes EXACTLY ONE request (SceneAssistant max_retries=0; the SDK's own retries are off), with the image
F:\\Projects\\WOAD-Research\\test_street.jpg, and records the outcome (text and metadata only, never the image) to
data/vision_live_result.json. A 503 / timeout is a valid, recorded outcome: the test checks that it is handled and
spoken clearly, not that the cloud service is up.

    set NEUROSONIC_LIVE_VISION=1 && ..\\.venv\\Scripts\\python -m unittest tests.test_vision_live -v
"""
import json
import os
import time
import unittest
from pathlib import Path

from tests._common import ROOT
from neurosonic.vision import SceneAssistant, is_spoken_text_safe
from neurosonic.vision.assistant import TEXT
from neurosonic.vision.gemini import GeminiProvider, read_key

IMAGE = ROOT.parent / "test_street.jpg"
OUT = ROOT / "data" / "vision_live_result.json"


@unittest.skipUnless(os.environ.get("NEUROSONIC_LIVE_VISION") == "1", "live cloud test (set NEUROSONIC_LIVE_VISION=1)")
class TestGeminiLive(unittest.TestCase):
    def test_one_real_request(self):
        self.assertTrue(IMAGE.exists(), IMAGE)
        provider = GeminiProvider()
        self.assertTrue(provider.configured(), provider.problem())
        logs = []
        a = SceneAssistant(provider, max_retries=0, budget_s=30.0, per_try_timeout_s=25.0, log=logs.append)
        started = time.strftime("%Y-%m-%d %H:%M:%S %z")
        r = a.describe(IMAGE.read_bytes(), mode="chest", session="live-test", consent=True)
        info = a.info()
        record = {"started": started, "image": str(IMAGE), "model_requested": provider.model,
                  "provider_calls": info["provider_calls"], "result": r, "log": logs,
                  "breaker_after": info["breaker"]}
        text = json.dumps(record, indent=1, ensure_ascii=False)
        self.assertNotIn(read_key() or "\0", text)                     # the key never appears in the record
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
        print("\nLIVE RESULT:\n" + text)
        self.assertEqual(info["provider_calls"], 1)                     # exactly one real request
        self.assertIsInstance(r["ok"], bool)
        self.assertTrue(r["text"])
        if r["ok"]:
            self.assertTrue(r["text"].startswith("AI description:"))
            self.assertTrue(is_spoken_text_safe(r["text"]), r["text"])
            self.assertLessEqual(len(r["text"]), 400)
        else:
            self.assertIn(r["code"], TEXT)
            self.assertEqual(r["text"], TEXT[r["code"]])


if __name__ == "__main__":
    unittest.main()
