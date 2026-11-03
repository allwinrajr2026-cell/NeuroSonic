"""RF-DETR integration (2026-11-03): detector fallback, ByteTrack-style tracking with camera-motion compensation,
conservative entering / crossing events, and the end-to-end frame pipeline. RF-DETR tests run only where CUDA, the
rfdetr package and the local weights exist (the .venv-gpu environment); everything else runs everywhere.
Synthetic motion tests check the logic only; they are not evidence of real-world reliability."""
import http.client
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from tests._common import ROOT
from tests._offline import no_internet
from neurosonic.awareness import OBSTACLE_CLASSES, RGBAwareness
from neurosonic.detectors import (DetectorUnavailable, FallbackDetector, SSDLiteDetector, find_rfdetr_weights,
                                  make_detector)
from neurosonic.events import PathEventDetector
from neurosonic.pathguide import BLOCKED_VIEW, CLEAR_VIEW, POSSIBLE_OBSTACLE
from neurosonic.tracking import ByteTracker, CameraMotion, estimate_camera_motion

DEMO = ROOT / "demo_data" / "detec_test" / "ir"
W, H = 320, 240


def rfdetr_ready():
    try:
        import torch
        import rfdetr  # noqa: F401
        return torch.cuda.is_available() and find_rfdetr_weights() is not None
    except Exception:  # noqa: BLE001
        return False


def det(x1, y1, x2, y2, cls="Person", conf=0.9):
    return {"class_id": 1, "class_name": cls, "confidence": conf, "box_xyxy": [x1, y1, x2, y2]}


def textured(seed=0):
    rng = np.random.default_rng(seed)
    img = (rng.integers(0, 255, (H // 8, W // 8, 3), dtype=np.uint8))
    return cv2.resize(img, (W, H), interpolation=cv2.INTER_NEAREST)


# ----------------------------------------------------------------------------- detectors and fallback
class TestDetectorFallback(unittest.TestCase):
    def test_ssdlite_default_and_explicit(self):
        d, info = make_detector(OBSTACLE_CLASSES, "ssdlite", log=lambda *_: None)
        self.assertEqual((d.name, d.device, info["fallback_reason"]), ("ssdlite320", "cpu", None))

    def test_auto_falls_back_when_rfdetr_cannot_start(self):
        import neurosonic.detectors as D
        orig = D.RFDETRDetector
        logs = []

        class Broken:
            def __init__(self, *a, **k):
                raise DetectorUnavailable("CUDA not available (simulated)")
        D.RFDETRDetector = Broken
        try:
            d, info = make_detector(OBSTACLE_CLASSES, "auto", log=logs.append)
        finally:
            D.RFDETRDetector = orig
        self.assertEqual(d.name, "ssdlite320")
        self.assertIn("CUDA not available (simulated)", info["fallback_reason"])
        self.assertTrue(logs and "using SSDLite" in logs[0])

    def test_auto_falls_back_when_warm_up_inference_fails(self):
        import neurosonic.detectors as D
        orig = D.RFDETRDetector

        class FailsOnInference:
            name, device, input_size = "rf-detr-nano", "cuda", 384

            def __init__(self, *a, **k):
                self.weights = "x"

            def detect(self, bgr):
                raise RuntimeError("CUDA error: out of memory (simulated)")
        D.RFDETRDetector = FailsOnInference
        try:
            d, info = make_detector(OBSTACLE_CLASSES, "auto", log=lambda *_: None)
        finally:
            D.RFDETRDetector = orig
        self.assertEqual(d.name, "ssdlite320")
        self.assertIn("out of memory", info["fallback_reason"])

    def test_runtime_failure_switches_to_ssdlite_and_reruns_the_frame(self):
        class Flaky:
            name, device, input_size = "rf-detr-nano", "cuda", 384
            calls = 0

            def detect(self, bgr):
                Flaky.calls += 1
                if Flaky.calls > 1:
                    raise RuntimeError("CUDA error: device lost (simulated)")
                return [det(1, 1, 50, 50)]
        logs = []
        fd = FallbackDetector(Flaky(), lambda: SSDLiteDetector(OBSTACLE_CLASSES), log=logs.append)
        frame = cv2.imread(str(DEMO / "0000060683.png"))
        self.assertEqual(len(fd.detect(frame)), 1)
        dets = fd.detect(frame)                                    # fails -> SSDLite answers the same frame
        self.assertEqual(fd.name, "ssdlite320")
        self.assertIn("Person", [d["class_name"] for d in dets])
        self.assertIn("device lost", fd.fallback_reason)
        self.assertTrue(any("switching to SSDLite" in l for l in logs))

    def test_awareness_reports_detector_and_frame_interval(self):
        a = RGBAwareness(detector="ssdlite", log=lambda *_: None)
        a.warm_up()
        i = a.info()
        self.assertEqual((i["detector"]["name"], i["detector"]["device"], i["recommended_frame_ms"]), ("ssdlite320", "cpu", 400))
        self.assertEqual(i["coco_box_map"], 21.3)

    def test_unknown_detector_name_is_rejected(self):
        with self.assertRaises(ValueError):
            make_detector(OBSTACLE_CLASSES, "yolo", log=lambda *_: None)


@unittest.skipUnless(rfdetr_ready(), "RF-DETR needs CUDA, the rfdetr package and local weights (.venv-gpu)")
class TestRFDETROnGPU(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = RGBAwareness(detector="auto", log=lambda *_: None)
        cls.a.warm_up()

    def test_runs_on_gpu_and_detects_people(self):
        i = self.a.info()
        self.assertEqual((i["detector"]["name"], i["detector"]["device"], i["recommended_frame_ms"]), ("rf-detr-nano", "cuda", 200))
        self.assertIsNone(i["detector"]["fallback_reason"])
        frame = cv2.resize(cv2.imread(str(DEMO / "0000060683.png")), (320, 240))   # the phone sends 320 px frames
        with no_internet() as attempts:
            dets = self.a.detect(frame)
        self.assertEqual(attempts, [])                                              # no download at run time
        self.assertIn("Person", [d["class_name"] for d in dets])
        self.assertTrue(all(d["class_id"] in OBSTACLE_CLASSES for d in dets))

    def test_process_frame_uses_rfdetr(self):
        j = cv2.imencode(".jpg", cv2.resize(cv2.imread(str(DEMO / "0000060683.png")), (320, 240)))[1].tobytes()
        r = None
        for k in range(3):
            r = self.a.process_frame(j, session="gpu", t=k * 0.2)
        self.assertEqual(r["detector"], {"name": "rf-detr-nano", "device": "cuda"})
        self.assertLess(r["timing"]["total_ms"], 500)
        self.assertTrue(r["tracks"])


# ----------------------------------------------------------------------------- camera motion
class TestCameraMotion(unittest.TestCase):
    def test_recovers_a_known_shift_and_zoom(self):
        g = cv2.cvtColor(cv2.resize(cv2.imread(str(DEMO / "0000030226.png")), (W, H)), cv2.COLOR_BGR2GRAY)
        A = np.float32([[1, 0, 6], [0, 1, -3]])
        moved = cv2.warpAffine(g, A, (W, H), borderMode=cv2.BORDER_REFLECT)
        cam = estimate_camera_motion(g, moved)
        self.assertTrue(cam.ok)
        self.assertAlmostEqual(cam.A[0, 2], 6, delta=1.0)
        self.assertAlmostEqual(cam.A[1, 2], -3, delta=1.0)
        Z = cv2.getRotationMatrix2D((W / 2, H / 2), 0, 1.05)
        cam = estimate_camera_motion(g, cv2.warpAffine(g, Z, (W, H), borderMode=cv2.BORDER_REFLECT))
        self.assertAlmostEqual(cam.scale, 1.05, delta=0.01)

    def test_featureless_image_gives_no_estimate(self):
        flat = np.full((H, W), 128, np.uint8)
        self.assertFalse(estimate_camera_motion(flat, flat).ok)
        self.assertFalse(estimate_camera_motion(None, flat).ok)


# ----------------------------------------------------------------------------- tracking
class TestTracking(unittest.TestCase):
    def test_ids_are_stable_and_motion_is_relative_to_the_background(self):
        tr = ByteTracker()
        pan = CameraMotion(ok=True, A=np.float32([[1, 0, 10], [0, 1, 0]]), shift=10 / W)
        tracks = tr.update([det(100, 60, 140, 200), det(200, 60, 240, 200, "Car")], 0.0, W, H)
        ids = {t.class_name: t.id for t in tracks}
        for k in range(1, 5):              # camera pans: both static objects slide 10 px/frame in the image
            tracks = tr.update([det(100 + 10 * k, 60, 140 + 10 * k, 200), det(200 + 10 * k, 60, 240 + 10 * k, 200, "Car")],
                               0.2 * k, W, H, pan)
        self.assertEqual({t.class_name: t.id for t in tracks}, ids)
        for t in tracks:
            self.assertTrue(all(abs(h[5]) < 1e-6 for h in list(t.history)[1:]), t.history)   # no relative motion

    def test_low_confidence_detections_only_extend_tracks(self):
        tr = ByteTracker()
        self.assertEqual(tr.update([det(10, 10, 50, 50, conf=0.45)], 0, W, H), [])      # too weak to start a track
        tr.update([det(10, 10, 50, 50, conf=0.9)], 0.2, W, H)
        tracks = tr.update([det(12, 10, 52, 50, conf=0.45)], 0.4, W, H)                # weak but extends it
        self.assertEqual((len(tracks), tracks[0].hits), (1, 2))

    def test_tracks_expire_after_misses(self):
        tr = ByteTracker(max_misses=2)
        tr.update([det(10, 10, 50, 50)], 0, W, H)
        for k in range(3):
            tr.update([], 0.2 * (k + 1), W, H)
        self.assertEqual(tr.tracks, [])


# ----------------------------------------------------------------------------- events
STILL = CameraMotion(ok=True, A=np.float32([[1, 0, 0], [0, 1, 0]]), shift=0.0, scale=1.0)


def run_events(boxes_per_frame, cam=STILL, state=CLEAR_VIEW, mode="chest", dt=0.2, cls="Person"):
    tr, ev, said = ByteTracker(), PathEventDetector(mode), []
    for k, b in enumerate(boxes_per_frame):
        tracks = tr.update([det(*b, cls=cls)] if b else [], k * dt, W, H, cam)
        said += ev.update(tracks, k * dt, W, H, cam, state)
    return said


def walk(x_from, x_to, steps, y1=100, y2=235, w=40):
    return [(x_from + (x_to - x_from) * k / (steps - 1), y1, x_from + (x_to - x_from) * k / (steps - 1) + w, y2)
            for k in range(steps)]


class TestEvents(unittest.TestCase):
    def test_person_entering_from_the_left(self):
        said = run_events(walk(5, 140, 8))                       # ~0.53 image widths/s towards the centre
        self.assertEqual([e["type"] for e in said], ["entering"])
        self.assertEqual(said[0]["side"], "left")
        self.assertEqual(said[0]["text"], "Caution. A person is moving into your path from the left.")

    def test_crossing_left_to_right_and_right_to_left(self):
        # further ahead (higher in the image, outside the near walking-path region): "crossing", not "entering";
        # an object that passes through the near path region is announced as "entering" instead (precedence)
        said = run_events(walk(10, 270, 12, y1=30, y2=124), cls="Bicycle")
        self.assertEqual([e["type"] for e in said], ["crossing"])
        self.assertEqual(said[0]["text"], "A bicycle is crossing in front of you, from left to right.")
        said = run_events(walk(270, 10, 12, y1=30, y2=124), mode="handheld", cls="Motorcycle")
        self.assertEqual(said[0]["text"], "A motorcycle is crossing the camera view, from right to left.")

    def test_static_object_seen_while_the_camera_pans_gives_no_event(self):
        # the user turns: a parked car slides from the left into the path region, but it does not move itself
        pan = CameraMotion(ok=True, A=np.float32([[1, 0, 19], [0, 1, 0]]), shift=19 / W, scale=1.0)
        self.assertEqual(run_events(walk(5, 140, 8), cam=pan, cls="Car"), [])

    def test_shaky_or_unknown_camera_motion_suppresses_events(self):
        shaky = CameraMotion(ok=True, A=np.float32([[1, 0, 0], [0, 1, 0]]), shift=0.2, scale=1.0)
        self.assertEqual(run_events(walk(5, 140, 8), cam=shaky), [])
        self.assertEqual(run_events(walk(5, 140, 8), cam=CameraMotion(ok=False)), [])

    def test_no_events_while_blocked_or_uncertain_and_slow_movers_are_ignored(self):
        self.assertEqual(run_events(walk(5, 140, 8), state=BLOCKED_VIEW), [])
        self.assertEqual(run_events(walk(5, 30, 8)), [])                       # too slow: drifting, not entering
        self.assertEqual(run_events(walk(5, 140, 8), cls="Chair"), [])         # chairs do not move by themselves

    def test_each_event_once_per_track_and_global_gap(self):
        said = run_events(walk(5, 140, 8) + walk(140, 140, 10))
        self.assertEqual(len(said), 1)

    def test_texts_have_no_distance_or_safety_claims(self):
        for mode in ("chest", "handheld"):
            for e in run_events(walk(5, 140, 8), mode=mode) + run_events(walk(10, 270, 12, y1=30, y2=124), mode=mode):
                low = e["text"].lower()
                for word in ("metre", "meter", "safe", "clear", "approach", "seconds"):
                    self.assertNotIn(word, low)


# ----------------------------------------------------------------------------- end to end (stub detector)
class StubDetector:
    name, device, input_size, fallback_reason = "stub", "cpu", 320, None

    def __init__(self, boxes):
        self.boxes, self.k = boxes, 0

    def detect(self, bgr):
        b = self.boxes[min(self.k, len(self.boxes) - 1)]
        self.k += 1
        return [det(*b)] if b else []


class TestEndToEnd(unittest.TestCase):
    def test_event_reaches_the_frame_response_and_history(self):
        from neurosonic.server import make_server, serve_in_thread
        from neurosonic.service import EventLog
        from neurosonic.store import Store
        td = Path(tempfile.mkdtemp(prefix="ns_events_"))
        store = Store(td / "t.sqlite3")
        a = RGBAwareness(detector="ssdlite", log=lambda *_: None)
        a._model = StubDetector(walk(5, 140, 8))               # a person walking in from the left; camera still

        class Svc:
            events = EventLog(store)
        httpd = make_server(Svc(), store, "127.0.0.1", 0, awareness=a)
        serve_in_thread(httpd)
        try:
            frame = cv2.imencode(".jpg", textured())[1].tobytes()
            kinds, texts = [], []
            import time
            for _ in range(8):
                time.sleep(0.2)                                  # the app's GPU frame interval (real timestamps)
                c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=30)
                c.request("POST", "/api/awareness/frame?session=e2e&mode=chest", frame, {"Content-Type": "image/jpeg"})
                r = json.loads(c.getresponse().read())
                c.close()
                self.assertTrue(r["camera_motion"]["ok"] or r["tracks"] is not None)
                kinds += [e["kind"] for e in r["events"]]
                texts += [e["text"] for e in r["events"]]
            self.assertIn("Caution. A person is moving into your path from the left.", texts)
            self.assertIn("event", [h["kind"] for h in store.history(50)])     # spoken text in history, no image
            self.assertIn("timing", r)
            self.assertEqual(r["detector"]["name"], "stub")
        finally:
            httpd.shutdown()
            httpd.server_close()
            store.close()
            shutil.rmtree(td, ignore_errors=True)

    def test_frontend_uses_server_frame_interval_and_speaks_events(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("aInfo.recommended_frame_ms", js)
        self.assertIn('e.kind === "event"', js)
        self.assertIn("aLatency.push", js)


if __name__ == "__main__":
    unittest.main()
