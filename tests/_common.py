"""Shared test helpers (stdlib unittest; also runnable with pytest)."""
import functools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEMO = ROOT / "demo_data" / "reconstructed_val"
ORIGINAL_REPO = ROOT.parent / "original" / "Cross-Modal obstacle detection"
ORIGINAL_CKPT = ORIGINAL_REPO / "runs" / "train" / "exp72" / "weights" / "best.pt"
GOLDEN = ROOT / "tests" / "golden_detections.json"


def demo_available():
    return (DEMO / "ir").is_dir() and (DEMO / "depth").is_dir() and any((DEMO / "ir").glob("*.png"))


@functools.lru_cache(maxsize=1)
def detector():
    from woad.detector import WOADDetector
    return WOADDetector(device="cpu", conf_thres=0.25, iou_thres=0.45)


def demo_pair(name):
    return DEMO / "ir" / name, DEMO / "depth" / name


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
