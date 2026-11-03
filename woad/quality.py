"""Input-quality check: is a frame similar enough to the training data for detections to mean anything?

Thresholds (calibrated 2026-11-02, see docs/EVALUATION.md section 8 and docs/STAGE2_ALERTS.md):
  per-frame IR grey mean / standard deviation
                           OK        WARN                         UNUSABLE
  rule                     else      mean < 100 or std < 40       mean < 40 or std < 10
  detec_test (600)         100 %     0 %                          0 %
  exp72 val recon (187)    100 %     0 %                          0 %
  labelled VOCdetiv (1651) 89.4 %    7.4 %                        3.2 %
  raw CS30 recording (501) 1.4 %     56.1 %                       42.5 %
The brightness experiment showed that darkening training-like frames to the recording's level removes ~73 %
of detections, and that dark/flat frames produce false "person" alarms. These rules are a coarse guard,
not a guarantee of correct detections: frames that pass can still be out of distribution.

Depth: a frame whose colour-depth image is almost entirely invalid (black) is UNUSABLE (training-type data
has at most ~86 % invalid pixels). IR/depth size mismatch is a WARN.
"""
from dataclasses import dataclass, field

import cv2
import numpy as np

OK, WARN, UNUSABLE = "ok", "warn", "unusable"
_RANK = {OK: 0, WARN: 1, UNUSABLE: 2}


@dataclass
class QualityThresholds:
    warn_ir_mean: float = 100.0
    warn_ir_std: float = 40.0
    unusable_ir_mean: float = 40.0
    unusable_ir_std: float = 10.0
    unusable_depth_invalid: float = 0.95


@dataclass
class QualityReport:
    status: str
    reasons: list = field(default_factory=list)
    ir_mean: float = None
    ir_std: float = None
    depth_invalid: float = None

    def as_dict(self):
        return {"status": self.status, "reasons": self.reasons,
                "ir_mean": None if self.ir_mean is None else round(self.ir_mean, 1),
                "ir_std": None if self.ir_std is None else round(self.ir_std, 1),
                "depth_invalid": None if self.depth_invalid is None else round(self.depth_invalid, 3)}


class InputQualityChecker:
    def __init__(self, thresholds=None):
        self.t = thresholds or QualityThresholds()

    def check(self, ir_bgr, depth_bgr):
        if ir_bgr is None or depth_bgr is None:
            return QualityReport(UNUSABLE, ["image could not be read"])
        gray = cv2.cvtColor(ir_bgr, cv2.COLOR_BGR2GRAY) if ir_bgr.ndim == 3 else ir_bgr
        mean, std = float(gray.mean()), float(gray.std())
        invalid = float((depth_bgr.max(axis=2) == 0).mean()) if depth_bgr.ndim == 3 else float((depth_bgr == 0).mean())
        status, reasons = OK, []

        def flag(level, reason):
            nonlocal status
            reasons.append(reason)
            if _RANK[level] > _RANK[status]:
                status = level

        t = self.t
        if mean < t.unusable_ir_mean:
            flag(UNUSABLE, f"IR image too dark (mean {mean:.0f})")
        elif mean < t.warn_ir_mean:
            flag(WARN, f"IR image darker than training data (mean {mean:.0f})")
        if std < t.unusable_ir_std:
            flag(UNUSABLE, f"IR image has almost no contrast (std {std:.0f})")
        elif std < t.warn_ir_std:
            flag(WARN, f"IR image contrast lower than training data (std {std:.0f})")
        if invalid > t.unusable_depth_invalid:
            flag(UNUSABLE, f"depth image almost empty ({invalid:.0%} invalid)")
        if gray.shape[:2] != depth_bgr.shape[:2]:
            flag(WARN, "IR and depth sizes differ")
        return QualityReport(status, reasons, mean, std, invalid)
