"""End-to-end detection regression, input-order and blanked-input ablation checks.

Uses the reconstructed (degraded) validation demo samples - see demo_data/reconstructed_val/README.md.
Thresholds were calibrated on 48 frames (batches 0-2) with large margins:
    measured conf-mass ratio vs. normal: swapped 0.08, zero IR 0.00, zero depth 0.65.
"""
import json
import unittest

import cv2
import torch

from tests._common import GOLDEN, demo_available, demo_pair, detector, iou
from woad.preprocess import prepare_pair

ABLATION_FRAMES = [f"recon_b{b:02d}_i{i:02d}.png" for b in (0, 1) for i in range(16)]


def conf_mass(prepared, ir, depth):
    prepared.ir, prepared.depth = ir, depth
    dets = detector().detect_prepared(prepared)["detections"]
    return sum(d["confidence"] for d in dets), len(dets)


@unittest.skipUnless(demo_available(), "reconstructed demo samples missing (run tools/reconstruct_val_samples.py)")
class TestDetectionRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_golden_fixture_matches_weights(self):
        self.assertEqual(self.golden["weights_sha256"], detector().info["sha256"])

    def test_golden_detections(self):
        for frame, expected in self.golden["frames"].items():
            with self.subTest(frame=frame):
                res, _ = detector().detect_files(*demo_pair(frame))
                got = res["detections"]
                self.assertEqual(len(got), len(expected), f"{frame}: {got} vs {expected}")
                for g, e in zip(sorted(got, key=lambda d: -d["confidence"]),
                                sorted(expected, key=lambda d: -d["confidence"])):
                    self.assertEqual(g["class_name"], e["class_name"])
                    self.assertAlmostEqual(g["confidence"], e["confidence"], delta=0.02)
                    self.assertGreaterEqual(iou(g["box_xyxy"], e["box_xyxy"]), 0.9)

    def test_known_objects(self):
        # Corroborated by the predictions saved during training (val_lidar batch0_pred.jpg).
        for frame, cls in (("recon_b00_i03.png", "person"), ("recon_b00_i08.png", "Ebike"),
                           ("recon_b00_i13.png", "Ebike")):
            with self.subTest(frame=frame):
                res, _ = detector().detect_files(*demo_pair(frame))
                best = max(res["detections"], key=lambda d: d["confidence"])
                self.assertEqual(best["class_name"], cls)
                self.assertGreater(best["confidence"], 0.5)

    def test_boxes_in_original_coordinates(self):
        res, _ = detector().detect_files(*demo_pair("recon_b00_i04.png"))
        self.assertEqual(res["image_size"], {"width": 640, "height": 480})
        self.assertTrue(res["detections"])
        for d in res["detections"]:
            x1, y1, x2, y2 = d["box_xyxy"]
            self.assertTrue(0 <= x1 < x2 <= 640 and 0 <= y1 < y2 <= 480, d)

    def test_box_mapping_scales_with_input_resolution(self):
        # Same scene at 2x resolution must give the same boxes scaled by 2 (letterbox + scale_coords inverse).
        ir_p, dp_p = demo_pair("recon_b00_i04.png")
        ir, dp = cv2.imread(str(ir_p)), cv2.imread(str(dp_p))
        small = detector().detect_arrays(ir, dp)["detections"]
        big = detector().detect_arrays(cv2.resize(ir, (1280, 960)), cv2.resize(dp, (1280, 960)))["detections"]
        self.assertTrue(small)
        for s in small:
            scaled = [v * 2 for v in s["box_xyxy"]]
            best = max(big, key=lambda b: iou(b["box_xyxy"], scaled))
            self.assertEqual(best["class_name"], s["class_name"])
            self.assertGreaterEqual(iou(best["box_xyxy"], scaled), 0.85)


@unittest.skipUnless(demo_available(), "reconstructed demo samples missing (run tools/reconstruct_val_samples.py)")
class TestModalityChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mass = {k: 0.0 for k in ("normal", "swapped", "zero_ir", "zero_depth")}
        for f in ABLATION_FRAMES:
            ir_p, dp_p = demo_pair(f)
            p = prepare_pair(cv2.imread(str(ir_p)), cv2.imread(str(dp_p)))
            ir, dp = p.ir.clone(), p.depth.clone()
            cls.mass["normal"] += conf_mass(p, ir, dp)[0]
            cls.mass["swapped"] += conf_mass(p, dp, ir)[0]
            cls.mass["zero_ir"] += conf_mass(p, torch.zeros_like(ir), dp)[0]
            cls.mass["zero_depth"] += conf_mass(p, ir, torch.zeros_like(dp))[0]

    def ratio(self, k):
        return self.mass[k] / self.mass["normal"]

    def test_normal_detects(self):
        self.assertGreater(self.mass["normal"], 10.0)

    def test_input_order(self):
        # model(ir, depth) is correct; swapping the streams collapses detections (measured ratio 0.08).
        self.assertLess(self.ratio("swapped"), 0.4, self.mass)

    def test_blank_ir(self):
        # IR is the dominant stream (measured ratio 0.00).
        self.assertLess(self.ratio("zero_ir"), 0.1, self.mass)

    def test_blank_depth(self):
        # Depth contributes measurably (measured ratio 0.65): blanking it must reduce detections.
        self.assertLess(self.ratio("zero_depth"), 0.85, self.mass)


if __name__ == "__main__":
    unittest.main()
