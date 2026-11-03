"""Model loading, checkpoint integrity, two-input forward pass, equivalence with the original code."""
import sys
import unittest

import torch

from tests._common import ORIGINAL_CKPT, ORIGINAL_REPO, ROOT, detector
from woad.arch.yolo import Model
from woad.model_loader import (DEFAULT_WEIGHTS, EXP72_BEST_SHA256, EXPECTED_NAMES, CheckpointError, load_model,
                               sha256)


class TestCheckpoint(unittest.TestCase):
    def test_copied_checkpoint_hash(self):
        self.assertTrue(DEFAULT_WEIGHTS.is_file(), f"missing {DEFAULT_WEIGHTS}")
        self.assertEqual(sha256(DEFAULT_WEIGHTS), EXP72_BEST_SHA256)

    @unittest.skipUnless(ORIGINAL_CKPT.is_file(), "original repository not present")
    def test_original_checkpoint_untouched(self):
        self.assertEqual(sha256(ORIGINAL_CKPT), EXP72_BEST_SHA256)

    def test_missing_checkpoint_error(self):
        with self.assertRaises(CheckpointError):
            load_model(ROOT / "weights" / "does_not_exist.pt")

    @unittest.skipUnless((ORIGINAL_REPO / "best.pt").is_file(), "original repository not present")
    def test_incompatible_root_checkpoint_rejected(self):
        # The repository-root best.pt is a different 5-class fusion variant the exp72 code cannot run.
        with self.assertRaises(CheckpointError) as cm:
            load_model(ORIGINAL_REPO / "best.pt")
        self.assertIn("different cross-modal variant", str(cm.exception))


class TestModelLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = detector().model
        cls.info = detector().info

    def test_metadata(self):
        self.assertIsInstance(self.model, Model)
        self.assertEqual(self.info["names"], EXPECTED_NAMES)
        self.assertEqual(self.info["nc"], 3)
        self.assertEqual(self.info["stride"], [8, 16, 32])
        self.assertEqual(self.info["num_params"], 7521992)

    def test_eval_mode_and_frozen(self):
        self.assertFalse(self.model.training)
        self.assertTrue(all(not m.training for m in self.model.modules()))
        self.assertTrue(all(not p.requires_grad for p in self.model.parameters()))

    def test_fusion_modules_present(self):
        self.assertEqual(len(self.model.trans_blocks), 8)
        self.assertEqual(tuple(self.model.pos_emb.shape), (1, 128, 64))
        self.assertEqual([type(m).__name__ for m in self.model.model1], ["Conv", "Conv", "C3"])

    def test_no_legacy_module_leak(self):
        leaked = [k for k in sys.modules if k == "models" or k.startswith("models.")]
        self.assertEqual(leaked, [], "legacy 'models' aliases must be removed after loading")


class TestForward(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = detector().model

    def test_two_input_forward_640(self):
        with torch.inference_mode():
            pred, feats = self.model(torch.rand(2, 3, 640, 640), torch.rand(2, 3, 640, 640))
        self.assertEqual(tuple(pred.shape), (2, 25200, 8))  # 3 anchors x (80^2+40^2+20^2), 5+3 outputs
        self.assertEqual(len(feats), 3)
        self.assertTrue(torch.isfinite(pred).all())
        self.assertTrue(((pred[..., 4:] >= 0) & (pred[..., 4:] <= 1)).all(), "obj/cls must be probabilities")

    def test_single_input_rejected(self):
        # The original detect/val/train scripts passed one width-concatenated tensor; that is invalid here.
        with self.assertRaises(TypeError):
            self.model(torch.rand(1, 3, 640, 1280))

    def test_mismatched_modality_sizes_rejected(self):
        with self.assertRaises(RuntimeError):
            with torch.inference_mode():
                self.model(torch.rand(1, 3, 640, 640), torch.rand(1, 3, 320, 320))

    def test_deterministic(self):
        g = torch.Generator().manual_seed(1)
        ir, dp = torch.rand(1, 3, 640, 640, generator=g), torch.rand(1, 3, 640, 640, generator=g)
        with torch.inference_mode():
            a, b = self.model(ir, dp)[0], self.model(ir, dp)[0]
        self.assertTrue(torch.equal(a, b))


@unittest.skipUnless((ORIGINAL_REPO / "models" / "yolo.py").is_file(), "original repository not present")
class TestEquivalenceWithOriginal(unittest.TestCase):
    def test_bit_exact_vs_original_code(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import verify_equivalence
        code, msg = verify_equivalence.run(ORIGINAL_REPO)
        self.assertEqual(code, 0, msg)


if __name__ == "__main__":
    unittest.main()
