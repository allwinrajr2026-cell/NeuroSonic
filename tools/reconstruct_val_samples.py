"""Reconstruct paired IR/depth DEMO samples from the saved exp72 validation visualisations.

!!! These are NOT the original raw dataset images. !!!
They are recovered from the JPEG mosaics YOLOv5 saved during training
(runs/train/exp72/val_batch{b}_{labels,pred}.jpg and "val_lidar batch{b}_{labels,pred}.jpg").
Degradations compared with the raw 640x480 frames:
  * downscaled 640->480 by the plotting code, JPEG-compressed, then upscaled back 480->640 here;
  * ground-truth and prediction boxes/labels were burned into the mosaics; they are removed
    here by (1) taking the same pixel from the other mosaic (labels vs pred) when that one is
    clean, else (2) OpenCV inpainting. Inpainted pixels are synthetic;
  * thin white tile borders (2 px) at the left/right edges are inpainted as well;
  * the IR result is converted to grayscale (it is single-channel content) to remove inpainting colour casts.
Use them for smoke tests and demos only - never for reporting accuracy.

Mosaic geometry (utils/plots.py::plot_images, verified): 4x4 grid, images placed column-first
(index i -> column i//4, row i%4), each 640x640 letterboxed tile resized to 480x480; the
640x480 frame content occupies tile rows 60..420. The last batch (11) holds 11 images.

Usage:
    python tools/reconstruct_val_samples.py [--src <exp72 run dir>] [--out demo_data/reconstructed_val]
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT.parent / "original" / "Cross-Modal obstacle detection" / "runs" / "train" / "exp72"
DEFAULT_OUT = ROOT / "demo_data" / "reconstructed_val"
GRID, TILE, Y0, Y1 = 4, 480, 60, 420       # 4x4 grid, 480 px tiles, content rows [60, 420)
OUT_W, OUT_H = 640, 480                    # restore original sensor frame size
CHROMA_THR = 25                            # IR is grayscale; coloured pixels are overlays


def overlay_mask(ir_mosaic_bgr):
    """Boolean mask of burned-in boxes/labels/borders, derived from the (grayscale) IR mosaic."""
    a = ir_mosaic_bgr.astype(np.int16)
    m = ((a.max(2) - a.min(2)) > CHROMA_THR).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))   # fill white text inside label tags
    m = cv2.dilate(m, np.ones((7, 7), np.uint8))                          # JPEG chroma bleed around lines
    for k in range(GRID + 1):                                             # white 2-px tile borders
        c = k * TILE
        m[:, max(c - 3, 0):c + 3] = 1
    return m.astype(bool)


def compose(lab, pred, m_lab, m_pred):
    """Prefer clean labels-mosaic pixels, then clean pred-mosaic pixels; inpaint where both are covered."""
    out = lab.copy()
    use_pred = m_lab & ~m_pred
    out[use_pred] = pred[use_pred]
    hole = (m_lab & m_pred).astype(np.uint8)
    if hole.any():
        out = cv2.inpaint(out, hole, 3, cv2.INPAINT_TELEA)
    return out, use_pred, hole.astype(bool)


def tile_slice(i):
    col, row = divmod(i, GRID)
    y, x = row * TILE, col * TILE
    return slice(y + Y0, y + Y1), slice(x, x + TILE)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--overwrite", action="store_true", help="allow writing into an existing non-empty --out")
    a = ap.parse_args(argv)
    src, out = Path(a.src), Path(a.out)
    if out.exists() and any(out.iterdir()) and not a.overwrite:
        print(f"ERROR: {out} is not empty; pass --overwrite to regenerate", file=sys.stderr)
        return 2
    (out / "ir").mkdir(parents=True, exist_ok=True)
    (out / "depth").mkdir(parents=True, exist_ok=True)

    manifest = []
    for b in range(100):
        files = {k: src / f for k, f in (("ir_lab", f"val_batch{b}_labels.jpg"), ("ir_pred", f"val_batch{b}_pred.jpg"),
                                         ("dp_lab", f"val_lidar batch{b}_labels.jpg"),
                                         ("dp_pred", f"val_lidar batch{b}_pred.jpg"))}
        if not files["ir_lab"].exists():
            break
        missing = [str(p) for p in files.values() if not p.exists()]
        if missing:
            print(f"ERROR: incomplete mosaic set for batch {b}: {missing}", file=sys.stderr)
            return 1
        im = {k: cv2.imread(str(p)) for k, p in files.items()}
        shapes = {v.shape for v in im.values()}
        if shapes != {(GRID * TILE, GRID * TILE, 3)}:
            print(f"ERROR: unexpected mosaic shape(s) {shapes} in batch {b}", file=sys.stderr)
            return 1
        m_lab, m_pred = overlay_mask(im["ir_lab"]), overlay_mask(im["ir_pred"])
        ir, ir_from_pred, ir_hole = compose(im["ir_lab"], im["ir_pred"], m_lab, m_pred)
        # The IR stream is single-channel content stored as 3 identical channels: remove inpainting colour cast.
        ir = cv2.cvtColor(cv2.cvtColor(ir, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        dp, _, _ = compose(im["dp_lab"], im["dp_pred"], m_lab, m_pred)

        for i in range(GRID * GRID):
            sy, sx = tile_slice(i)
            raw = im["ir_lab"][sy, sx]
            if raw.mean() > 250:  # unused (white) tile in a partial last batch
                continue
            name = f"recon_b{b:02d}_i{i:02d}.png"
            for img, sub in ((ir, "ir"), (dp, "depth")):
                t = cv2.resize(img[sy, sx], (OUT_W, OUT_H), interpolation=cv2.INTER_LINEAR)
                cv2.imwrite(str(out / sub / name), t, [cv2.IMWRITE_PNG_COMPRESSION, 9])
            manifest.append({
                "file": name, "batch": b, "mosaic_index": i,
                "grid_col_row": [i // GRID, i % GRID],
                "sources": {k: p.name for k, p in files.items()},
                "pct_pixels_taken_from_pred_mosaic": round(100 * float(ir_from_pred[sy, sx].mean()), 2),
                "pct_pixels_inpainted": round(100 * float(ir_hole[sy, sx].mean()), 2),
            })
        print(f"batch {b:2d}: {sum(1 for r in manifest if r['batch'] == b)} pairs")

    notice = {
        "WARNING": "RECONSTRUCTED, COMPRESSED/DEGRADED DEMO SAMPLES - NOT ORIGINAL RAW DATASET IMAGES. "
                   "Recovered from YOLOv5 validation JPEG mosaics; boxes removed by mosaic substitution and "
                   "inpainting. Use for smoke tests/demos only, never for accuracy reporting.",
        "source_run": str(src),
        "count": len(manifest),
        "frame_size": [OUT_W, OUT_H],
        "classes": ["person", "Ebike", "Car"],
        "samples": manifest,
    }
    (out / "manifest.json").write_text(json.dumps(notice, indent=2), encoding="utf-8")
    print(f"{len(manifest)} pairs written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
