"""Multi-object tracking with camera-motion compensation (2026-11-03).

* estimate_camera_motion(): the phone moves with the walker, so every object shifts in the image even when it stands
  still. The global image motion between two frames is estimated from background corners (sparse Lucas-Kanade
  optical flow, OpenCV) outside the detected objects, as a similarity transform (shift, scale, rotation; RANSAC).
* ByteTracker: ByteTrack-style association (Zhang et al., "ByteTrack: Multi-Object Tracking by Associating Every
  Detection Box", ECCV 2022): confident detections are matched first, lower-confidence ones then only extend existing
  tracks; new tracks start from confident detections only. Matching is IoU against each track's box *moved by the
  camera motion*, per class. This is a small own implementation (no extra dependency), not the reference code.
* Every matched update stores the object's displacement RELATIVE TO THE BACKGROUND (observed centre minus where a
  static point would be after the camera motion), in image-width units. Downstream event rules use only this, so a
  parked car that slides across the image because the user turns does not count as "moving".
"""
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np


# ----------------------------------------------------------------------------- camera motion
@dataclass
class CameraMotion:
    ok: bool
    A: np.ndarray = None            # 2x3 similarity transform, previous frame -> current frame (pixels)
    shift: float = 0.0              # translation magnitude, fraction of image width per frame
    scale: float = 1.0
    points: int = 0
    inliers: int = 0

    def apply(self, x, y):
        if not self.ok or self.A is None:
            return x, y
        return (self.A[0, 0] * x + self.A[0, 1] * y + self.A[0, 2], self.A[1, 0] * x + self.A[1, 1] * y + self.A[1, 2])

    def as_dict(self):
        return {"ok": self.ok, "shift": round(self.shift, 4), "scale": round(self.scale, 4), "points": self.points,
                "inliers": self.inliers}


def estimate_camera_motion(prev_gray, gray, exclude_boxes=(), max_corners=150, min_inliers=12):
    """Global motion prev -> cur from background corners outside `exclude_boxes` (xyxy pixels)."""
    if prev_gray is None or gray is None or prev_gray.shape != gray.shape:
        return CameraMotion(ok=False)
    h, w = gray.shape[:2]
    mask = np.full((h, w), 255, np.uint8)
    for b in exclude_boxes:
        x1, y1, x2, y2 = (int(max(0, v)) for v in b)
        mask[y1:min(h, y2), x1:min(w, x2)] = 0
    pts = cv2.goodFeaturesToTrack(prev_gray, maxCorners=max_corners, qualityLevel=0.01, minDistance=7, mask=mask)
    if pts is None or len(pts) < min_inliers:
        return CameraMotion(ok=False, points=0 if pts is None else len(pts))
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, pts, None, winSize=(21, 21), maxLevel=3)
    good = st.reshape(-1) == 1
    p0, p1 = pts.reshape(-1, 2)[good], nxt.reshape(-1, 2)[good]
    if len(p0) < min_inliers:
        return CameraMotion(ok=False, points=int(len(p0)))
    A, inl = cv2.estimateAffinePartial2D(p0, p1, method=cv2.RANSAC, ransacReprojThreshold=2.0)
    n_in = int(inl.sum()) if inl is not None else 0
    if A is None or n_in < min_inliers:
        return CameraMotion(ok=False, points=int(len(p0)), inliers=n_in)
    scale = float(np.hypot(A[0, 0], A[1, 0]))
    shift = float(np.hypot(A[0, 2], A[1, 2]) / w)
    return CameraMotion(ok=True, A=A, shift=shift, scale=scale, points=int(len(p0)), inliers=n_in)


def small_gray(bgr, width=320):
    h, w = bgr.shape[:2]
    s = min(1.0, width / w)
    img = cv2.resize(bgr, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else bgr
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), s


# ----------------------------------------------------------------------------- tracking
def iou(a, b):
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Track:
    id: int
    class_name: str
    box: list
    score: float
    t_first: float
    t_last: float
    hits: int = 1
    misses: int = 0
    # (t, cx, cy, w, h, rel_dx, rel_dy, cam_ok) normalised to image size; rel_* = motion relative to the background
    history: deque = field(default_factory=lambda: deque(maxlen=40))
    announced: set = field(default_factory=set)

    @property
    def age(self):
        return self.t_last - self.t_first

    def as_dict(self):
        return {"id": self.id, "class_name": self.class_name, "box_xyxy": [round(v, 1) for v in self.box],
                "hits": self.hits, "age_s": round(self.age, 2)}


class ByteTracker:
    def __init__(self, high=0.55, low=0.40, match_iou=0.25, second_iou=0.45, max_misses=3):
        self.high, self.low, self.match_iou, self.second_iou, self.max_misses = high, low, match_iou, second_iou, max_misses
        self.tracks = []
        self._next = 1

    def _associate(self, tracks, dets, predicted, thr):
        pairs = sorted(((iou(predicted[t.id], d["box_xyxy"]), ti, di) for ti, t in enumerate(tracks)
                        for di, d in enumerate(dets) if d["class_name"] == t.class_name), reverse=True)
        used_t, used_d, out = set(), set(), []
        for v, ti, di in pairs:
            if v < thr:
                break
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            out.append((ti, di))
        return out, [i for i in range(len(tracks)) if i not in used_t], [i for i in range(len(dets)) if i not in used_d]

    def update(self, dets, t, width, height, cam=None):
        """dets: detection dicts (pixels). cam: CameraMotion prev->cur in the SAME pixel scale (or None)."""
        cam = cam or CameraMotion(ok=False)
        predicted = {}
        for tr in self.tracks:                     # where the box would be if the object were static
            x1, y1 = cam.apply(tr.box[0], tr.box[1])
            x2, y2 = cam.apply(tr.box[2], tr.box[3])
            predicted[tr.id] = [x1, y1, x2, y2]
        high = [d for d in dets if d["confidence"] >= self.high]
        low = [d for d in dets if self.low <= d["confidence"] < self.high]
        m1, rest_t, rest_d = self._associate(self.tracks, high, predicted, self.match_iou)
        remaining = [self.tracks[i] for i in rest_t]
        m2, rest_t2, _ = self._associate(remaining, low, predicted, self.second_iou)
        matched = [(self.tracks[ti], high[di]) for ti, di in m1] + [(remaining[ti], low[di]) for ti, di in m2]
        for tr, d in matched:
            px1, py1, px2, py2 = predicted[tr.id]
            b = d["box_xyxy"]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            rel_dx = (cx - (px1 + px2) / 2) / width
            rel_dy = (cy - (py1 + py2) / 2) / height
            tr.box, tr.score, tr.t_last = list(b), d["confidence"], t
            tr.hits += 1
            tr.misses = 0
            tr.history.append((t, cx / width, cy / height, (b[2] - b[0]) / width, (b[3] - b[1]) / height,
                               rel_dx, rel_dy, cam.ok))
        for i in rest_t2:
            remaining[i].misses += 1
        self.tracks = [tr for tr in self.tracks if tr.misses <= self.max_misses]
        for di in rest_d:                          # new tracks from confident, unmatched detections
            d = high[di]
            b = d["box_xyxy"]
            tr = Track(self._next, d["class_name"], list(b), d["confidence"], t, t)
            tr.history.append((t, (b[0] + b[2]) / 2 / width, (b[1] + b[3]) / 2 / height, (b[2] - b[0]) / width,
                               (b[3] - b[1]) / height, 0.0, 0.0, cam.ok))
            self._next += 1
            self.tracks.append(tr)
        return [tr for tr in self.tracks if tr.misses == 0]
