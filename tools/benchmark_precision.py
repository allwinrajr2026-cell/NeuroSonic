"""RF-DETR Nano FP32 vs FP16 (not used by the app): person quality on the 365-image near-IR validation set and
latency at 320 x 240 (the phone frame size) both back-to-back and paced at 5 frames/s.

Pacing matters: at 5 frames/s the laptop GPU drops to a low power state between frames, so per-frame latency is
higher than in a back-to-back benchmark. Same weights and code path as the app (rfdetr.RFDETRNano, local weights).

    ..\\.venv-gpu\\Scripts\\python tools\\benchmark_precision.py --out outputs\\benchmarks\\precision\\results.json
"""
import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from benchmark_detectors import SEQ, evaluate_quality  # noqa: E402
from neurosonic.detectors import find_rfdetr_weights  # noqa: E402


class Wrapped:
    """predict(bgr) -> boxes, scores, names, as benchmark_detectors.evaluate_quality expects."""

    def __init__(self, dtype):
        from PIL import Image
        from rfdetr import RFDETRNano
        from rfdetr.assets.coco_classes import COCO_CLASSES
        self.Image, self.names = Image, COCO_CLASSES
        self.m = RFDETRNano(device="cuda", pretrain_weights=str(find_rfdetr_weights()))
        self.precision = "fp32"
        if dtype == "fp16":
            self.m.inference(compile=False, dtype=torch.float16)
            self.precision = "fp16"

    def predict(self, bgr, threshold=0.001):
        d = self.m.predict(self.Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)), threshold=threshold)
        return (np.asarray(d.xyxy, np.float32), np.asarray(d.confidence, np.float32),
                [self.names.get(int(c), str(c)) if isinstance(self.names, dict) else self.names[int(c)]
                 for c in d.class_id])


def gpu_clock():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=pstate,clocks.sm", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return out
    except Exception:  # noqa: BLE001
        return None


def speed(det, frames, period):
    lat, clocks = [], []
    for i, im in enumerate(frames):
        t = time.perf_counter()
        det.predict(im, threshold=0.40)
        torch.cuda.synchronize()
        lat.append((time.perf_counter() - t) * 1000)
        if period and i % 20 == 10:
            clocks.append(gpu_clock())
        if period:
            time.sleep(max(0.0, period - (time.perf_counter() - t)))
    lat = sorted(lat[10:])
    return {"frames": len(lat), "median_ms": round(statistics.median(lat), 1),
            "p90_ms": round(lat[int(0.9 * (len(lat) - 1))], 1), "gpu_pstate_clock_samples": clocks}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=110)
    ap.add_argument("--out", type=Path, default=ROOT / "outputs" / "benchmarks" / "precision" / "results.json")
    a = ap.parse_args()
    ims = [cv2.resize(cv2.imread(str(p)), (320, 240)) for p in sorted(SEQ.glob("*.png"))[:a.frames]]
    res = {"gpu": torch.cuda.get_device_name(0), "torch": torch.__version__, "frame_size": "320x240",
           "started": time.strftime("%Y-%m-%d %H:%M:%S"), "runs": []}
    for dtype in ("fp32", "fp16"):
        det = Wrapped(dtype)
        for im in ims[:10]:
            det.predict(im)
        r = {"precision": det.precision,
             "quality_vocdetiv_val": evaluate_quality(det),
             "latency_back_to_back": speed(det, ims, 0),
             "latency_paced_5fps": speed(det, ims, 0.2)}
        print(json.dumps(r), flush=True)
        res["runs"].append(r)
        del det
        torch.cuda.empty_cache()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("wrote", a.out)


if __name__ == "__main__":
    main()
