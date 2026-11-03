#!/usr/bin/env python
"""WOAD cross-modal obstacle detection (IR + colour-mapped depth) - command line interface.

Input modes (choose one):
  --ir FILE --depth FILE            a single IR/depth pair
  --ir-dir DIR --depth-dir DIR      two folders, paired by filename
  --source DIR                      a folder containing ir/ and depth/ sub-folders

Outputs (in a new, auto-incremented run folder under --project, never overwritten):
  annotated/<stem>.jpg   IR | depth side-by-side, boxes drawn on both
  json/<stem>.json       per-pair detections in original IR pixel coordinates (xyxy)
  results.json           run metadata (model hash, settings, versions) + all detections

Examples:
  python woad_detect.py --source demo_data/reconstructed_val
  python woad_detect.py --ir a/ir/0001.png --depth a/depth/0001.png --conf 0.4
  python woad_detect.py --ir-dir data/ir --depth-dir data/depth --match stem --skip-unpaired
"""
import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
import torchvision  # noqa: E402

from woad import __version__  # noqa: E402
from woad.detector import WOADDetector  # noqa: E402
from woad.model_loader import DEFAULT_WEIGHTS, CheckpointError  # noqa: E402
from woad.pairing import PairingError, pair_directories, resolve_source_root  # noqa: E402
from woad.preprocess import InputImageError  # noqa: E402
from woad.visualize import draw_detections, side_by_side  # noqa: E402


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("input")
    src.add_argument("--ir", help="single IR image")
    src.add_argument("--depth", help="single colour-mapped depth image (used with --ir)")
    src.add_argument("--ir-dir", help="folder of IR images")
    src.add_argument("--depth-dir", help="folder of depth images (used with --ir-dir)")
    src.add_argument("--source", help="folder containing ir/ and depth/ sub-folders")
    src.add_argument("--match", choices=["name", "stem"], default="name",
                     help="pair by exact filename (default, as in training) or by filename stem")
    src.add_argument("--skip-unpaired", action="store_true",
                     help="warn about and skip unpaired images instead of aborting")
    m = ap.add_argument_group("model")
    m.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    m.add_argument("--device", default="cpu", help="cpu | cuda | 0 | auto  (default: cpu)")
    m.add_argument("--conf", type=float, default=0.25, help="confidence threshold (default 0.25)")
    m.add_argument("--iou", type=float, default=0.45, help="NMS IoU threshold (default 0.45)")
    m.add_argument("--max-det", type=int, default=300)
    m.add_argument("--classes", nargs="+", help="keep only these classes (names or ids)")
    m.add_argument("--agnostic-nms", action="store_true")
    o = ap.add_argument_group("output")
    o.add_argument("--project", default=str(ROOT / "outputs"), help="parent folder for runs")
    o.add_argument("--name", default="detect", help="run folder name (auto-incremented if it exists)")
    o.add_argument("--no-images", action="store_true", help="do not save annotated images")
    o.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    single = a.ir or a.depth
    folders = a.ir_dir or a.depth_dir
    modes = sum(bool(x) for x in (single, folders, a.source))
    if modes != 1:
        ap.error("choose exactly one input mode: --ir/--depth, --ir-dir/--depth-dir, or --source")
    if single and not (a.ir and a.depth):
        ap.error("--ir and --depth must be given together")
    if folders and not (a.ir_dir and a.depth_dir):
        ap.error("--ir-dir and --depth-dir must be given together")
    return a


def collect_pairs(a, log):
    if a.ir:
        return [(Path(a.ir), Path(a.depth))]
    ir_dir, depth_dir = (resolve_source_root(a.source) if a.source else (a.ir_dir, a.depth_dir))
    res = pair_directories(ir_dir, depth_dir, a.match)
    if not res.complete:
        msg = "Unpaired images found:\n" + res.describe_missing()
        if not a.skip_unpaired:
            raise PairingError(msg + "\nFix the file names, or re-run with --skip-unpaired "
                                     "(and/or --match stem if only the extensions differ).")
        log("WARNING: " + msg + "\nSkipping them (--skip-unpaired).")
    if not res.pairs:
        raise PairingError(f"no IR/depth pairs found (IR: {ir_dir}, depth: {depth_dir})")
    return res.pairs


def increment_dir(project, name):
    project = Path(project)
    d = project / name
    n = 2
    while d.exists():
        d = project / f"{name}{n}"
        n += 1
    return d


def main(argv=None):
    a = parse_args(argv)
    log = (lambda *x: None) if a.quiet else (lambda *x: print(*x, flush=True))
    try:
        pairs = collect_pairs(a, log)
        det = WOADDetector(a.weights, a.device, a.conf, a.iou, a.max_det, a.classes, a.agnostic_nms)
    except (PairingError, CheckpointError, ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    run_dir = increment_dir(a.project, a.name)
    (run_dir / "json").mkdir(parents=True)
    if not a.no_images:
        (run_dir / "annotated").mkdir()
    log(f"Model: {det.info['weights']} ({det.info['sha256'][:12]}..., classes {det.names}, {det.info['device']})")
    log(f"{len(pairs)} pair(s) -> {run_dir}")

    results, failures, t_start = [], [], time.perf_counter()
    for k, (ir_p, dp_p) in enumerate(pairs, 1):
        try:
            res, prep = det.detect_files(ir_p, dp_p)
        except InputImageError as e:
            failures.append({"ir_path": str(ir_p), "depth_path": str(dp_p), "error": str(e)})
            log(f"[{k}/{len(pairs)}] ERROR {ir_p.name}: {e}")
            continue
        stem = ir_p.stem
        (run_dir / "json" / f"{stem}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
        if not a.no_images:
            ir_vis = draw_detections(prep.ir_original, res["detections"])
            # Boxes are in IR coordinates; draw them on depth only when the resolutions agree.
            dp_vis = (draw_detections(prep.depth_original, res["detections"]) if not prep.size_mismatch
                      else prep.depth_original)
            banner = f"{ir_p.name} | {len(res['detections'])} detection(s) | conf>={a.conf}"
            cv2.imwrite(str(run_dir / "annotated" / f"{stem}.jpg"), side_by_side(ir_vis, dp_vis, banner))
        results.append(res)
        if prep.size_mismatch:
            log(f"  note: {ir_p.name}: IR and depth resolutions differ; boxes are in IR coordinates")
        summary = ", ".join(f"{d['class_name']} {d['confidence']:.2f}" for d in res["detections"]) or "none"
        log(f"[{k}/{len(pairs)}] {ir_p.name}: {summary}  ({res['timing_ms']['inference']:.0f} ms)")

    elapsed = time.perf_counter() - t_start
    counts = {}
    for r in results:
        for d in r["detections"]:
            counts[d["class_name"]] = counts.get(d["class_name"], 0) + 1
    meta = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "woad_version": __version__,
        "model": det.info,
        "settings": det.settings(),
        "environment": {"python": platform.python_version(), "torch": torch.__version__,
                        "torchvision": torchvision.__version__, "opencv": cv2.__version__,
                        "numpy": np.__version__, "platform": platform.platform()},
        "summary": {"pairs": len(pairs), "processed": len(results), "failed": len(failures),
                    "detections_per_class": counts, "elapsed_s": round(elapsed, 2)},
        "failures": failures,
        "results": results,
    }
    (run_dir / "results.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log(f"Done: {len(results)} processed, {len(failures)} failed, detections {counts or '{}'}, "
        f"{elapsed:.1f}s. Results: {run_dir}")
    return 1 if failures and not results else 0


if __name__ == "__main__":
    sys.exit(main())
