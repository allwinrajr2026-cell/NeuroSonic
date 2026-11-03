"""Experiment: does IR brightness/contrast explain the detector's failure on the raw CS30 recording?

Not part of the product pipeline. Only the IR stream is transformed; depth is unchanged.

IR transforms (all 8-bit grey -> 8-bit grey):
  raw        unchanged
  gain       linear gain so the frame mean becomes REF_MEAN (clipped)
  stretch    per-frame percentile stretch: p1 -> 0, p99.5 -> 255
  histmatch  per-frame histogram matching to the pooled reference IR histogram
  gamma      gamma 0.5 (brightens shadows)

Part A - sensor recording (test1730450780): detections per transform (no labels; inspect visually).
Part B - controlled test on detec_test: darken frames to the recording's histogram ("dark"), then apply
         each transform. Reference = detections on the original frames. Reported: share of reference
         detections recovered (same class, IoU >= 0.5) and the number of extra detections.

Usage:
  python experiments/ir_brightness_test.py --recording ../datasets/test1730450780_paired ^
      --reference-ir ../datasets/detec_test/detec_test/ir --reference-depth ../datasets/detec_test/detec_test/pointcloud
"""
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from woad.detector import WOADDetector  # noqa: E402

TRANSFORMS = ("raw", "gain", "stretch", "histmatch", "gamma")


def pooled_cdf(paths):
    hist = np.zeros(256, np.float64)
    for p in paths:
        hist += np.bincount(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE).ravel(), minlength=256)
    cdf = hist.cumsum()
    return cdf / cdf[-1]


def match_to_cdf(gray, ref_cdf):
    src_cdf = np.bincount(gray.ravel(), minlength=256).cumsum().astype(np.float64)
    src_cdf /= src_cdf[-1]
    lut = np.clip(np.searchsorted(ref_cdf, src_cdf), 0, 255).astype(np.uint8)
    return lut[gray]


def transform(gray, name, ref_cdf, ref_mean):
    if name == "raw":
        return gray
    if name == "gain":
        return np.clip(gray.astype(np.float32) * (ref_mean / max(gray.mean(), 1e-3)), 0, 255).astype(np.uint8)
    if name == "stretch":
        lo, hi = np.percentile(gray, (1, 99.5))
        return np.clip((gray.astype(np.float32) - lo) * 255.0 / max(hi - lo, 1.0), 0, 255).astype(np.uint8)
    if name == "histmatch":
        return match_to_cdf(gray, ref_cdf)
    if name == "gamma":
        lut = (255.0 * (np.arange(256) / 255.0) ** 0.5).round().astype(np.uint8)
        return lut[gray]
    raise ValueError(name)


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def agreement(ref, got):
    """Greedy match by class and IoU >= 0.5. Returns (#ref matched, #extra in got)."""
    used, matched = set(), 0
    for r in sorted(ref, key=lambda d: -d["confidence"]):
        best, bj = 0.5, None
        for j, g in enumerate(got):
            if j not in used and g["class_name"] == r["class_name"]:
                v = iou(r["box_xyxy"], g["box_xyxy"])
                if v >= best:
                    best, bj = v, j
        if bj is not None:
            used.add(bj)
            matched += 1
    return matched, len(got) - len(used)


def stats(gray):
    return {"mean": float(gray.mean()), "std": float(gray.std())}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recording", type=Path, required=True, help="folder with ir/ and depth/ (paired by name)")
    ap.add_argument("--reference-ir", type=Path, required=True, help="training-like IR frames (reference histogram)")
    ap.add_argument("--reference-depth", type=Path, required=True)
    ap.add_argument("--controlled-step", type=int, default=3, help="use every n-th reference frame in part B")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs" / "experiments" / "ir_brightness")
    a = ap.parse_args(argv)

    out = a.out
    k = 2
    while out.exists():
        out = a.out.with_name(f"{a.out.name}{k}")
        k += 1
    (out / "frames").mkdir(parents=True)

    det = WOADDetector(conf_thres=0.25)
    ref_paths = sorted(a.reference_ir.glob("*.png"))
    rec_ir = sorted((a.recording / "ir").glob("*.png"))
    ref_cdf = pooled_cdf(ref_paths)
    ref_mean = float(np.mean([cv2.imread(str(p), 0).mean() for p in ref_paths[::5]]))
    rec_cdf = pooled_cdf(rec_ir)

    # ---- Part A: recording
    t0 = time.time()
    part_a = {t: [] for t in TRANSFORMS}
    for p in rec_ir:
        gray = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        depth = cv2.imread(str(a.recording / "depth" / p.name))
        for t in TRANSFORMS:
            g = transform(gray, t, ref_cdf, ref_mean)
            res = det.detect_arrays(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), depth)
            part_a[t].append({"frame": p.name, "ir_stats": stats(g), "detections": res["detections"]})
    summary_a = {}
    for t in TRANSFORMS:
        dets = [d for r in part_a[t] for d in r["detections"]]
        summary_a[t] = {
            "ir_mean": round(float(np.mean([r["ir_stats"]["mean"] for r in part_a[t]])), 1),
            "ir_std": round(float(np.mean([r["ir_stats"]["std"] for r in part_a[t]])), 1),
            "frames_with_detections": sum(1 for r in part_a[t] if r["detections"]),
            "detections": len(dets),
            "by_class": {c: sum(1 for d in dets if d["class_name"] == c) for c in det.names},
        }
    print(f"Part A ({len(rec_ir)} recording frames, {time.time() - t0:.0f}s)")
    for t, s in summary_a.items():
        print(f"  {t:10s} IR mean {s['ir_mean']:6.1f} std {s['ir_std']:5.1f} | frames w/ det {s['frames_with_detections']:4d} "
              f"| dets {s['detections']:4d} {s['by_class']}")

    # ---- Part B: controlled darkening of training-like frames
    t0 = time.time()
    b_paths = ref_paths[::a.controlled_step]
    totals = {t: {"matched": 0, "extra": 0} for t in ("original",) + tuple("dark+" + t for t in TRANSFORMS)}
    n_ref = 0
    for p in b_paths:
        gray = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        depth = cv2.imread(str(a.reference_depth / p.name))
        ref = det.detect_arrays(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), depth)["detections"]
        n_ref += len(ref)
        dark = match_to_cdf(gray, rec_cdf)
        for t in TRANSFORMS:
            g = transform(dark, t, ref_cdf, ref_mean)
            got = det.detect_arrays(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), depth)["detections"]
            m, e = agreement(ref, got)
            totals["dark+" + t]["matched"] += m
            totals["dark+" + t]["extra"] += e
    totals.pop("original")
    summary_b = {t: {"recovered": v["matched"], "of_reference": n_ref,
                     "recovered_pct": round(100.0 * v["matched"] / max(n_ref, 1), 1), "extra": v["extra"]}
                 for t, v in totals.items()}
    print(f"Part B ({len(b_paths)} detec_test frames, {n_ref} reference detections, {time.time() - t0:.0f}s)")
    for t, s in summary_b.items():
        print(f"  {t:16s} recovered {s['recovered']:4d}/{s['of_reference']} ({s['recovered_pct']:5.1f} %)  extra {s['extra']:4d}")

    (out / "results.json").write_text(json.dumps({
        "reference_ir_mean": ref_mean, "part_a_summary": summary_a, "part_b_summary": summary_b,
        "part_a_frames": part_a, "settings": det.settings()}, indent=1), encoding="utf-8")

    # frames with any detection in any transform, for visual verification
    by_frame = {}
    for t in TRANSFORMS:
        for r in part_a[t]:
            if r["detections"]:
                by_frame.setdefault(r["frame"], {})[t] = r["detections"]
    for name, per_t in by_frame.items():
        gray = cv2.imread(str(a.recording / "ir" / name), cv2.IMREAD_GRAYSCALE)
        tiles = []
        for t in TRANSFORMS:
            im = cv2.cvtColor(transform(gray, t, ref_cdf, ref_mean), cv2.COLOR_GRAY2BGR)
            for d in per_t.get(t, []):
                x1, y1, x2, y2 = map(int, d["box_xyxy"])
                cv2.rectangle(im, (x1, y1), (x2, y2), (0, 0, 255), 3)
                cv2.putText(im, f"{d['class_name']} {d['confidence']:.2f}", (x1 + 3, max(y1 + 22, 22)), 0, 0.8,
                            (0, 0, 255), 2)
            cv2.putText(im, t, (8, 470), 0, 1.0, (0, 255, 255), 2)
            tiles.append(cv2.resize(im, (320, 240)))
        cv2.imwrite(str(out / "frames" / name.replace(".png", ".jpg")), np.hstack(tiles))
    print(f"frames with detections in any transform: {len(by_frame)} -> {out / 'frames'}")
    print(f"results: {out}")


if __name__ == "__main__":
    main()
