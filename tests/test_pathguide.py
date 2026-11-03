"""Walking Guidance: path states, side vs central objects, temporal confirmation, announcement policy,
Object Description on/off. Synthetic boxes test the logic; real demo frames test the integration.
None of this is evidence of real-world safety (see docs/FEATURE_STATUS.md)."""
import http.client
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from tests._common import ROOT
from neurosonic.pathguide import (BLOCKED_VIEW, CAMERA_UNAVAILABLE, CLEAR_VIEW, MESSAGES, POSSIBLE_OBSTACLE,
                                  UNCERTAIN, FrameAssessment, PathGuide, assess_frame, box_path_overlap)

W, H = 640, 480
DETEC = ROOT / "demo_data" / "detec_test" / "ir"
HAVE_RGB = (ROOT / "models" / "rgb" / "ssdlite320_mobilenet_v3_large_coco-a79551df.pth").exists()


def det(x1, y1, x2, y2, cls="Person", conf=0.8):
    return {"class_name": cls, "confidence": conf, "box_xyxy": [x1, y1, x2, y2]}


def fa(dets, status="ok", brightness=130.0, sharp=500.0):
    return assess_frame(dets, W, H, status, brightness, sharp)


CENTRE_BIG = det(200, 180, 440, 480)        # fills the lower centre
CENTRE_SMALL = det(300, 250, 340, 330)      # small, inside the path region
LEFT_EDGE = det(0, 100, 90, 300)            # far left, outside the path region
RIGHT_CLOSE = det(420, 0, 640, 480)         # large, mostly beside the path (right edge)


class TestFrameAssessment(unittest.TestCase):
    def test_overlap_geometry(self):
        cover, inpath = box_path_overlap([0, 0, W, H], W, H)
        self.assertAlmostEqual(cover, 1.0, places=2)
        self.assertEqual(box_path_overlap([0, 0, 60, 120], W, H), (0.0, 0.0))   # top-left corner: no overlap

    def test_states_per_frame(self):
        self.assertEqual(fa([CENTRE_BIG]).level, BLOCKED_VIEW)
        self.assertEqual(fa([CENTRE_SMALL]).level, POSSIBLE_OBSTACLE)
        self.assertEqual(fa([]).level, CLEAR_VIEW)
        self.assertEqual(fa([], status="unusable").level, UNCERTAIN)
        self.assertEqual(fa([], sharp=5.0).level, UNCERTAIN)                  # blurred / featureless
        self.assertEqual(fa([], status="warn", brightness=35.0).level, UNCERTAIN)   # too dark to claim clear

    def test_side_object_versus_central_object(self):
        side = fa([LEFT_EDGE])
        self.assertEqual(side.level, CLEAR_VIEW)                 # a person at the side does not obstruct the path
        self.assertEqual([o["side"] for o in side.at_side], ["left"])
        self.assertEqual(side.in_path, [])
        close_right = fa([RIGHT_CLOSE])
        self.assertEqual(close_right.level, POSSIBLE_OBSTACLE)   # large but mostly beside the path: caution, not stop
        self.assertEqual(fa([CENTRE_BIG, LEFT_EDGE]).level, BLOCKED_VIEW)

    def test_low_confidence_ignored(self):
        self.assertEqual(fa([dict(CENTRE_BIG, confidence=0.3)]).level, CLEAR_VIEW)

    def test_obstacles_still_reported_in_dark_image(self):
        # a dark (but usable) frame cannot be CLEAR, but a recognised obstruction is still reported
        self.assertEqual(fa([CENTRE_BIG], status="warn", brightness=35.0).level, BLOCKED_VIEW)


class TestTemporalPolicy(unittest.TestCase):
    def run_frames(self, g, frames, t0=0.0, dt=0.4):
        out = []
        for i, f in enumerate(frames):
            out.append(g.update(f, t0 + i * dt))
        return out

    def test_clear_needs_three_good_frames_and_is_said_once(self):
        g = PathGuide()
        r = self.run_frames(g, [fa([])] * 6)
        self.assertEqual([x["state"] for x in r[:3]], [None, None, CLEAR_VIEW])
        self.assertEqual([x["text"] for x in r if x["announce"]], [MESSAGES["chest"][CLEAR_VIEW]])

    def test_single_frame_flicker_does_not_change_state(self):
        g = PathGuide()
        self.run_frames(g, [fa([])] * 3)
        r = self.run_frames(g, [fa([CENTRE_SMALL]), fa([]), fa([]), fa([])], t0=2.0)
        self.assertTrue(all(x["state"] == CLEAR_VIEW for x in r))
        self.assertFalse(any(x["announce"] for x in r))

    def test_possible_then_blocked_then_clear(self):
        g = PathGuide()
        self.run_frames(g, [fa([])] * 3)
        r = self.run_frames(g, [fa([CENTRE_SMALL]), fa([CENTRE_SMALL])], t0=2.0)
        self.assertEqual(r[-1]["state"], POSSIBLE_OBSTACLE)
        self.assertEqual(r[-1]["text"], "Caution. An object is detected in the walking path.")
        self.assertEqual(r[-1]["category"], "obstacle")
        r = self.run_frames(g, [fa([CENTRE_BIG]), fa([CENTRE_BIG])], t0=3.0)
        self.assertEqual(r[-1]["state"], BLOCKED_VIEW)
        self.assertEqual(r[-1]["text"], "Stop. The walking path may be blocked.")
        self.assertEqual(r[-1]["category"], "urgent")
        r = self.run_frames(g, [fa([])] * 3, t0=6.0)
        self.assertEqual(r[-1]["state"], CLEAR_VIEW)                 # clear again only after 3 clean frames
        self.assertTrue(r[-1]["announce"])

    def test_blocked_reminder_but_no_constant_repeats(self):
        g = PathGuide(blocked_reminder_s=8.0)
        r = self.run_frames(g, [fa([CENTRE_BIG])] * 30, dt=0.4)    # 12 s of the same obstruction
        texts = [x["text"] for x in r if x["announce"]]
        self.assertEqual(texts, ["Stop. The walking path may be blocked.", "Stop. The walking path may still be blocked."])

    def test_possible_reannounced_only_when_obstruction_changes(self):
        g = PathGuide(possible_change_cooldown_s=4.0)
        left_ish = det(240, 300, 300, 400)
        right_ish = det(350, 300, 410, 400)
        r = self.run_frames(g, [fa([left_ish])] * 15)              # same obstruction for 6 s
        self.assertEqual(sum(x["announce"] for x in r), 1)
        r = self.run_frames(g, [fa([left_ish, det(310, 380, 360, 470, "Bicycle")])] * 3, t0=10.0)
        self.assertEqual(sum(x["announce"] for x in r), 0)          # different object, same side/level: no repeat
        g2 = PathGuide(possible_change_cooldown_s=4.0)
        self.run_frames(g2, [fa([CENTRE_SMALL])] * 3)
        r = self.run_frames(g2, [fa([RIGHT_CLOSE])] * 3, t0=5.0)    # obstruction moved to the right side
        self.assertEqual(sum(x["announce"] for x in r), 1)

    def test_deescalation_waits_but_escalation_is_immediate(self):
        g = PathGuide(deescalate_min_s=2.0)
        r = self.run_frames(g, [fa([CENTRE_BIG])] * 2, dt=0.2)
        self.assertEqual(r[-1]["state"], BLOCKED_VIEW)
        r = self.run_frames(g, [fa([])] * 3, t0=0.4, dt=0.2)       # clear evidence after 1 s: too soon to relax
        self.assertEqual(r[-1]["state"], BLOCKED_VIEW)
        r = self.run_frames(g, [fa([])], t0=2.6)
        self.assertEqual(r[-1]["state"], CLEAR_VIEW)

    def test_uncertain_and_camera_unavailable(self):
        g = PathGuide()
        r = self.run_frames(g, [fa([], status="unusable")] * 2)
        self.assertEqual(r[-1]["state"], UNCERTAIN)
        self.assertEqual(r[-1]["text"], "I cannot clearly assess the path. Please check carefully.")
        u = g.camera_unavailable(5.0)
        self.assertEqual((u["state"], u["text"], u["category"]), (CAMERA_UNAVAILABLE, "Camera view is unavailable.", "system"))

    def test_uncertain_never_followed_by_premature_clear(self):
        g = PathGuide()
        r = self.run_frames(g, [fa([], status="unusable")] * 2 + [fa([])] * 2, dt=1.0)
        self.assertEqual(r[-1]["state"], UNCERTAIN)                # 2 good frames are not enough
        r = self.run_frames(g, [fa([])], t0=10)
        self.assertEqual(r[-1]["state"], CLEAR_VIEW)

    def test_handheld_wording(self):
        g = PathGuide("handheld")
        r = self.run_frames(g, [fa([CENTRE_BIG])] * 2)
        self.assertEqual(r[-1]["text"], "Stop. The view in front of the camera may be blocked.")
        for state, msg in MESSAGES["handheld"].items():
            self.assertNotIn("walking path", msg, state)

    def test_messages_have_no_technical_terms(self):
        for mode in MESSAGES.values():
            for msg in mode.values():
                low = msg.lower()
                for word in ("class", "bounding", "box", "confidence", "human detected", "metre", "safe"):
                    self.assertNotIn(word, low, msg)


@unittest.skipUnless(HAVE_RGB and DETEC.is_dir(), "detector weights or demo frames missing")
class TestAwarenessIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from neurosonic.awareness import RGBAwareness
        cls.a = RGBAwareness()

    def frames(self, name, session, describe, n=3):
        j = cv2.imencode(".jpg", cv2.imread(str(DETEC / name)))[1].tobytes()
        return [self.a.process_frame(j, session=session, mode="chest", t=i * 0.4, describe=describe) for i in range(n)]

    def test_object_description_off_speaks_no_object_names(self):
        rs = self.frames("0000060683.png", "d-off", describe=False)
        texts = [e["text"] for r in rs for e in r["events"]]
        self.assertEqual(texts, ["Stop. The walking path may be blocked."])
        self.assertEqual(rs[-1]["path"]["state"], BLOCKED_VIEW)
        self.assertTrue(rs[-1]["path"]["in_path"])                 # objects still reported for the UI overlay

    def test_object_description_on_adds_names_with_position(self):
        rs = self.frames("0000060683.png", "d-on", describe=True)
        texts = [e["text"] for r in rs for e in r["events"]]
        self.assertIn("Stop. The walking path may be blocked.", texts)
        self.assertTrue(any(t.startswith(("Person", "Bicycle")) for t in texts), texts)
        desc = [e for r in rs for e in r["events"] if e["kind"] == "object"]
        self.assertTrue(desc and all(e["category"] == "description" and not e["urgent"] for e in desc))

    def test_empty_scene_becomes_clear_view(self):
        rs = self.frames("0000000018.png", "empty", describe=False)
        self.assertEqual(rs[-1]["path"]["state"], CLEAR_VIEW)
        self.assertEqual([e["text"] for r in rs for e in r["events"]], ["The visible path appears clear. Continue carefully."])

    def test_dark_and_blurred_frames_are_uncertain(self):
        for name, im in (("dark", np.full((480, 640, 3), 8, np.uint8)),
                         ("blur", cv2.GaussianBlur(cv2.imread(str(DETEC / "0000060683.png")), (31, 31), 0))):
            with self.subTest(name):
                j = cv2.imencode(".jpg", im)[1].tobytes()
                rs = [self.a.process_frame(j, session=name, t=i * 0.4) for i in range(2)]
                self.assertEqual(rs[-1]["path"]["state"], UNCERTAIN)


@unittest.skipUnless(HAVE_RGB and DETEC.is_dir(), "detector weights or demo frames missing")
class TestAwarenessEndpointDescribe(unittest.TestCase):
    def test_describe_query_parameter(self):
        from neurosonic.awareness import RGBAwareness
        from neurosonic.server import make_server, serve_in_thread
        from neurosonic.store import Store
        td = Path(tempfile.mkdtemp(prefix="ns_path_"))
        store = Store(td / "t.sqlite3")

        class Svc:
            class events:   # noqa: N801
                @staticmethod
                def add(*a, **k):
                    store.add_alert(a[0], a[1], a[2])

        httpd = make_server(Svc(), store, "127.0.0.1", 0, awareness=RGBAwareness())
        serve_in_thread(httpd)
        try:
            j = cv2.imencode(".jpg", cv2.imread(str(DETEC / "0000060683.png")))[1].tobytes()
            for describe, session in (("0", "a"), ("1", "b")):
                texts = []
                for _ in range(3):
                    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=60)
                    c.request("POST", f"/api/awareness/frame?session={session}&mode=chest&describe={describe}", j,
                              {"Content-Type": "image/jpeg"})
                    r = json.loads(c.getresponse().read())
                    c.close()
                    texts += [e["text"] for e in r["events"]]
                    self.assertIn("path", r)
                    self.assertEqual(r["describe"], describe == "1")
                if describe == "0":
                    self.assertFalse(any(t.startswith(("Person", "Bicycle")) for t in texts), texts)
                else:
                    self.assertTrue(any(t.startswith(("Person", "Bicycle")) for t in texts), texts)
            kinds = {h["kind"] for h in store.history(50)}
            self.assertIn("path", kinds)                            # path announcements reach the history
        finally:
            httpd.shutdown()
            httpd.server_close()
            store.close()
            shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
