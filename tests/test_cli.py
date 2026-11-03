"""woad_detect.py command line: output images/JSON, run-folder safety, pairing errors."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2

from tests._common import ROOT, demo_available, demo_pair
import woad_detect

FRAMES = ["recon_b00_i03.png", "recon_b00_i04.png", "recon_b00_i06.png"]  # person / 2 Ebikes / nothing


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = woad_detect.main([str(a) for a in args])
    return code, out.getvalue(), err.getvalue()


@unittest.skipUnless(demo_available(), "reconstructed demo samples missing (run tools/reconstruct_val_samples.py)")
class TestCLI(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="woad_cli_test_"))
        self.src = self.td / "src"
        (self.src / "ir").mkdir(parents=True)
        (self.src / "depth").mkdir()
        for f in FRAMES:
            ir, dp = demo_pair(f)
            shutil.copy(ir, self.src / "ir" / f)
            shutil.copy(dp, self.src / "depth" / f)
        self.project = self.td / "runs"

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_source_mode_outputs(self):
        code, out, err = run_cli("--source", self.src, "--project", self.project, "--name", "t", "--quiet")
        self.assertEqual(code, 0, err)
        run = self.project / "t"
        imgs = sorted(p.name for p in (run / "annotated").iterdir())
        self.assertEqual(imgs, [Path(f).stem + ".jpg" for f in FRAMES])
        for f in FRAMES:
            im = cv2.imread(str(run / "annotated" / (Path(f).stem + ".jpg")))
            self.assertIsNotNone(im)
            self.assertEqual(im.shape[1], 640 * 2 + 4)  # IR | separator | depth
            per = json.loads((run / "json" / (Path(f).stem + ".json")).read_text(encoding="utf-8"))
            self.assertEqual(set(per), {"ir_path", "depth_path", "image_size", "depth_size", "size_mismatch",
                                        "detections", "timing_ms"})
        meta = json.loads((run / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["summary"]["processed"], 3)
        self.assertEqual(meta["summary"]["failed"], 0)
        self.assertEqual(meta["model"]["names"], ["person", "Ebike", "Car"])
        by_name = {Path(r["ir_path"]).name: r["detections"] for r in meta["results"]}
        self.assertEqual([d["class_name"] for d in by_name["recon_b00_i03.png"]], ["person"])
        self.assertEqual(len(by_name["recon_b00_i04.png"]), 2)
        self.assertEqual(by_name["recon_b00_i06.png"], [])
        for d in by_name["recon_b00_i04.png"]:
            self.assertEqual(set(d), {"class_id", "class_name", "confidence", "box_xyxy"})

    def test_runs_are_never_overwritten(self):
        for _ in range(2):
            code, _, err = run_cli("--source", self.src, "--project", self.project, "--name", "t", "--quiet",
                                   "--no-images")
            self.assertEqual(code, 0, err)
        self.assertTrue((self.project / "t").is_dir())
        self.assertTrue((self.project / "t2").is_dir())
        self.assertFalse((self.project / "t" / "annotated").exists())

    def test_single_pair_mode_and_class_filter(self):
        ir, dp = demo_pair("recon_b00_i03.png")
        code, _, err = run_cli("--ir", ir, "--depth", dp, "--project", self.project, "--name", "s", "--quiet",
                               "--classes", "Ebike")
        self.assertEqual(code, 0, err)
        meta = json.loads((self.project / "s" / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["results"][0]["detections"], [])  # the person is filtered out

    def test_unpaired_images_abort_with_clear_error(self):
        (self.src / "depth" / FRAMES[0]).unlink()
        code, _, err = run_cli("--source", self.src, "--project", self.project, "--name", "u", "--quiet")
        self.assertEqual(code, 2)
        self.assertIn("IR images with no matching depth image", err)
        self.assertIn(FRAMES[0], err)
        self.assertIn("--skip-unpaired", err)
        self.assertFalse((self.project / "u").exists(), "no run folder should be created on error")

    def test_skip_unpaired(self):
        (self.src / "depth" / FRAMES[0]).unlink()
        code, out, err = run_cli("--source", self.src, "--project", self.project, "--name", "k",
                                 "--skip-unpaired", "--no-images")
        self.assertEqual(code, 0, err)
        self.assertIn("WARNING", out)
        meta = json.loads((self.project / "k" / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["summary"]["processed"], 2)

    def test_bad_arguments(self):
        with self.assertRaises(SystemExit):
            run_cli("--ir", "x.png")  # --depth missing
        with self.assertRaises(SystemExit):
            run_cli("--source", self.src, "--ir-dir", self.src / "ir", "--depth-dir", self.src / "depth")
        code, _, err = run_cli("--source", self.src, "--project", self.project, "--conf", "1.5", "--quiet")
        self.assertEqual(code, 2)
        self.assertIn("conf", err)


if __name__ == "__main__":
    unittest.main()
