"""(Re)generate tests/golden_detections.json - the detection regression fixture.

Runs the current pipeline (CPU, conf 0.25, iou 0.45) on the 16 reconstructed batch-0 frames
and stores the detections. Only regenerate after a deliberate, reviewed change to the pipeline.

Provenance: on these frames the pipeline was manually cross-checked against the predictions
saved during training (runs/train/exp72/val_lidar batch0_pred.jpg): 13 of 16 frames agree in
class and location; index 0 (person, training conf 0.9) is missed (0.15) after overlay removal;
index 1 (training: one Ebike at 0.3) scores below 0.25 here; index 11 has an extra Ebike that
matches a ground-truth box the training-time plot did not show. See README "Verification evidence".
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from woad.detector import WOADDetector  # noqa: E402

DEMO = ROOT / "demo_data" / "reconstructed_val"
OUT = ROOT / "tests" / "golden_detections.json"
FRAMES = [f"recon_b00_i{i:02d}.png" for i in range(16)]


def main():
    det = WOADDetector(device="cpu", conf_thres=0.25, iou_thres=0.45)
    golden = {"settings": det.settings(), "weights_sha256": det.info["sha256"], "frames": {}}
    for f in FRAMES:
        res, _ = det.detect_files(DEMO / "ir" / f, DEMO / "depth" / f)
        golden["frames"][f] = res["detections"]
    OUT.write_text(json.dumps(golden, indent=2), encoding="utf-8")
    print(f"wrote {OUT} ({sum(len(v) for v in golden['frames'].values())} detections)")


if __name__ == "__main__":
    main()
