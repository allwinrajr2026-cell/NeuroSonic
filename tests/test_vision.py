"""Online scene description (Sprint 1): provider abstraction, SceneAssistant, safety filter, failure handling.
Only the mock provider is used here - no real cloud call is ever made (checked with tests/_offline.py)."""
import unittest

import cv2
import numpy as np

from tests._common import ROOT
from tests._offline import no_internet
from neurosonic.vision import (MockProvider, SceneAssistant, compose_speech, filter_text, is_spoken_text_safe,
                               parse_scene, scrub)
from neurosonic.vision.assistant import MAX_SPOKEN, TEXT, prepare_image
from neurosonic.vision.base import BadResponse

DEMO = ROOT / "demo_data" / "detec_test" / "ir" / "0000060683.png"


def jpeg(w=640, h=480, path=DEMO):
    im = cv2.imread(str(path)) if path and path.exists() else np.full((h, w, 3), 120, np.uint8)
    im = cv2.resize(im, (w, h))
    return cv2.imencode(".jpg", im)[1].tobytes()


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def make(script=("ok",), **kw):
    clock = FakeClock()
    prov = MockProvider(script=script)
    logs = []
    a = SceneAssistant(prov, clock=clock, sleep=clock.sleep, log=logs.append, **kw)
    return a, prov, clock, logs


class TestSceneAssistant(unittest.TestCase):
    def test_success_gives_short_spoken_text_with_positions(self):
        a, prov, _, logs = make()
        with no_internet() as attempts:
            r = a.describe(jpeg(), consent=True)
        self.assertEqual(attempts, [])
        self.assertTrue(r["ok"])
        self.assertTrue(r["text"].startswith("AI description:"))
        self.assertIn("person on the left", r["text"])
        self.assertIn("car on the right", r["text"])
        self.assertIn("Possible hazards:", r["text"])
        self.assertLessEqual(len(r["text"]), MAX_SPOKEN)
        self.assertEqual([o["position"] for o in r["objects"]], ["left", "right", "centre"])
        self.assertIn("does not confirm that any path is safe", r["notice"])
        self.assertEqual(len(prov.calls), 1)
        self.assertTrue(any("[vision]" in l and "ok" in l for l in logs))

    def test_question_is_passed_to_the_provider(self):
        a, prov, _, _ = make()
        r = a.describe(jpeg(), question="Is there a bus stop?\x00", consent=True)
        self.assertTrue(r["ok"])
        self.assertEqual(prov.calls[0]["question"], "Is there a bus stop?")
        self.assertIn('The user asks: "Is there a bus stop?"', prov.calls[0]["prompt"])
        self.assertTrue(r["text"].startswith("AI description: Regarding your question"))

    def test_handheld_positions_refer_to_the_camera_view(self):
        a, _, _, _ = make()
        r = a.describe(jpeg(), mode="handheld", consent=True)
        self.assertIn("on the left of the camera view", r["text"])

    def test_503_then_success_uses_exactly_one_retry(self):
        a, prov, _, _ = make(["503", "ok"])
        r = a.describe(jpeg(), consent=True)
        self.assertTrue(r["ok"])
        self.assertEqual(r["attempts"], 2)
        self.assertEqual(len(prov.calls), 2)

    def test_repeated_503_gives_clear_fallback_and_no_more_than_one_retry(self):
        a, prov, _, logs = make(["503"])
        r = a.describe(jpeg(), consent=True)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "unavailable")
        self.assertEqual(r["text"], "Online scene description is unavailable right now. Local walking guidance continues.")
        self.assertEqual(len(prov.calls), 2)
        self.assertIn("unavailable: 503", a.info()["last_error"])
        self.assertTrue(any("FAILED unavailable" in l for l in logs))

    def test_max_retries_zero_means_exactly_one_call(self):
        a, prov, _, _ = make(["503"], max_retries=0)
        self.assertFalse(a.describe(jpeg(), consent=True)["ok"])
        self.assertEqual(len(prov.calls), 1)

    def test_timeout_and_time_budget(self):
        a, prov, _, _ = make(["timeout"])
        r = a.describe(jpeg(), consent=True)
        self.assertEqual(r["code"], "timeout")
        self.assertIn("took too long", r["text"])
        # a timed-out request is never repeated, and it got the full per-attempt timeout (default 30 s)
        self.assertEqual([c["timeout_s"] for c in prov.calls], [30.0])
        # a provider that is slower than the per-try timeout (real sleep, small numbers)
        slow = SceneAssistant(MockProvider(latency_s=0.3), budget_s=1.2, per_try_timeout_s=0.1, max_retries=0,
                              log=lambda *_: None)
        self.assertEqual(slow.describe(jpeg(), consent=True)["code"], "timeout")

    def test_non_retryable_errors(self):
        for outcome, code in (("rejected", "rejected"), ("429", "provider_rate_limited"), ("bad", "bad_response")):
            with self.subTest(outcome):
                a, prov, _, _ = make([outcome])
                r = a.describe(jpeg(), consent=True)
                self.assertEqual(r["code"], code)
                self.assertEqual(len(prov.calls), 1)                     # never retried
                self.assertEqual(r["text"], TEXT[code])

    def test_circuit_breaker_opens_and_recovers(self):
        a, prov, clock, _ = make(["503", "503", "503", "503", "503", "503", "ok"], max_retries=1, breaker_threshold=3,
                                 breaker_cooldown_s=60, min_interval_s=0)
        for _ in range(3):
            self.assertEqual(a.describe(jpeg(), consent=True)["code"], "unavailable")
        self.assertEqual(a.info()["breaker"], "open")
        self.assertFalse(a.info()["available"])
        calls = len(prov.calls)
        r = a.describe(jpeg(), consent=True)
        self.assertEqual(r["code"], "paused")                            # no provider call while open
        self.assertEqual(len(prov.calls), calls)
        self.assertGreater(r["retry_after_s"], 0)
        clock.t += 61
        self.assertEqual(a.info()["breaker"], "half-open")
        r = a.describe(jpeg(), consent=True)                             # one trial request is allowed again
        self.assertTrue(r["ok"], r)
        self.assertEqual(a.info()["breaker"], "closed")

    def test_rate_limit_per_session_and_hourly_cap(self):
        a, prov, clock, _ = make(min_interval_s=5, hourly_cap=3)
        self.assertTrue(a.describe(jpeg(), session="s1", consent=True)["ok"])
        r = a.describe(jpeg(), session="s1", consent=True)
        self.assertEqual(r["code"], "rate_limited")
        self.assertEqual(r["text"], "Please wait a few seconds before asking again.")
        self.assertTrue(a.describe(jpeg(), session="s2", consent=True)["ok"])  # other session not blocked
        clock.t += 6
        self.assertTrue(a.describe(jpeg(), session="s1", consent=True)["ok"])
        clock.t += 6
        self.assertEqual(a.describe(jpeg(), session="s3", consent=True)["code"], "hourly_cap")
        self.assertEqual(len(prov.calls), 3)
        clock.t += 3600
        self.assertTrue(a.describe(jpeg(), session="s3", consent=True)["ok"])

    def test_consent_disabled_and_not_configured_never_call_the_provider(self):
        a, prov, _, _ = make()
        self.assertEqual(a.describe(jpeg(), consent=False)["code"], "consent")
        off = SceneAssistant(prov, enabled=False, log=lambda *_: None)
        self.assertEqual(off.describe(jpeg(), consent=True)["code"], "disabled")
        nc = SceneAssistant(MockProvider(configured=False), log=lambda *_: None)
        r = nc.describe(jpeg(), consent=True)
        self.assertEqual(r["code"], "not_configured")
        self.assertIn("not set up", r["text"])
        self.assertEqual(prov.calls, [])
        self.assertFalse(nc.info()["available"])

    def test_bad_images_are_rejected_before_any_provider_call(self):
        a, prov, _, _ = make(min_interval_s=0)
        for bad in (b"", b"not an image", jpeg(32, 32, None)):
            with self.assertRaises(ValueError):
                a.describe(bad, consent=True)
        self.assertEqual(prov.calls, [])

    def test_unusable_image_quality(self):
        a, _, _, _ = make(["dark"])
        r = a.describe(jpeg(), consent=True)
        self.assertTrue(r["ok"])
        self.assertIn("too dark or blurred", r["text"])

    def test_status_never_contains_the_key_and_no_image_is_kept(self):
        a, prov, _, _ = make()
        a.describe(jpeg(), consent=True)
        info = a.info()
        for k in ("requires_internet", "requires_consent", "stores_images"):
            self.assertIn(k, info)
        self.assertFalse(info["stores_images"])
        # the assistant keeps no image bytes anywhere in its state
        for v in vars(a).values():
            self.assertNotIsInstance(v, (bytes, bytearray))
        self.assertEqual(set(prov.calls[0]), {"question", "image_bytes", "prompt", "timeout_s"})


class TestSafetyFilter(unittest.TestCase):
    def test_unsafe_model_output_is_filtered(self):
        a, _, _, _ = make(["unsafe"])
        r = a.describe(jpeg(), question="Can I walk forward?", consent=True)
        self.assertTrue(r["ok"])
        t = r["text"].lower()
        for banned in ("safe", "no obstacles", "metres", "10", "steps ahead", "path ahead is clear"):
            self.assertNotIn(banned, t.replace("please check the path yourself", ""), r["text"])
        self.assertTrue(r["text"].endswith("Please check the path yourself."))
        self.assertGreater(r["filtered_sentences"], 0)
        self.assertTrue(is_spoken_text_safe(r["text"]))

    def test_filter_text_examples(self):
        cases = {
            "The road is busy. It is safe to cross.": "The road is busy.",
            "A pole is about 2 m ahead. A dog is on the left.": "A dog is on the left.",
            "The path looks clear. Watch the step.": "Watch the step.",
            "There are no obstacles.": "",
            "A few metres away there is a bin. Cars are parked.": "Cars are parked.",
            "An unsafe-looking hole on the right.": "An unsafe-looking hole on the right.",
        }
        for src, want in cases.items():
            with self.subTest(src):
                self.assertEqual(filter_text(src)[0], want)

    def test_spoken_length_limit(self):
        long = {"summary": "A very long description. " * 40, "objects": [{"name": "car", "position": "left"}] * 10,
                "hazards": ["Something risky on the right."] * 6, "uncertainty": "Unclear.", "image_quality": "good"}
        text, _, _ = compose_speech(parse_scene(__import__("json").dumps(long)))
        self.assertLessEqual(len(text), MAX_SPOKEN)
        self.assertTrue(text.endswith("."))


class TestParsingAndSecrets(unittest.TestCase):
    def test_parse_scene_variants(self):
        good = '```json\n{"summary": "A shop.", "objects": [{"name": "door", "position": "center"}], "hazards": [], "uncertainty": "", "image_quality": "excellent"}\n```'
        d = parse_scene(good)
        self.assertEqual(d["objects"][0]["position"], "centre")
        self.assertEqual(d["image_quality"], "good")
        self.assertEqual(parse_scene('Here you go: {"summary": "x", "objects": []} thanks')["summary"], "x")
        for bad in ("", "no json here", "[1, 2]", '{"objects": []}'):
            with self.subTest(bad), self.assertRaises(BadResponse):
                parse_scene(bad)

    def test_scrub_removes_keys(self):
        key = "AIza" + "Sy" + "X" * 33
        msg = f"400 API key not valid: {key} url=https://x/?key={key}&alt=json"
        out = scrub(msg, key)
        self.assertNotIn(key, out)
        self.assertNotIn("XXXXXXXXXX", out)
        self.assertIn("[REDACTED]", out)

    def test_prepare_image_downscales_in_memory(self):
        big = cv2.imencode(".jpg", np.full((1800, 2400, 3), 90, np.uint8))[1].tobytes()
        out, w, h = prepare_image(big)
        self.assertEqual((w, h), (1024, 768))
        self.assertEqual(out[:2], b"\xff\xd8")


class FakeModels:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "config": config, "n_parts": len(contents)})
        o = self.outcome
        if isinstance(o, BaseException):
            raise o
        if o == "hang":
            import time as _t
            _t.sleep(3)
        return o


class FakeClient:
    def __init__(self, outcome):
        self.models = FakeModels(outcome)


class FakeResp:
    def __init__(self, text, model_version="gemini-3.8-flash-001"):
        self.text, self.model_version, self.candidates, self.prompt_feedback = text, model_version, [], None


KEY = "AIza" + "Sy" + "F" * 33


class TestGeminiProviderOffline(unittest.TestCase):
    """GeminiProvider with an injected fake client: request building and error mapping, no network."""

    def provider(self, outcome):
        from neurosonic.vision.gemini import GeminiProvider
        holder = {}

        def factory(key):
            holder["key_ok"] = key == KEY
            holder["client"] = FakeClient(outcome)
            return holder["client"]
        return GeminiProvider(model="gemini-3.8-flash", api_key=KEY, client_factory=factory), holder

    def call(self, outcome, timeout=5.0, min_timeout=None):
        from neurosonic.vision.base import SceneRequest
        p, h = self.provider(outcome)
        if min_timeout is not None:
            p.min_timeout_s = min_timeout        # test only: the real floor is 10 s
        with no_internet() as attempts:
            try:
                return p.analyze(SceneRequest(image=jpeg()), "prompt", "system", timeout), h, None
            except Exception as e:  # noqa: BLE001
                return None, h, e
            finally:
                self.assertEqual(attempts, [])

    def test_success_and_request_configuration(self):
        import json
        reply, h, err = self.call(FakeResp(json.dumps({"summary": "A road.", "objects": [], "hazards": [],
                                                       "uncertainty": "", "image_quality": "good"})))
        self.assertIsNone(err)
        self.assertTrue(h["key_ok"])
        self.assertEqual(reply.scene["summary"], "A road.")
        self.assertEqual(reply.model, "gemini-3.8-flash-001")
        call = h["client"].models.calls[0]
        self.assertEqual(call["model"], "gemini-3.8-flash")
        cfg = call["config"]
        self.assertEqual(cfg.response_mime_type, "application/json")
        self.assertEqual(cfg.http_options.timeout, 10000)                # 5 s requested -> 10 s server minimum
        self.assertEqual(cfg.http_options.retry_options.attempts, 1)      # SDK retries off: 1 call = 1 request
        self.assertEqual(len(h["client"].models.calls), 1)

    def test_error_mapping_and_key_scrubbing(self):
        from google.genai import errors
        from neurosonic.vision.base import (ProviderRateLimited, ProviderTimeout, ProviderUnavailable, Rejected,
                                            VisionError)
        cases = [
            (errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "The model is overloaded."}}), ProviderUnavailable),
            (errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota"}}), ProviderRateLimited),
            (errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": f"API key not valid {KEY}"}}), Rejected),
            (errors.ClientError(404, {"error": {"code": 404, "status": "NOT_FOUND", "message": "models/gemini-x is not found"}}), Rejected),
            (TimeoutError("read timed out"), ProviderTimeout),
            (ConnectionError("getaddrinfo failed"), ProviderUnavailable),
            (RuntimeError("weird"), VisionError),
        ]
        for exc, want in cases:
            with self.subTest(type(exc).__name__):
                _, _, err = self.call(exc)
                self.assertIsInstance(err, want)
                self.assertNotIn(KEY, str(err))

    def test_empty_reply_and_hard_timeout(self):
        from neurosonic.vision.base import BadResponse, ProviderTimeout
        _, _, err = self.call(FakeResp(None))
        self.assertIsInstance(err, BadResponse)
        _, _, err = self.call("hang", timeout=0.2, min_timeout=0.2)   # guard fires after timeout + 2 s, before the 3 s hang
        self.assertIsInstance(err, ProviderTimeout)

    def test_missing_key_is_reported_without_a_call(self):
        from neurosonic.vision.gemini import GeminiProvider
        p = GeminiProvider(api_key="")
        self.assertFalse(p.configured())
        self.assertIn("GEMINI_API_KEY", p.problem())
        a = SceneAssistant(p, log=lambda *_: None)
        self.assertEqual(a.describe(jpeg(), consent=True)["code"], "not_configured")
        self.assertNotIn("key", str(a.info().get("model")))


class TestVisionEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shutil, tempfile  # noqa: E401
        from pathlib import Path
        from neurosonic.server import make_server, serve_in_thread
        from neurosonic.store import Store
        cls.td = Path(tempfile.mkdtemp(prefix="ns_vision_"))
        cls._rm = shutil.rmtree
        cls.store = Store(cls.td / "t.sqlite3")
        cls.prov = MockProvider(script=["ok"])
        cls.vision = SceneAssistant(cls.prov, min_interval_s=0, log=lambda *_: None)

        from neurosonic.service import EventLog

        class Svc:
            events = EventLog(cls.store)          # the real event log -> SQLite history
        cls.httpd = make_server(Svc(), cls.store, "127.0.0.1", 0, vision=cls.vision)
        serve_in_thread(cls.httpd)
        cls.port = cls.httpd.server_address[1]
        cls.nov = make_server(Svc(), cls.store, "127.0.0.1", 0)            # server without vision
        serve_in_thread(cls.nov)

    @classmethod
    def tearDownClass(cls):
        for h in (cls.httpd, cls.nov):
            h.shutdown()
            h.server_close()
        cls.store.close()
        cls._rm(cls.td, ignore_errors=True)

    def req(self, method, path, body=None, ctype="image/jpeg", port=None):
        import http.client, json  # noqa: E401
        c = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=30)
        c.request(method, path, body=body, headers={"Content-Type": ctype} if body is not None else {})
        r = c.getresponse()
        out = r.status, json.loads(r.read() or b"null")
        c.close()
        return out

    def test_status_has_no_secrets(self):
        st, s = self.req("GET", "/api/vision/status")
        self.assertEqual(st, 200)
        self.assertTrue(s["available"])
        self.assertEqual((s["requires_internet"], s["requires_consent"], s["stores_images"]), (True, True, False))
        self.assertNotIn("key", " ".join(k.lower() for k in s))
        st, s = self.req("GET", "/api/vision/status", port=self.nov.server_address[1])
        self.assertEqual((st, s["available"]), (200, False))

    def test_describe_requires_consent_then_works(self):
        from urllib.parse import quote
        calls = len(self.prov.calls)
        st, r = self.req("POST", "/api/vision/describe?session=a", jpeg())
        self.assertEqual((st, r["ok"], r["code"]), (200, False, "consent"))
        self.assertEqual(len(self.prov.calls), calls)                     # nothing sent without consent
        st, r = self.req("POST", "/api/vision/describe?session=a&consent=1&mode=chest&q=" + quote("What is on the left?"), jpeg())
        self.assertEqual(st, 200)
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["text"].startswith("AI description:"))
        self.assertEqual(self.prov.calls[-1]["question"], "What is on the left?")
        hist = self.store.history(20)
        scene = [h for h in hist if h["kind"] == "scene"]
        self.assertTrue(scene and scene[0]["source"] == "vision")
        # history keeps text and metadata only - no image bytes or base64
        import json
        dump = json.dumps(hist)
        self.assertNotIn("/9j/", dump)                                    # JPEG base64 prefix
        self.assertLess(len(dump), 20000)

    def test_bad_requests(self):
        self.assertEqual(self.req("POST", "/api/vision/describe?consent=1", b"xx")[0], 400)
        self.assertEqual(self.req("POST", "/api/vision/describe?consent=1", jpeg(), ctype="text/plain")[0], 415)
        self.assertEqual(self.req("POST", "/api/vision/describe?consent=1", b"", ctype="image/jpeg")[0], 400)
        self.assertEqual(self.req("POST", "/api/vision/describe?consent=1", jpeg(),
                                  port=self.nov.server_address[1])[0], 503)

    def test_error_responses_arrive_even_with_unread_bodies(self):
        # regression (2026-11-02): rejecting a request before reading its body (415 / 503) made Windows reset the
        # connection, so clients sometimes got "connection aborted" instead of the error response
        big = jpeg(1600, 1200) + b"\0" * 200_000
        nov = self.nov.server_address[1]
        for _ in range(10):
            self.assertEqual(self.req("POST", "/api/vision/describe?consent=1", big, port=nov)[0], 503)
            self.assertEqual(self.req("POST", "/api/awareness/frame", big, port=nov)[0], 503)   # existing endpoint
            self.assertEqual(self.req("POST", "/api/vision/describe?consent=1", big, ctype="text/plain")[0], 415)

    def test_provider_failure_is_a_spoken_fallback(self):
        prov = self.vision.provider
        self.vision.provider = MockProvider(script=["503"])
        try:
            st, r = self.req("POST", "/api/vision/describe?session=f&consent=1", jpeg())
        finally:
            self.vision.provider = prov
        self.assertEqual((st, r["ok"], r["code"]), (200, False, "unavailable"))
        self.assertIn("Local walking guidance continues", r["text"])


class DeadlineProvider:
    """Behaves like the Gemini service as seen on 2026-11-02, on a fake clock: records the timeout and the
    X-Server-Timeout header the real SDK would send, rejects deadlines below 10 s (400), and fails with
    504 DEADLINE_EXCEEDED when the reply would take longer than the deadline."""
    name, model, min_timeout_s = "gemini", "gemini-3.8-flash", 10.0

    def __init__(self, clock, outcomes):
        self.clock, self.outcomes, self.calls = clock, list(outcomes), []

    def configured(self):
        return True

    def problem(self):
        return ""

    def analyze(self, req, prompt, system, timeout_s):
        from google.genai._api_client import populate_server_timeout_header
        from neurosonic.vision.base import ProviderReply, ProviderTimeout, Rejected
        h = {}
        populate_server_timeout_header(h, timeout_s)          # the real SDK function, no network
        deadline = int(h["X-Server-Timeout"])
        self.calls.append({"timeout_s": timeout_s, "deadline": deadline, "at": self.clock.t})
        if deadline < 10:
            raise Rejected(f"400 INVALID_ARGUMENT. Manually set deadline {deadline}s is too short.")
        secs, err = self.outcomes.pop(0)
        self.clock.t += min(secs, timeout_s)
        if secs >= timeout_s:
            raise ProviderTimeout("504 DEADLINE_EXCEEDED. Deadline expired before operation could complete.")
        if err is not None:
            raise err
        return ProviderReply(scene=parse_scene('{"summary": "A road.", "objects": [], "hazards": [], '
                                               '"uncertainty": "", "image_quality": "good"}'), model=self.model)


class TestTimeoutPolicy(unittest.TestCase):
    """The 2026-11-02 deadline fix: full attempts only, never below 10 s, no retry after a timeout."""

    def run_case(self, outcomes, **kw):
        clock = FakeClock()
        clock.t = 0.0
        prov = DeadlineProvider(clock, outcomes)
        a = SceneAssistant(prov, clock=clock, sleep=clock.sleep, log=lambda *_: None, **kw)
        with no_internet() as attempts:
            r = a.describe(jpeg(), consent=True)
        self.assertEqual(attempts, [])
        return r, prov, a

    def test_defaults(self):
        a = SceneAssistant(MockProvider(), log=lambda *_: None)
        self.assertEqual((a.per_try_timeout_s, a.budget_s, a.max_retries), (30.0, 45.0, 1))
        info = a.info()
        self.assertEqual((info["attempt_timeout_s"], info["budget_s"], info["max_retries"]), (30.0, 45.0, 1))

    def test_slow_model_times_out_once_and_is_not_retried(self):
        r, prov, _ = self.run_case([(60, None), (60, None)])
        self.assertEqual(r["code"], "timeout")
        self.assertEqual([c["deadline"] for c in prov.calls], [30])           # one attempt, full 30 s deadline

    def test_reproduced_4s_deadline_cannot_happen_any_more(self):
        # before the fix: 503 after ~10 s, then a retry with the 3.x s left of the 15 s budget -> "deadline 4s"
        from neurosonic.vision.base import ProviderUnavailable
        for first_failure_s in (9.5, 10.3, 14.0, 20.0):
            with self.subTest(first_failure_s):
                r, prov, _ = self.run_case([(first_failure_s, ProviderUnavailable("503 UNAVAILABLE")), (5, None)])
                self.assertTrue(all(c["deadline"] >= 10 for c in prov.calls), prov.calls)
                self.assertTrue(all(c["timeout_s"] == 30.0 for c in prov.calls), prov.calls)   # never shrunk
                self.assertNotEqual(r["code"], "rejected")
                if first_failure_s + 1.6 <= 15.0:          # a full 30 s attempt surely still fits into 45 s
                    self.assertEqual(len(prov.calls), 2)
                    self.assertTrue(r["ok"])
                elif first_failure_s + 0.8 > 15.0:         # it surely does not fit: no retry at all
                    self.assertEqual(len(prov.calls), 1)
                    self.assertEqual(r["code"], "unavailable")

    def test_quick_503_gets_exactly_one_full_retry(self):
        from neurosonic.vision.base import ProviderUnavailable
        r, prov, _ = self.run_case([(0.5, ProviderUnavailable("503 UNAVAILABLE")), (8, None)])
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["attempts"], 2)
        self.assertEqual([c["deadline"] for c in prov.calls], [30, 30])
        # two quick 503s: still only one retry (max_retries unchanged)
        r, prov, _ = self.run_case([(0.5, ProviderUnavailable("503")), (0.5, ProviderUnavailable("503")), (1, None)])
        self.assertEqual((r["code"], len(prov.calls)), ("unavailable", 2))

    def test_network_error_is_retried_like_503_but_504_is_not(self):
        from neurosonic.vision.base import ProviderTimeout, ProviderUnavailable
        r, prov, _ = self.run_case([(0.2, ProviderUnavailable("network error, is the laptop online?")), (3, None)])
        self.assertTrue(r["ok"])
        self.assertEqual(len(prov.calls), 2)
        r, prov, _ = self.run_case([(2, ProviderTimeout("504 DEADLINE_EXCEEDED")), (3, None)])
        self.assertEqual((r["code"], len(prov.calls)), ("timeout", 1))

    def test_environment_configuration(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"NEUROSONIC_VISION_TIMEOUT_S": "20", "NEUROSONIC_VISION_BUDGET_S": "50"}):
            a = SceneAssistant(MockProvider(), log=lambda *_: None)
            self.assertEqual((a.per_try_timeout_s, a.budget_s), (20.0, 50.0))
        logs = []
        with mock.patch.dict(os.environ, {"NEUROSONIC_VISION_TIMEOUT_S": "abc", "NEUROSONIC_VISION_BUDGET_S": "-3"}):
            a = SceneAssistant(MockProvider(), log=logs.append)
            self.assertEqual((a.per_try_timeout_s, a.budget_s), (30.0, 45.0))     # invalid values -> defaults
            self.assertEqual(len(logs), 2)
        with mock.patch.dict(os.environ, {"NEUROSONIC_VISION_TIMEOUT_S": "5", "NEUROSONIC_VISION_BUDGET_S": "8"}):
            a = SceneAssistant(DeadlineProvider(FakeClock(), []), log=lambda *_: None)
            self.assertEqual((a.per_try_timeout_s, a.budget_s), (10.0, 10.0))     # Gemini minimum; budget >= attempt
        with mock.patch.dict(os.environ, {"NEUROSONIC_VISION_TIMEOUT_S": "20"}):      # explicit arguments win
            self.assertEqual(SceneAssistant(MockProvider(), per_try_timeout_s=12, log=lambda *_: None).per_try_timeout_s, 12.0)

    def test_circuit_breaker_still_counts_timeouts_and_rate_limits_unchanged(self):
        clock = FakeClock()
        prov = DeadlineProvider(clock, [(60, None)] * 4)
        a = SceneAssistant(prov, clock=clock, sleep=clock.sleep, log=lambda *_: None, min_interval_s=0)
        for _ in range(3):
            self.assertEqual(a.describe(jpeg(), consent=True)["code"], "timeout")
        self.assertEqual(a.describe(jpeg(), consent=True)["code"], "paused")
        self.assertEqual(len(prov.calls), 3)
        b = SceneAssistant(MockProvider(), log=lambda *_: None)
        self.assertEqual((b.min_interval_s, b.hourly_cap, b.breaker_threshold, b.breaker_cooldown_s), (5.0, 60, 3, 60.0))

    def test_gemini_provider_never_sends_a_deadline_below_10s(self):
        import json
        from google.genai._api_client import populate_server_timeout_header
        from neurosonic.vision.base import SceneRequest
        from neurosonic.vision.gemini import GeminiProvider, MIN_DEADLINE_S
        self.assertEqual(MIN_DEADLINE_S, 10.0)
        reply = FakeResp(json.dumps({"summary": "x", "objects": [], "hazards": [], "uncertainty": "", "image_quality": "good"}))
        for requested, want_ms in ((3.59, 10000), (9.99, 10000), (10, 10000), (30, 30000)):
            with self.subTest(requested):
                holder = {}
                p = GeminiProvider(api_key=KEY, client_factory=lambda k: holder.setdefault("c", FakeClient(reply)))
                with no_internet():
                    p.analyze(SceneRequest(image=jpeg()), "p", "s", requested)
                cfg = holder["c"].models.calls[0]["config"]
                self.assertEqual(cfg.http_options.timeout, want_ms)
                self.assertEqual(cfg.http_options.retry_options.attempts, 1)      # the SDK itself never retries
                h = {}
                populate_server_timeout_header(h, cfg.http_options.timeout / 1000)
                self.assertGreaterEqual(int(h["X-Server-Timeout"]), 10)

    def test_phone_waits_longer_than_the_backend(self):
        import re
        from neurosonic.vision.assistant import DEFAULT_BUDGET_S
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        req = int(re.search(r"SCENE_REQUEST_TIMEOUT_MS = (\d+)", js).group(1))
        wait = int(re.search(r"SCENE_STILL_WAITING_MS = (\d+)", js).group(1))
        self.assertEqual((req, wait), (60000, 15000))
        self.assertGreater(req, DEFAULT_BUDGET_S * 1000 + 5000)               # backend answers before the phone gives up
        self.assertIn("setTimeout(() => ctl.abort(), SCENE_REQUEST_TIMEOUT_MS)", js)
        self.assertIn("Still waiting for the online description. Local walking guidance continues.", js)


class TestSceneVoiceIntents(unittest.TestCase):
    def test_describe_and_ask_intents_do_not_break_existing_commands(self):
        from neurosonic.voicecmd import parse_intent
        cases = [
            (("describe surroundings", "describe surroundings"), ("describe_scene", None)),
            (("what is around me", "what is around me"), ("describe_scene", None)),
            (("what is in front of me", "what is in front of me"), ("describe_scene", None)),
            (("[unk]", "is there a bus stop on the left"), ("ask_scene", "is there a bus stop on the left")),
            (("[unk]", "can you see a door"), ("ask_scene", "can you see a door")),
            # existing commands keep priority
            (("where am i", "where am i"), ("status", None)),
            (("start camera", "start camera"), ("awareness_on", None)),
            (("stop navigation", "stop navigation"), ("stop_navigation", None)),
            (("navigate to", "navigate to cmc hospital"), ("navigate", "cmc hospital")),
            (("help", "help"), ("help", None)),
        ]
        for (g, f), want in cases:
            with self.subTest(f):
                self.assertEqual(parse_intent(g, f), want)


class TestLocalGuidanceIndependence(unittest.TestCase):
    def test_local_modules_do_not_import_the_cloud_package(self):
        import ast
        for mod in ("awareness.py", "pathguide.py", "tts.py", "maps.py", "voicecmd.py", "store.py"):
            tree = ast.parse((ROOT / "neurosonic" / mod).read_text(encoding="utf-8"))
            names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
                    [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            self.assertFalse([n for n in names if n.split(".")[-1] == "vision" or n.startswith(("neurosonic.vision", "google"))],
                             f"{mod} must not depend on cloud vision")


if __name__ == "__main__":
    unittest.main()
