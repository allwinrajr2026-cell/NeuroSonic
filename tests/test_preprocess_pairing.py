"""Preprocessing fidelity (letterbox, median blur, colour order, normalisation) and filename pairing."""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
import torch

from tests._common import ROOT  # noqa: F401  (sets sys.path)
from woad.pairing import PairingError, pair_directories, resolve_source_root
from woad.preprocess import InputImageError, load_pair, prepare_pair, read_image


class TestPreprocess(unittest.TestCase):
    def test_letterbox_640x480(self):
        ir = np.full((480, 640, 3), 200, np.uint8)
        p = prepare_pair(ir, ir.copy())
        for t in (p.ir, p.depth):
            self.assertEqual(tuple(t.shape), (1, 3, 640, 640))
            self.assertEqual(t.dtype, torch.float32)
            # 80 px of pad value 114 above and below the 480-row frame
            self.assertTrue(torch.allclose(t[0, :, :80, :], torch.tensor(114 / 255)))
            self.assertTrue(torch.allclose(t[0, :, 560:, :], torch.tensor(114 / 255)))
            self.assertTrue(torch.allclose(t[0, :, 80:560, :], torch.tensor(200 / 255)))

    def test_bgr_to_rgb_and_range(self):
        bgr_blue = np.zeros((480, 640, 3), np.uint8)
        bgr_blue[..., 0] = 255  # pure blue in OpenCV BGR
        p = prepare_pair(bgr_blue, bgr_blue.copy())
        for t in (p.ir, p.depth):
            content = t[0, :, 80:560, :]
            self.assertEqual(float(content[2].min()), 1.0)  # RGB channel 2 = blue
            self.assertEqual(float(content[0].max()), 0.0)  # RGB channel 0 = red
            self.assertGreaterEqual(float(t.min()), 0.0)
            self.assertLessEqual(float(t.max()), 1.0)

    def test_median_blur_on_depth_only(self):
        img = np.zeros((480, 640, 3), np.uint8)
        img[240, 320] = 255  # isolated salt pixel
        p = prepare_pair(img, img.copy())
        self.assertEqual(float(p.ir[0, 0, 80 + 240, 320]), 1.0, "IR must not be blurred")
        self.assertEqual(float(p.depth[0, 0, 80 + 240, 320]), 0.0, "depth must be median-blurred (k=3)")

    def test_resolution_mismatch_flag(self):
        p = prepare_pair(np.zeros((480, 640, 3), np.uint8), np.zeros((240, 320, 3), np.uint8))
        self.assertTrue(p.size_mismatch)
        self.assertEqual(tuple(p.depth.shape), (1, 3, 640, 640))

    def test_large_ir_downscaled(self):
        p = prepare_pair(np.zeros((960, 1280, 3), np.uint8), np.zeros((960, 1280, 3), np.uint8))
        self.assertEqual(tuple(p.ir.shape), (1, 3, 640, 640))

    def test_bad_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            cv2.imwrite(str(td / "d16.png"), np.zeros((48, 64), np.uint16))
            cv2.imwrite(str(td / "gray.png"), np.zeros((48, 64), np.uint8))
            (td / "broken.png").write_bytes(b"not an image")
            with self.assertRaisesRegex(InputImageError, "16|uint16"):
                read_image(td / "d16.png", "depth")
            with self.assertRaisesRegex(InputImageError, "single-channel"):
                read_image(td / "gray.png", "depth")
            self.assertEqual(read_image(td / "gray.png", "IR").shape, (48, 64, 3))  # gray IR is expanded
            with self.assertRaisesRegex(InputImageError, "decoded"):
                read_image(td / "broken.png", "IR")
            with self.assertRaisesRegex(InputImageError, "not found"):
                load_pair(td / "missing.png", td / "gray.png")


class TestPairing(unittest.TestCase):
    def _make(self, td, ir_names, depth_names):
        (td / "ir").mkdir()
        (td / "depth").mkdir()
        img = np.zeros((8, 8, 3), np.uint8)
        for n in ir_names:
            cv2.imwrite(str(td / "ir" / n), img)
        for n in depth_names:
            cv2.imwrite(str(td / "depth" / n), img)

    def test_exact_name_pairing(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            self._make(td, ["a.png", "b.png", "c.png"], ["b.png", "a.png", "d.png"])
            r = pair_directories(td / "ir", td / "depth")
            self.assertEqual([(i.name, d.name) for i, d in r.pairs], [("a.png", "a.png"), ("b.png", "b.png")])
            self.assertEqual([p.name for p in r.ir_without_depth], ["c.png"])
            self.assertEqual([p.name for p in r.depth_without_ir], ["d.png"])
            self.assertFalse(r.complete)
            self.assertIn("c.png", r.describe_missing())
            self.assertIn("d.png", r.describe_missing())

    def test_stem_pairing_allows_extension_change(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            self._make(td, ["a.jpg"], ["a.png"])
            self.assertEqual(len(pair_directories(td / "ir", td / "depth", "name").pairs), 0)
            self.assertEqual(len(pair_directories(td / "ir", td / "depth", "stem").pairs), 1)

    def test_ambiguous_stem(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            self._make(td, ["a.jpg", "a.png"], ["a.png"])
            with self.assertRaisesRegex(PairingError, "ambiguous"):
                pair_directories(td / "ir", td / "depth", "stem")

    def test_missing_dirs_and_empty(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            with self.assertRaisesRegex(PairingError, "must contain 'ir/' and 'depth/'"):
                resolve_source_root(td)
            self._make(td, [], ["a.png"])
            with self.assertRaisesRegex(PairingError, "no images"):
                pair_directories(td / "ir", td / "depth")


if __name__ == "__main__":
    unittest.main()
