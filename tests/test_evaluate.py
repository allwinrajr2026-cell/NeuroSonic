"""Evaluation path: vendored metrics == original code, label rules, class mapping, end-to-end sanity."""
import ast
import contextlib
import io
import json
import shutil
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np
import torch

from tests._common import ROOT, demo_available, demo_pair, detector
from woad.metrics import IOUV, ap_per_class, process_batch

ORIGINAL_METRICS = ROOT.parent / "original" / "Cross-Modal obstacle detection" / "utils" / "metrics.py"


def load_original_functions(path, names):
    """Exec selected top-level functions of the original file (read-only), without its imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mod = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names],
                     type_ignores=[])
    np_shim = types.SimpleNamespace(**{k: getattr(np, k) for k in dir(np) if not k.startswith("__")})
    np_shim.trapz = np.trapezoid  # np.trapz no longer exists in NumPy 2.5
    ns = {"np": np_shim}
    exec(compile(mod, str(path), "exec"), ns)
    return ns


class TestMetricsMatchOriginal(unittest.TestCase):
    @unittest.skipUnless(ORIGINAL_METRICS.exists(), "original repository not found")
    def test_ap_per_class_equals_original(self):
        orig = load_original_functions(ORIGINAL_METRICS, {"ap_per_class", "compute_ap"})
        rng = np.random.default_rng(0)
        for trial in range(5):
            n = 400
            tp = rng.random((n, 10)) < np.linspace(0.8, 0.2, 10)
            conf = rng.random(n)
            pred_cls = rng.integers(0, 3, n).astype(float)
            target_cls = rng.integers(0, 3, 300).astype(float)
            o = orig["ap_per_class"](tp, conf, pred_cls, target_cls, plot=False, names={})
            m = ap_per_class(tp, conf, pred_cls, target_cls)
            np.testing.assert_allclose(m["ap"], o[5])
            np.testing.assert_allclose(m["p"], o[2])
            np.testing.assert_allclose(m["r"], o[3])
            np.testing.assert_array_equal(m["classes"], o[6])

    def test_perfect_predictions_give_max_ap(self):
        # The original 101-point interpolation (sentinel recall 1.0 / precision 0) caps AP at 0.995.
        tp = np.ones((5, 10), bool)
        m = ap_per_class(tp, np.linspace(0.9, 0.5, 5), np.zeros(5), np.zeros(5))
        self.assertAlmostEqual(float(m["ap"][0, 0]), 0.995, places=6)

    def test_process_batch_iou_levels(self):
        labels = torch.tensor([[0, 0, 0, 100, 100]], dtype=torch.float32)
        # IoU = 80*100 / (100*100) = 0.8 -> correct at 0.50..0.80, not above
        dets = torch.tensor([[0, 0, 80, 100, 0.9, 0], [0, 0, 100, 100, 0.8, 1]], dtype=torch.float32)
        c = process_batch(dets, labels, IOUV)
        self.assertEqual(c[0].tolist(), [bool(t <= 0.8 + 1e-6) for t in IOUV.tolist()])
        self.assertFalse(c[1].any())  # wrong class never matches


class TestLabelRulesAndClassMap(unittest.TestCase):
    def setUp(self):
        from tools import evaluate
        self.ev = evaluate
        self.td = Path(tempfile.mkdtemp(prefix="woad_eval_test_"))

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def lb(self, text):
        p = self.td / "x.txt"
        p.write_text(text)
        return self.ev.read_labels(p)

    def test_label_rules(self):
        self.assertEqual(self.ev.read_labels(self.td / "missing.txt")[0].shape, (0, 5))
        ok, prob = self.lb("0 0.5 0.5 0.2 0.2\n0 0.5 0.5 0.2 0.2")
        self.assertIsNone(prob)
        self.assertEqual(len(ok), 1)  # duplicate removed
        self.assertIsNotNone(self.lb("0 0.5 0.5 1.2 0.2")[1])
        self.assertIsNotNone(self.lb("0 0.5 0.5 0.2")[1])
        self.assertIsNotNone(self.lb("-1 0.5 0.5 0.2 0.2")[1])

    def test_class_map(self):
        names = ["person", "Ebike", "Car"]
        self.assertEqual(self.ev.parse_class_map("0:person,2:Ebike", names), {0: 0, 2: 1})
        self.assertEqual(self.ev.parse_class_map("3:2", names), {3: 2})
        for bad in ("0:bike", "0:person,1:person", "x:person", "0:5"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.ev.parse_class_map(bad, names)


@unittest.skipUnless(demo_available(), "reconstructed demo samples missing")
class TestEvaluateEndToEnd(unittest.TestCase):
    """Labels = the model's own confident detections, so mAP@0.5 must be ~1 and a class map must apply."""

    FRAMES = ["recon_b00_i03.png", "recon_b00_i04.png", "recon_b00_i08.png", "recon_b00_i13.png"]

    def setUp(self):
        from tools import evaluate
        self.ev = evaluate
        self.td = Path(tempfile.mkdtemp(prefix="woad_eval_e2e_"))
        for d in ("images", "clouds", "labels"):
            (self.td / d / "val").mkdir(parents=True)
        self.n_gt = 0
        for f in self.FRAMES:
            ir, dp = demo_pair(f)
            shutil.copy(ir, self.td / "images" / "val" / f)
            shutil.copy(dp, self.td / "clouds" / "val" / f)
            res, _ = detector().detect_files(ir, dp)
            w, h = res["image_size"]["width"], res["image_size"]["height"]
            rows = []
            for d in res["detections"]:
                if d["confidence"] < 0.5:
                    continue
                x1, y1, x2, y2 = d["box_xyxy"]
                ds_cls = {0: 5, 1: 7}.get(d["class_id"], 9)  # dataset uses different ids on purpose
                rows.append(f"{ds_cls} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
                self.n_gt += 1
            (self.td / "labels" / "val" / (Path(f).stem + ".txt")).write_text("\n".join(rows))

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_self_consistency(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.ev.main(["--split-root", str(self.td), "--split", "val", "--class-map", "5:person,7:Ebike",
                                 "--project", str(self.td / "runs"), "--name", "e", "--quiet"])
        self.assertEqual(code, 0)
        meta = json.loads((self.td / "runs" / "e" / "metrics.json").read_text(encoding="utf-8"))
        self.assertGreater(self.n_gt, 3)
        self.assertEqual(meta["data_report"]["images_evaluated"], len(self.FRAMES))
        self.assertGreater(meta["summary"]["mAP50"], 0.98, meta["per_class"])  # metric maximum is 0.995
        self.assertEqual({c["model_class"] for c in meta["per_class"]}, {"person", "Ebike"})


if __name__ == "__main__":
    unittest.main()
