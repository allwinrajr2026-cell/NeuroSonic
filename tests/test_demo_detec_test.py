"""Smoke test for the primary demo set demo_data/detec_test (real, unlabelled frames)."""
import json
import unittest

from tests._common import ROOT, detector
from woad.pairing import pair_directories, resolve_source_root

DEMO = ROOT / "demo_data" / "detec_test"


@unittest.skipUnless((DEMO / "manifest.json").exists(), "detec_test demo missing (run tools/prepare_detec_test_demo.py)")
class TestDetecTestDemo(unittest.TestCase):
    def test_layout_and_pairing(self):
        ir_dir, depth_dir = resolve_source_root(DEMO)
        pairing = pair_directories(ir_dir, depth_dir)
        self.assertTrue(pairing.complete)
        manifest = json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(pairing.pairs), manifest["pairs"])
        self.assertEqual(manifest["pairs"], 600)

    def test_known_frames(self):
        # Values observed on 2026-11-02 (see demo_data/detec_test/README.md).
        for name, cls, min_conf in (("0000061265.png", "person", 0.9), ("0000060683.png", "Ebike", 0.9),
                                    ("0000000191.png", "person", 0.7)):
            with self.subTest(frame=name):
                res, _ = detector().detect_files(DEMO / "ir" / name, DEMO / "depth" / name)
                best = max(res["detections"], key=lambda d: d["confidence"])
                self.assertEqual(best["class_name"], cls)
                self.assertGreater(best["confidence"], min_conf)


if __name__ == "__main__":
    unittest.main()
