"""Evaluate the WOAD exp72 checkpoint on a labelled IR + depth dataset (YOLO label format).

Follows the original validation pipeline (original/.../val.py and utils/datasets.py, rect=False as in
exp72/opt.yaml):
  * preprocessing: woad.preprocess.prepare_pair (IR resize+letterbox, depth medianBlur(3)+letterbox, 640x640)
  * NMS: original non_max_suppression, conf_thres=0.001, iou_thres=0.6, multi_label=True, max_det=300
  * matching: original process_batch at IoU 0.50:0.05:0.95, boxes in native IR pixel coordinates
  * metrics: original ap_per_class (101-point interpolated AP; P/R at the max mean-F1 confidence)
  * labels: original verify_image_label rules - 5 columns, normalised coordinates in [0, 1],
    duplicate rows removed, a label file breaking the rules excludes the image (reported).
Differences from the original run (documented, not hidden): FP32 on CPU instead of FP16 on CUDA,
batch forward size is irrelevant for the metrics (no rect batching).

Class mapping: dataset class ids and model class ids need not agree. --class-map "0:person,2:Ebike"
evaluates dataset class 0 as model class 'person' and dataset class 2 as model 'Ebike'. Ground truth of
unmapped dataset classes is ignored and detections of unmapped model classes are discarded.

Example:
  python tools/evaluate.py --split-root ../datasets/VOCdetiv_data/VOCdevkit_nc_10 --split val ^
      --class-map 0:person --dataset-names person,box,bike --name nc10_val_person
"""
import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from woad import __version__  # noqa: E402
from woad.metrics import IOUV, ConfusionMatrix, ap_per_class, process_batch  # noqa: E402
from woad.model_loader import DEFAULT_WEIGHTS, load_model  # noqa: E402
from woad.ops import clip_coords, non_max_suppression, scale_coords, xywh2xyxy  # noqa: E402
from woad.pairing import pair_directories  # noqa: E402
from woad.preprocess import IMG_SIZE, load_pair  # noqa: E402


def parse_class_map(text, model_names):
    """'0:person,2:1' -> {dataset_id: model_id}."""
    lowered = [n.lower() for n in model_names]
    mapping = {}
    for item in text.split(","):
        ds, _, md = item.strip().partition(":")
        if not ds.strip().isdigit() or not md.strip():
            raise ValueError(f"bad --class-map entry '{item}', expected DATASET_ID:MODEL_CLASS")
        md = md.strip()
        m = int(md) if md.isdigit() else (lowered.index(md.lower()) if md.lower() in lowered else None)
        if m is None or not 0 <= m < len(model_names):
            raise ValueError(f"unknown model class '{md}' in --class-map; model classes: {model_names}")
        if int(ds) in mapping or m in mapping.values():
            raise ValueError(f"--class-map must be one-to-one: '{text}'")
        mapping[int(ds)] = m
    return mapping


def read_labels(path):
    """Returns (labels Nx5 float [cls, x, y, w, h] normalised, problem or None)."""
    if not path.exists():
        return np.zeros((0, 5), np.float32), None  # missing label file = background image (as original)
    rows = [line.split() for line in path.read_text().strip().splitlines() if line.strip()]
    if not rows:
        return np.zeros((0, 5), np.float32), None
    if any(len(r) != 5 for r in rows):
        return None, "label rows must have 5 columns (segments not supported)"
    lb = np.array(rows, dtype=np.float32)
    if (lb < 0).any():
        return None, "negative label values"
    if (lb[:, 1:] > 1).any():
        return None, "non-normalised or out of bounds coordinates"
    if lb[:, 0].astype(int).astype(np.float32).tolist() != lb[:, 0].tolist():
        return None, "non-integer class id"
    _, idx = np.unique(lb, axis=0, return_index=True)
    return lb[np.sort(idx)], None


def evaluate(images, clouds, labels, class_map, model, names, dataset_names, conf_thres, iou_thres, max_det,
             batch_size, log):
    pairing = pair_directories(images, clouds, match="name")
    if not pairing.complete:
        raise SystemExit("unpaired images/depth files:\n" + pairing.describe_missing())
    label_stems = {p.stem for p in labels.glob("*.txt")}
    img_stems = [ir.stem for ir, _ in pairing.pairs]
    report = {"pairs": len(pairing.pairs), "labels_without_image": sorted(label_stems - set(img_stems)),
              "images_without_label_file": sorted(set(img_stems) - label_stems), "excluded_images": {}}

    device = next(model.parameters()).device
    eval_model_classes = sorted(class_map.values())
    model_to_ds = {m: d for d, m in class_map.items()}
    cm = ConfusionMatrix(nc=len(names))
    stats, per_image, gt_ignored = [], [], {}
    t_fwd = 0.0
    items = []
    for ir_p, dp_p in pairing.pairs:
        lb, problem = read_labels(labels / (ir_p.stem + ".txt"))
        if problem:
            report["excluded_images"][ir_p.name] = problem
            continue
        items.append((ir_p, dp_p, lb))

    for b0 in range(0, len(items), batch_size):
        batch = items[b0:b0 + batch_size]
        prepared = [load_pair(ir_p, dp_p) for ir_p, dp_p, _ in batch]
        ir = torch.cat([p.ir for p in prepared]).to(device)
        dp = torch.cat([p.depth for p in prepared]).to(device)
        t0 = time.perf_counter()
        with torch.inference_mode():
            pred = model(ir, dp)[0]
        t_fwd += time.perf_counter() - t0
        out = non_max_suppression(pred, conf_thres, iou_thres, multi_label=True, max_det=max_det)
        for (ir_p, _, lb), prep, det in zip(batch, prepared, out):
            h0, w0 = prep.ir_original.shape[:2]
            det = det.clone()
            det[:, :4] = scale_coords((IMG_SIZE, IMG_SIZE), det[:, :4], (h0, w0))
            # ground truth in native pixels (equivalent to the original letterbox + scale_coords round trip)
            gt = torch.from_numpy(lb).clone()
            gt_boxes = xywh2xyxy(gt[:, 1:5]) * torch.tensor([w0, h0, w0, h0])
            clip_coords(gt_boxes, (h0, w0))
            ds_cls = gt[:, 0].long().tolist()
            for c in ds_cls:
                if c not in class_map:
                    gt_ignored[c] = gt_ignored.get(c, 0) + 1
            keep_gt = torch.tensor([c in class_map for c in ds_cls], dtype=torch.bool)
            gt_model = torch.cat([torch.tensor([[class_map[c]] for c in ds_cls if c in class_map], dtype=torch.float32)
                                  .reshape(-1, 1), gt_boxes[keep_gt]], 1)
            det = det[torch.isin(det[:, 5].long(), torch.tensor(eval_model_classes))]
            tcls = gt_model[:, 0].tolist()
            if len(det) == 0:
                if len(gt_model):
                    stats.append((torch.zeros(0, len(IOUV), dtype=torch.bool), torch.Tensor(), torch.Tensor(), tcls))
            else:
                if len(gt_model):
                    correct = process_batch(det, gt_model, IOUV)
                    cm.process_batch(det, gt_model)
                else:
                    correct = torch.zeros(det.shape[0], len(IOUV), dtype=torch.bool)
                stats.append((correct, det[:, 4], det[:, 5], tcls))
            per_image.append({"image": ir_p.name, "width": w0, "height": h0,
                              "ground_truth": [{"dataset_class": int(c), "model_class": names[int(m)],
                                                "box_xyxy": [round(v, 2) for v in bb]}
                                               for c, m, bb in zip([d for d in ds_cls if d in class_map],
                                                                   gt_model[:, 0].long().tolist(),
                                                                   gt_model[:, 1:].tolist())],
                              "detections_conf_ge_0.25": [{"model_class": names[int(c)], "confidence": round(cf, 4),
                                                           "box_xyxy": [round(v, 2) for v in (x1, y1, x2, y2)]}
                                                          for x1, y1, x2, y2, cf, c in det.tolist() if cf >= 0.25]})
        log(f"  {min(b0 + batch_size, len(items))}/{len(items)} images")

    seen = len(items)
    report["images_evaluated"] = seen
    report["ignored_ground_truth_by_dataset_class"] = {
        f"{c} ({dataset_names[c] if dataset_names and c < len(dataset_names) else '?'})": n
        for c, n in sorted(gt_ignored.items())}
    report["forward_ms_per_image"] = round(t_fwd / max(seen, 1) * 1000, 1)

    st = [torch.cat(x, 0).numpy() if i < 3 else np.array(sum(x, []), dtype=np.float64)
          for i, x in enumerate(zip(*stats))] if stats else None
    classes_out = []
    if st is not None and len(st[3]):
        m = ap_per_class(*st)
        for i, c in enumerate(m["classes"]):
            c = int(c)
            classes_out.append({
                "model_class": names[c], "dataset_class": model_to_ds[c],
                "dataset_class_name": (dataset_names[model_to_ds[c]] if dataset_names else None),
                "instances": int(m["nt"][i]), "precision": float(m["p"][i]), "recall": float(m["r"][i]),
                "AP50": float(m["ap"][i, 0]), "AP50_95": float(m["ap"][i].mean())})
        summary = {"precision": float(m["p"].mean()), "recall": float(m["r"].mean()),
                   "mAP50": float(m["ap"][:, 0].mean()), "mAP50_95": float(m["ap"].mean()),
                   "instances": int(m["nt"].sum()), "operating_conf": m["best_conf"]}
        pr = {"recall_grid": m["px"].round(4).tolist(),
              "precision_at_iou50": {names[int(c)]: m["pr_curves"][i].round(4).tolist()
                                     for i, c in enumerate(m["classes"])}}
    else:
        summary, pr = {"note": "no ground truth for the mapped classes"}, {}
    cm_names = names + ["background"]
    confusion = {"rows_predicted_cols_true": cm_names, "matrix": cm.matrix.astype(int).tolist(),
                 "conf": cm.conf, "iou": cm.iou_thres}
    return summary, classes_out, report, per_image, pr, confusion


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--split-root", type=Path, help="dataset root with images/, clouds/, labels/ sub-folders")
    src.add_argument("--images", type=Path, help="IR image folder (use with --clouds and --labels)")
    ap.add_argument("--split", default="val", help="split name under --split-root (default: val)")
    ap.add_argument("--clouds", type=Path)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--class-map", required=True, help="DATASET_ID:MODEL_CLASS[,...], e.g. 0:person,2:Ebike")
    ap.add_argument("--dataset-names", default="", help="comma-separated dataset class names (for the report)")
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--conf", type=float, default=0.001)
    ap.add_argument("--iou", type=float, default=0.6)
    ap.add_argument("--max-det", type=int, default=300)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--project", type=Path, default=ROOT / "outputs" / "eval")
    ap.add_argument("--name", default="eval")
    ap.add_argument("--note", default="", help="free text stored in metrics.json (e.g. dataset caveats)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.split_root:
        images, clouds, labels = (a.split_root / d / a.split for d in ("images", "clouds", "labels"))
    else:
        if not (a.clouds and a.labels):
            ap.error("--images requires --clouds and --labels")
        images, clouds, labels = a.images, a.clouds, a.labels
    for d in (images, clouds, labels):
        if not d.is_dir():
            ap.error(f"not a directory: {d}")
    if a.conf > 0.001:
        print(f"WARNING: conf {a.conf} > 0.001 under-estimates mAP (the original val.py uses 0.001)")

    log = (lambda *x: None) if a.quiet else print
    model, info = load_model(a.weights, a.device)
    names = list(info["names"])
    class_map = parse_class_map(a.class_map, names)
    dataset_names = [s.strip() for s in a.dataset_names.split(",")] if a.dataset_names else []

    run = a.project / a.name
    k = 2
    while run.exists():
        run = a.project / f"{a.name}{k}"
        k += 1

    log(f"Evaluating {info['weights']} on {images}  class map {class_map}")
    t0 = time.time()
    summary, classes_out, report, per_image, pr, confusion = evaluate(
        images, clouds, labels, class_map, model, names, dataset_names, a.conf, a.iou, a.max_det,
        a.batch_size, log)

    label_digest = hashlib.sha256()
    for p in sorted(labels.glob("*.txt")):
        label_digest.update(p.name.encode() + b"\0" + p.read_bytes())
    meta = {
        "tool": "tools/evaluate.py", "woad_version": __version__,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"), "elapsed_s": round(time.time() - t0, 1),
        "model": {"weights": info["weights"], "sha256": info["sha256"], "names": names},
        "dataset": {"images": str(images.resolve()), "clouds": str(clouds.resolve()), "labels": str(labels.resolve()),
                    "labels_sha256": label_digest.hexdigest(), "dataset_names": dataset_names,
                    "class_map": {f"{d}" + (f" ({dataset_names[d]})" if d < len(dataset_names) else ""): names[m]
                                  for d, m in class_map.items()}},
        "settings": {"img_size": IMG_SIZE, "conf_thres": a.conf, "iou_thres": a.iou, "max_det": a.max_det,
                     "multi_label": True, "precision": "fp32", "device": str(next(model.parameters()).device),
                     "ap_method": "101-point interpolated (original utils/metrics.py)"},
        "environment": {"python": platform.python_version(), "torch": torch.__version__,
                        "numpy": np.__version__, "opencv": cv2.__version__, "platform": platform.platform()},
        "note": a.note,
        "summary": summary, "per_class": classes_out, "data_report": report, "confusion_matrix": confusion,
    }
    run.mkdir(parents=True)
    (run / "metrics.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (run / "per_image.json").write_text(json.dumps(per_image, indent=1), encoding="utf-8")
    (run / "pr_curve.json").write_text(json.dumps(pr), encoding="utf-8")

    print(f"{'class':>12} {'images':>7} {'inst':>6} {'P':>7} {'R':>7} {'AP50':>7} {'AP50-95':>8}")
    if classes_out:
        print(f"{'all':>12} {report['images_evaluated']:>7} {summary['instances']:>6} {summary['precision']:7.3f} "
              f"{summary['recall']:7.3f} {summary['mAP50']:7.3f} {summary['mAP50_95']:8.3f}")
        for c in classes_out:
            print(f"{c['model_class']:>12} {report['images_evaluated']:>7} {c['instances']:>6} {c['precision']:7.3f} "
                  f"{c['recall']:7.3f} {c['AP50']:7.3f} {c['AP50_95']:8.3f}")
    else:
        print(summary["note"])
    if report["excluded_images"]:
        print(f"excluded {len(report['excluded_images'])} images with invalid labels (see metrics.json)")
    print(f"results: {run}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
