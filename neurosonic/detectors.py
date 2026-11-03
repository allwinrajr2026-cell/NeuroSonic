"""Detector back-ends for live camera awareness, with automatic fallback (2026-11-03).

    RFDETRDetector   RF-DETR Nano (Roboflow, Apache-2.0), COCO, 384 px, on the NVIDIA GPU (CUDA). Primary when available.
    SSDLiteDetector  torchvision SSDLite320-MobileNetV3 (BSD-3), COCO, 320 px, CPU. The original detector; fallback.

Both return the same detection dicts (COCO category ids, the obstacle classes only) so everything downstream (walking
guidance, tracking, events, object description) is unchanged. `make_detector("auto")` tries RF-DETR and falls back to
SSDLite when CUDA, the rfdetr package or the local weights are missing, or when the warm-up inference fails.
`FallbackDetector` also switches to SSDLite permanently if RF-DETR fails during live inference, and re-runs the frame.
No weights are downloaded at run time: RF-DETR is only used if its checkpoint already exists locally.

Benchmark (docs/PHASE1_GPU_DETECTOR_BENCHMARK.md, laptop RTX 4050, FP32): RF-DETR Nano 21.3 ms/frame on the GPU,
person AP@0.5 0.660 vs SSDLite 0.542 on the WOAD near-IR validation images. Neither detector sees steps, kerbs, holes,
poles or walls, and neither measures distance.
"""
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
SSDLITE_WEIGHTS = ROOT / "models" / "rgb" / "ssdlite320_mobilenet_v3_large_coco-a79551df.pth"
RFDETR_WEIGHT_CANDIDATES = [ROOT / "models" / "rfdetr" / "rf-detr-nano.pth",
                            Path.home() / ".roboflow" / "models" / "rf-detr-nano.pth"]
DETECTOR_ENV = "NEUROSONIC_DETECTOR"          # auto | rfdetr | ssdlite
# While RF-DETR runs on the GPU, the CPU only does pre/post-processing. With PyTorch's default (8 threads here) the
# idle worker threads spin between frames: measured 712 % of one core at 5 frames/s vs 121 % with 2 threads, with the
# same per-frame latency (2026-11-03). The default is restored if the app falls back to SSDLite on the CPU.
GPU_MODE_CPU_THREADS = 2


class DetectorUnavailable(RuntimeError):
    pass


def _filter(boxes, scores, labels, classes, thres, scale=1.0):
    out = []
    for box, label, score in zip(boxes, labels, scores):
        label = int(label)
        if score < thres or label not in classes:
            continue
        out.append({"class_id": label, "class_name": classes[label][0], "confidence": round(float(score), 4),
                    "box_xyxy": [round(float(v) / scale, 1) for v in box]})
    return out


class SSDLiteDetector:
    name, device, input_size = "ssdlite320", "cpu", 320

    def __init__(self, classes, score_thres=0.40, max_side=320, weights=SSDLITE_WEIGHTS):
        self.classes, self.score_thres, self.max_side = classes, score_thres, max_side
        self.weights = Path(weights)
        self._model = None
        if not self.weights.exists():
            raise DetectorUnavailable(f"detector weights missing: {self.weights}")

    def _load(self):
        if self._model is None:
            from torchvision.models.detection import ssdlite320_mobilenet_v3_large
            m = ssdlite320_mobilenet_v3_large(weights=None, weights_backbone=None, num_classes=91)
            m.load_state_dict(torch.load(self.weights, map_location="cpu", weights_only=True))
            self._model = m.eval()
        return self._model

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        scale = min(1.0, self.max_side / max(h, w))
        img = cv2.resize(bgr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else bgr
        x = torch.from_numpy(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float().div(255)
        with torch.inference_mode():
            out = self._load()([x])[0]
        return _filter(out["boxes"].tolist(), out["scores"].tolist(), out["labels"].tolist(), self.classes,
                       self.score_thres, scale)


def find_rfdetr_weights():
    for p in RFDETR_WEIGHT_CANDIDATES:
        if p.exists() and p.stat().st_size > 10_000_000:
            return p
    return None


class RFDETRDetector:
    name, input_size = "rf-detr-nano", 384

    def __init__(self, classes, score_thres=0.40, device="cuda"):
        self.classes, self.score_thres, self.device = classes, score_thres, device
        if device == "cuda" and not torch.cuda.is_available():
            raise DetectorUnavailable(f"CUDA not available (torch {torch.__version__})")
        try:
            import rfdetr  # noqa: F401
        except Exception as e:  # noqa: BLE001
            raise DetectorUnavailable(f"rfdetr package not installed ({type(e).__name__})")
        weights = find_rfdetr_weights()
        if weights is None:
            raise DetectorUnavailable("RF-DETR Nano weights not found locally (no download at run time)")
        self.weights = weights
        os.environ.setdefault("HF_HUB_OFFLINE", "1")        # never fetch anything from the Hugging Face hub
        self.prev_threads = torch.get_num_threads()
        torch.set_num_threads(GPU_MODE_CPU_THREADS)
        from rfdetr import RFDETRNano
        self.model = RFDETRNano(device=device, pretrain_weights=str(weights))
        # FP16 inference (2026-11-03): at 5 frames/s the laptop GPU drops to its lowest power state (P8, ~400 MHz),
        # where FP32 took ~74 ms/frame vs ~57 ms in FP16. Person AP@0.5 on the 365-image near-IR set: 0.660 (FP16)
        # vs 0.660 (FP32), recall 0.729 both. No compilation (kept simple and robust). Falls back to FP32 if unsupported.
        self.precision = "fp32"
        try:
            self.model.inference(compile=False, dtype=torch.float16)
            self.precision = "fp16"
        except Exception:  # noqa: BLE001
            pass
        from PIL import Image
        self._Image = Image

    def detect(self, bgr):
        det = self.model.predict(self._Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)), threshold=self.score_thres)
        return _filter(np.asarray(det.xyxy).tolist(), np.asarray(det.confidence).tolist(), np.asarray(det.class_id).tolist(),
                       self.classes, self.score_thres)


class FallbackDetector:
    """Uses `primary` until it fails once at run time, then `fallback` for the rest of the process."""

    def __init__(self, primary, fallback_factory, log=print):
        self.active = primary
        self._fallback_factory = fallback_factory
        self.log = log
        self.fallback_reason = None
        self.lock = threading.Lock()

    @property
    def name(self):
        return self.active.name

    @property
    def device(self):
        return self.active.device

    @property
    def input_size(self):
        return self.active.input_size

    def detect(self, bgr):
        try:
            return self.active.detect(bgr)
        except Exception as e:  # noqa: BLE001 - any failure of the primary detector
            if isinstance(self.active, SSDLiteDetector):
                raise
            self.fallback_reason = f"{self.active.name} failed during inference ({type(e).__name__}: {str(e)[:120]})"
            self.log(f"[awareness] {self.fallback_reason}; switching to SSDLite on the CPU")
            if getattr(self.active, "prev_threads", None):
                torch.set_num_threads(self.active.prev_threads)        # SSDLite needs the CPU threads again
            self.active = self._fallback_factory()
            return self.active.detect(bgr)


def make_detector(classes, preference=None, score_thres=0.40, max_side=320, ssdlite_weights=SSDLITE_WEIGHTS, log=print):
    """-> (detector, info). preference: auto | rfdetr | ssdlite (default from $NEUROSONIC_DETECTOR, else ssdlite)."""
    pref = (preference or os.environ.get(DETECTOR_ENV) or "ssdlite").lower()
    if pref not in ("auto", "rfdetr", "ssdlite"):
        raise ValueError(f"unknown detector {pref!r} (auto, rfdetr, ssdlite)")

    def ssd():
        return SSDLiteDetector(classes, score_thres, max_side, ssdlite_weights)

    info = {"requested": pref, "fallback_reason": None}
    if pref == "ssdlite":
        return FallbackDetector(ssd(), ssd, log), info
    t = time.perf_counter()
    threads = torch.get_num_threads()
    try:
        prim = RFDETRDetector(classes, score_thres)
        prim.detect(np.zeros((240, 320, 3), np.uint8))       # warm-up: proves inference works on this machine
        info["load_ms"] = round((time.perf_counter() - t) * 1000)
        info["weights"] = str(prim.weights)
        return FallbackDetector(prim, ssd, log), info
    except Exception as e:  # noqa: BLE001
        torch.set_num_threads(threads)
        info["fallback_reason"] = f"RF-DETR unavailable: {type(e).__name__}: {str(e)[:160]}"
        log(f"[awareness] {info['fallback_reason']}; using SSDLite on the CPU")
        return FallbackDetector(ssd(), ssd, log), info
