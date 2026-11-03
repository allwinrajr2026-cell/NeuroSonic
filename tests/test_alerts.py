"""Stage 2: alert engine (synthetic detections), quality checker, replay source and woad_replay CLI."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests._common import ROOT, demo_available, demo_pair
from woad.alerts import AlertConfig, AlertEngine
from woad.quality import OK, UNUSABLE, WARN, InputQualityChecker, QualityReport
from woad.sources import ReplaySource

GOOD = QualityReport(OK)
W = 640


def det(cls, x1, y1, x2, y2, conf=0.8):
    return {"class_name": cls, "confidence": conf, "box_xyxy": [x1, y1, x2, y2]}


AHEAD = (280, 100, 360, 400)   # centre x = 320 -> ahead
LEFT = (20, 100, 100, 400)     # centre x = 60  -> left
RIGHT = (560, 100, 630, 400)   # centre x = 595 -> right


class Runner:
    def __init__(self, fps=5.0, **cfg):
        self.e = AlertEngine(AlertConfig(**cfg))
        self.i, self.fps = 0, fps

    def step(self, dets, quality=GOOD, segment_start=False, error=None, detections_none=False):
        ev = self.e.process(time=self.i / self.fps, frame_index=self.i, frame_id=f"f{self.i}", image_width=W,
                            detections=None if detections_none else dets, quality=quality,
                            segment_start=segment_start, error=error)
        self.i += 1
        return [x.text for x in ev]

    def run(self, frames, **kw):
        return [self.step(f, **kw) for f in frames]


class TestAlertEngine(unittest.TestCase):
    def test_single_frame_flicker_is_not_announced(self):
        r = Runner()
        out = r.run([[det("person", *AHEAD)], [], [], [], [det("person", *AHEAD)], [], []])
        self.assertEqual(sum(out, []), [])

    def test_confirmation_then_single_announcement(self):
        r = Runner()
        out = r.run([[det("person", *AHEAD)]] * 20)  # 4 s, below repeat_s
        self.assertEqual(out[0], [])
        self.assertEqual(out[1], ["Person detected ahead."])
        self.assertEqual(sum(out[2:], []), [])

    def test_positions_and_wording(self):
        for box, text in ((LEFT, "Car detected on the left."), (RIGHT, "Car detected on the right."),
                          (AHEAD, "Car detected ahead.")):
            with self.subTest(text=text):
                r = Runner()
                out = r.run([[det("Car", *box)]] * 2)
                self.assertEqual(out[1], [text])
        r = Runner()
        self.assertEqual(r.run([[det("Ebike", *LEFT)]] * 2)[1], ["E-bike detected on the left."])

    def test_low_confidence_is_ignored(self):
        r = Runner(alert_conf=0.4)
        out = r.run([[det("person", *AHEAD, conf=0.39)]] * 10)
        self.assertEqual(sum(out, []), [])

    def test_repeat_after_repeat_s_while_present(self):
        r = Runner(repeat_s=3.0, cooldown_s=1.0)
        out = r.run([[det("person", *AHEAD)]] * 25)  # 5 s at 5 fps
        said = [i for i, o in enumerate(out) if o]
        self.assertEqual(said, [1, 16])  # t=0.2 s, then t=3.2 s

    def test_position_change_is_announced(self):
        r = Runner(track_iou=0.0001)
        # same person moves from the left third (centre x 150) to the middle third (centre x 320)
        frames = [[det("person", *b)] for b in [(100, 100, 200, 400)] * 3 + [(260, 100, 380, 400)] * 3]
        out = r.run(frames)
        self.assertEqual(out[1], ["Person detected on the left."])
        self.assertIn("Person detected ahead.", sum(out[3:], []))

    def test_merge_and_priority_and_limit(self):
        r = Runner(max_object_alerts_per_frame=2)
        frame = [det("person", 270, 100, 300, 300), det("person", 330, 100, 360, 300),
                 det("Car", *LEFT), det("Ebike", *RIGHT)]
        out = r.run([frame] * 2 + [frame])
        self.assertEqual(out[1], ["Car detected on the left.", "E-bike detected on the right."])
        self.assertEqual(out[2], ["2 people detected ahead."])   # deferred group follows next frame

    def test_no_object_alert_without_current_detection(self):
        # invariant: every object alert refers to a detection present in that very frame
        rng = np.random.default_rng(1)
        r = Runner()
        for _ in range(300):
            dets = [det(rng.choice(["person", "Car", "Ebike"]), x, 100, x + 60, 300, conf=float(rng.uniform(0.2, 1)))
                    for x in rng.integers(0, 580, rng.integers(0, 3))]
            ev = r.e.process(time=r.i / 5, frame_index=r.i, frame_id="x", image_width=W, detections=dets, quality=GOOD)
            r.i += 1
            for e in ev:
                if e.kind == "object":
                    current = {(d["class_name"], tuple(d["box_xyxy"])) for d in dets if d["confidence"] >= 0.4}
                    for b in e.data["boxes_xyxy"]:
                        self.assertIn((e.data["class_name"], tuple(b)), {(c, tuple(map(float, bb))) for c, bb in current})

    def test_unusable_input_unavailable_then_resumed(self):
        r = Runner(unavailable_after_s=1.0, resume_after_s=1.0)
        bad = QualityReport(UNUSABLE, ["IR image too dark (mean 20)"])
        out = r.run([[det("person", *AHEAD)]] * 8, quality=bad)        # t = 0 .. 1.4
        self.assertEqual(sum(out, []), ["Obstacle detection unavailable: IR image too dark (mean 20)."])
        self.assertEqual(out[5], ["Obstacle detection unavailable: IR image too dark (mean 20)."])
        good = r.run([[det("person", *AHEAD)]] * 8)                     # resumes after 1 s of usable input
        self.assertIn("Obstacle detection resumed.", sum(good, []))
        first_resume = next(i for i, o in enumerate(good) if "Obstacle detection resumed." in o)
        self.assertEqual(first_resume, 5)
        self.assertTrue(all("Person" not in t for o in good[:first_resume] for t in o))  # silent while unavailable

    def test_read_errors_and_missing_inference_count_as_unusable(self):
        r = Runner(unavailable_after_s=0.4)
        out = r.run([None] * 4, error="IR image not found")
        self.assertEqual(sum(out, []), ["Obstacle detection unavailable: image could not be read."])

    def test_low_quality_notice_is_rate_limited(self):
        r = Runner(low_quality_notice_s=10.0)
        warn = QualityReport(WARN, ["IR image darker than training data (mean 80)"])
        out = r.run([[]] * 60, quality=warn)   # 12 s
        notices = [i for i, o in enumerate(out) if o]
        self.assertEqual(notices, [0, 50])

    def test_stall_watchdog(self):
        r = Runner(stall_s=2.0)
        r.step([])
        self.assertEqual(r.e.tick(1.0), [])
        ev = r.e.tick(2.5)
        self.assertEqual([e.text for e in ev], ["Obstacle detection unavailable: no camera frames."])
        self.assertEqual(r.e.tick(5.0), [])   # said once

    def test_segment_start_resets_tracking(self):
        r = Runner(repeat_s=60)
        r.run([[det("person", *AHEAD)]] * 3)
        out = r.step([det("person", *AHEAD)], segment_start=True)
        self.assertEqual(out, [])            # new clip: must be confirmed again
        self.assertEqual(r.step([det("person", *AHEAD)]), ["Person detected ahead."])

    def test_config_validation(self):
        for bad in (dict(confirm_hits=4, confirm_window=3), dict(alert_conf=1.5), dict(left_edge=0.7, right_edge=0.6)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                AlertEngine(AlertConfig(**bad))


class TestQualityChecker(unittest.TestCase):
    def test_levels(self):
        q = InputQualityChecker()
        rng = np.random.default_rng(0)
        depth = np.full((480, 640, 3), 128, np.uint8)
        normal = np.clip(rng.normal(135, 70, (480, 640)), 0, 255).astype(np.uint8)
        dark = np.clip(rng.normal(60, 22, (480, 640)), 0, 255).astype(np.uint8)
        black = np.full((480, 640), 10, np.uint8)
        g3 = lambda g: np.repeat(g[..., None], 3, axis=2)
        self.assertEqual(q.check(g3(normal), depth).status, OK)
        self.assertEqual(q.check(g3(dark), depth).status, WARN)
        self.assertEqual(q.check(g3(black), depth).status, UNUSABLE)
        self.assertEqual(q.check(g3(normal), np.zeros_like(depth)).status, UNUSABLE)
        self.assertEqual(q.check(None, depth).status, UNUSABLE)

    @unittest.skipUnless(demo_available(), "demo samples missing")
    def test_training_like_frames_pass(self):
        import cv2
        q = InputQualityChecker()
        for f in ("recon_b00_i03.png", "recon_b00_i04.png", "recon_b01_i00.png"):
            ir, dp = demo_pair(f)
            self.assertEqual(q.check(cv2.imread(str(ir)), cv2.imread(str(dp))).status, OK, f)


class TestReplaySource(unittest.TestCase):
    def setUp(self):
        import cv2
        self.td = Path(tempfile.mkdtemp(prefix="woad_replay_src_"))
        (self.td / "ir").mkdir()
        (self.td / "depth").mkdir()
        img = np.full((48, 64, 3), 120, np.uint8)
        for n in (1, 2, 3, 20, 21, 100):
            cv2.imwrite(str(self.td / "ir" / f"{n:010d}.png"), img)
            cv2.imwrite(str(self.td / "depth" / f"{n:010d}.png"), img)
        (self.td / "ir" / f"{200:010d}.png").write_bytes(b"not an image")
        (self.td / "depth" / f"{200:010d}.png").write_bytes(b"not an image")

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_order_segments_timestamps_errors(self):
        frames = list(ReplaySource.from_root(self.td, fps=4, segment_gap=10))
        self.assertEqual([f.frame_id[:10] for f in frames],
                         [f"{n:010d}" for n in (1, 2, 3, 20, 21, 100, 200)])
        self.assertEqual([f.segment for f in frames], [0, 0, 0, 1, 1, 2, 3])
        self.assertEqual([f.timestamp for f in frames], [i / 4 for i in range(7)])
        self.assertIsNotNone(frames[-1].error)
        self.assertIsNone(frames[-1].ir)
        self.assertEqual([f.segment for f in ReplaySource.from_root(self.td, segment_gap=None)], [0] * 7)


@unittest.skipUnless((ROOT / "demo_data" / "detec_test" / "manifest.json").exists(), "detec_test demo missing")
class TestReplayCLI(unittest.TestCase):
    def test_deterministic_transcript_live_model(self):
        import woad_replay
        td = Path(tempfile.mkdtemp(prefix="woad_replay_cli_"))
        try:
            outs = []
            for name in ("a", "b"):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = woad_replay.main(["--source", str(ROOT / "demo_data" / "detec_test"), "--segment-gap", "10",
                                             "--start", "260", "--limit", "60", "--project", str(td),
                                             "--name", name, "--quiet"])
                self.assertEqual(code, 0)
                outs.append((td / name / "transcript.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(outs[0], outs[1])
            events = [json.loads(line) for line in outs[0].splitlines()]
            self.assertTrue(any(e["kind"] == "object" for e in events))
            summary = json.loads((td / "a" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["frames"], 60)
            self.assertEqual(summary["quality"], {"ok": 60})
        finally:
            shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
