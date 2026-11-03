"""High-level IR + depth detector."""
import time
from pathlib import Path

import torch

from .model_loader import DEFAULT_WEIGHTS, load_model
from .ops import non_max_suppression, scale_coords
from .preprocess import IMG_SIZE, load_pair, prepare_pair


class WOADDetector:
    """Cross-modal obstacle detector (classes: person, Ebike, Car).

    Example:
        det = WOADDetector()
        result = det.detect_files("ir/0001.png", "depth/0001.png")
    """

    def __init__(self, weights=DEFAULT_WEIGHTS, device="cpu", conf_thres=0.25, iou_thres=0.45,
                 max_det=300, classes=None, agnostic_nms=False):
        if not 0 <= conf_thres <= 1 or not 0 <= iou_thres <= 1:
            raise ValueError("conf_thres and iou_thres must be within [0, 1]")
        self.model, self.info = load_model(weights, device)
        self.device = next(self.model.parameters()).device
        self.names = self.info["names"]
        self.conf_thres, self.iou_thres, self.max_det = conf_thres, iou_thres, max_det
        self.agnostic_nms = agnostic_nms
        if classes is not None:
            classes = [self._class_id(c) for c in classes]
        self.classes = classes

    def _class_id(self, c):
        if isinstance(c, int) or (isinstance(c, str) and c.isdigit()):
            c = int(c)
            if not 0 <= c < len(self.names):
                raise ValueError(f"class id {c} out of range 0..{len(self.names) - 1}")
            return c
        lowered = [n.lower() for n in self.names]
        if c.lower() not in lowered:
            raise ValueError(f"unknown class '{c}', expected one of {self.names}")
        return lowered.index(c.lower())

    @torch.inference_mode()
    def raw_forward(self, ir, depth):
        """ir/depth: (B,3,640,640) float tensors in [0,1]. Returns raw predictions (B, 25200, 8)."""
        return self.model(ir.to(self.device), depth.to(self.device))[0]

    def detect_prepared(self, prepared):
        t0 = time.perf_counter()
        pred = self.raw_forward(prepared.ir, prepared.depth)
        t1 = time.perf_counter()
        det = non_max_suppression(pred, self.conf_thres, self.iou_thres, self.classes, self.agnostic_nms,
                                  max_det=self.max_det)[0]
        det = det.clone()
        if len(det):
            det[:, :4] = scale_coords((IMG_SIZE, IMG_SIZE), det[:, :4], prepared.ir_original.shape).round()
        t2 = time.perf_counter()
        detections = [{
            "class_id": int(c),
            "class_name": self.names[int(c)],
            "confidence": round(float(cf), 4),
            "box_xyxy": [float(x1), float(y1), float(x2), float(y2)],
        } for x1, y1, x2, y2, cf, c in det.tolist()]
        h, w = prepared.ir_original.shape[:2]
        return {
            "image_size": {"width": w, "height": h},
            "depth_size": {"width": prepared.depth_original.shape[1], "height": prepared.depth_original.shape[0]},
            "size_mismatch": prepared.size_mismatch,
            "detections": detections,
            "timing_ms": {"inference": round((t1 - t0) * 1000, 1), "nms_and_scaling": round((t2 - t1) * 1000, 1)},
        }

    def detect_arrays(self, ir_bgr, depth_bgr):
        return self.detect_prepared(prepare_pair(ir_bgr, depth_bgr))

    def detect_files(self, ir_path, depth_path):
        t0 = time.perf_counter()
        prepared = load_pair(ir_path, depth_path)
        result = self.detect_prepared(prepared)
        result["timing_ms"]["load_and_preprocess"] = round((time.perf_counter() - t0) * 1000
                                                           - sum(result["timing_ms"].values()), 1)
        result = {"ir_path": str(Path(ir_path)), "depth_path": str(Path(depth_path)), **result}
        return result, prepared

    def settings(self):
        return {"conf_thres": self.conf_thres, "iou_thres": self.iou_thres, "max_det": self.max_det,
                "classes": self.classes, "agnostic_nms": self.agnostic_nms, "img_size": IMG_SIZE}
