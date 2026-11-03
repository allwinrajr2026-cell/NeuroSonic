"""Conservative walking-path assessment from RGB object detections (NeuroSonic "Walking Guidance").

What it does
  The lower-central part of the camera image is treated as the approximate walking path (a trapezoid). Each
  detected object (SSDLite, COCO classes) is compared with that region: how much of the path region the box
  covers, and how much of the box lies inside it. Objects at the sides are distinguished from objects that may
  obstruct the path. Results are confirmed over several frames, and image quality (brightness, sharpness) is
  checked, before one of five states is reported:

    CLEAR_VIEW          no recognised object in the path region for 3 consecutive good frames
    POSSIBLE_OBSTACLE   an object overlaps the path region (2 of the last 3 frames)
    BLOCKED_VIEW        an object covers a large part of the path region / fills the lower centre (2 of 3)
    UNCERTAIN           the image is too dark, too blurred or featureless to assess (2 consecutive frames)
    CAMERA_UNAVAILABLE  no usable camera frame

What it does NOT do (and never claims)
  * It does not measure distance: a 2-D box is not a distance. "Lower in the image" is not "close".
  * It does not see steps, potholes, kerbs, poles, walls or other things the COCO detector does not recognise,
    so CLEAR_VIEW means only "no recognised object in the visible path region" and is worded
    "The visible path appears clear. Continue carefully." - never "safe".
  * The thresholds below are engineering defaults, not validated with users or on Vellore streets.
"""
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

CLEAR_VIEW, POSSIBLE_OBSTACLE, BLOCKED_VIEW, UNCERTAIN, CAMERA_UNAVAILABLE = (
    "CLEAR_VIEW", "POSSIBLE_OBSTACLE", "BLOCKED_VIEW", "UNCERTAIN", "CAMERA_UNAVAILABLE")
SEVERITY = {CLEAR_VIEW: 0, UNCERTAIN: 1, CAMERA_UNAVAILABLE: 1, POSSIBLE_OBSTACLE: 2, BLOCKED_VIEW: 3}
# speech category used by the phone's queue (urgent > system > obstacle > navigation > info)
CATEGORY = {BLOCKED_VIEW: "urgent", POSSIBLE_OBSTACLE: "obstacle", UNCERTAIN: "system",
            CAMERA_UNAVAILABLE: "system", CLEAR_VIEW: "info"}

MESSAGES = {
    "chest": {
        CLEAR_VIEW: "The visible path appears clear. Continue carefully.",
        POSSIBLE_OBSTACLE: "Caution. An object is detected in the walking path.",
        BLOCKED_VIEW: "Stop. The walking path may be blocked.",
        UNCERTAIN: "I cannot clearly assess the path. Please check carefully.",
        CAMERA_UNAVAILABLE: "Camera view is unavailable.",
    },
    # handheld: the camera need not point where the user walks, so speak about the camera view, not "the path"
    "handheld": {
        CLEAR_VIEW: "The camera view appears clear. Continue carefully.",
        POSSIBLE_OBSTACLE: "Caution. An object is in front of the camera.",
        BLOCKED_VIEW: "Stop. The view in front of the camera may be blocked.",
        UNCERTAIN: "I cannot clearly assess the camera view. Please check carefully.",
        CAMERA_UNAVAILABLE: "Camera view is unavailable.",
    },
}
REMINDER = {"chest": "Stop. The walking path may still be blocked.",
            "handheld": "Stop. The view in front of the camera may still be blocked."}

# walking-path region: trapezoid in normalised image coordinates (x, y), y = 0 top, 1 bottom
PATH_POLYGON = [(0.22, 1.0), (0.78, 1.0), (0.60, 0.45), (0.40, 0.45)]
_GRID_W, _GRID_H = 64, 48


def _path_mask():
    m = np.zeros((_GRID_H, _GRID_W), np.uint8)
    pts = np.array([[x * (_GRID_W - 1), y * (_GRID_H - 1)] for x, y in PATH_POLYGON], np.int32)
    cv2.fillPoly(m, [pts], 1)
    return m.astype(bool)


PATH_MASK = _path_mask()
PATH_CELLS = int(PATH_MASK.sum())


@dataclass
class Thresholds:
    min_confidence: float = 0.40     # detections below are ignored
    blocked_cover: float = 0.30      # box covers >= 30 % of the path region
    blocked_inpath: float = 0.50     # ... or >= half of the box is in the path AND it fills the lower centre:
    blocked_bottom: float = 0.90     #     box reaches the bottom 10 % of the image
    blocked_height: float = 0.50     #     and is at least half the image height
    possible_cover: float = 0.06     # box covers >= 6 % of the path region
    possible_inpath: float = 0.35    # or >= 35 % of the box lies in the path region
    min_sharpness: float = 20.0      # Laplacian variance of the 320 px grey frame; below: blurred / featureless
    min_brightness: float = 45.0     # below (but usable): too dark to claim a clear view


def sharpness(bgr):
    h, w = bgr.shape[:2]
    s = min(1.0, 320 / max(h, w))
    g = cv2.cvtColor(cv2.resize(bgr, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
                     if s < 1 else bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def box_path_overlap(box, w, h):
    """(cover, inpath): fraction of the path region covered by the box, fraction of the box inside the region."""
    x1, y1, x2, y2 = box
    gx1, gx2 = int(np.floor(max(0.0, x1 / w) * _GRID_W)), int(np.ceil(min(1.0, x2 / w) * _GRID_W))
    gy1, gy2 = int(np.floor(max(0.0, y1 / h) * _GRID_H)), int(np.ceil(min(1.0, y2 / h) * _GRID_H))
    if gx2 <= gx1 or gy2 <= gy1:
        return 0.0, 0.0
    inside = int(PATH_MASK[gy1:gy2, gx1:gx2].sum())
    return inside / PATH_CELLS, inside / max(1, (gx2 - gx1) * (gy2 - gy1))


def side_of(box, w):
    cx = (box[0] + box[2]) / 2 / w
    return "left" if cx < 1 / 3 else ("right" if cx > 2 / 3 else "centre")


@dataclass
class FrameAssessment:
    level: str                      # one of the five states, for this single frame
    reason: str
    in_path: list = field(default_factory=list)   # objects overlapping the path region
    at_side: list = field(default_factory=list)   # recognised objects outside it
    sharpness: float = None
    brightness: float = None


def assess_frame(detections, width, height, quality_status, brightness, sharp, th=Thresholds()):
    """One frame -> FrameAssessment. quality_status: 'ok' | 'warn' | 'unusable' (from RGBAwareness.quality)."""
    if quality_status == "unusable":
        return FrameAssessment(UNCERTAIN, "image too dark or covered", sharpness=sharp, brightness=brightness)
    if sharp is not None and sharp < th.min_sharpness:
        return FrameAssessment(UNCERTAIN, "image blurred or without detail", sharpness=sharp, brightness=brightness)
    in_path, at_side, level = [], [], CLEAR_VIEW
    for d in detections or []:
        if d["confidence"] < th.min_confidence:
            continue
        cover, inpath = box_path_overlap(d["box_xyxy"], width, height)
        x1, y1, x2, y2 = d["box_xyxy"]
        obj = {"class_name": d["class_name"], "side": side_of(d["box_xyxy"], width),
               "path_cover": round(cover, 3), "in_path": round(inpath, 3)}
        # BLOCKED only for objects that are centred or mostly inside the path region: a large object standing
        # mostly beside the path (e.g. a close person at the right edge) is a caution, not a stop
        centred_or_inside = obj["side"] == "centre" or inpath >= th.blocked_inpath
        blocked = (cover >= th.blocked_cover and centred_or_inside) or (
            inpath >= th.blocked_inpath and y2 / height >= th.blocked_bottom and (y2 - y1) / height >= th.blocked_height)
        possible = cover >= th.possible_cover or inpath >= th.possible_inpath
        if blocked:
            obj["level"] = BLOCKED_VIEW
            in_path.append(obj)
            level = BLOCKED_VIEW
        elif possible:
            obj["level"] = POSSIBLE_OBSTACLE
            in_path.append(obj)
            if level != BLOCKED_VIEW:
                level = POSSIBLE_OBSTACLE
        else:
            at_side.append(obj)
    if level == CLEAR_VIEW and (quality_status == "warn" or (brightness is not None and brightness < th.min_brightness)):
        return FrameAssessment(UNCERTAIN, "image too dark to confirm a clear view", in_path, at_side, sharp, brightness)
    reason = {CLEAR_VIEW: "no recognised object in the path region", POSSIBLE_OBSTACLE: "object overlaps the path region",
              BLOCKED_VIEW: "object covers a large part of the path region"}[level]
    return FrameAssessment(level, reason, in_path, at_side, sharp, brightness)


class PathGuide:
    """Temporal state machine + announcement policy for one phone session."""

    def __init__(self, mode="chest", window=3, blocked_reminder_s=8.0, uncertain_repeat_s=30.0,
                 possible_change_cooldown_s=4.0, deescalate_min_s=2.0):
        self.mode = mode if mode in MESSAGES else "chest"
        self.frames = deque(maxlen=window)
        self.state = None
        self.since = None
        self.last_spoken = {}          # state -> time
        self.last_spoken_any = None
        self.last_obstruction = None   # signature of the obstruction last announced
        self.cfg = dict(blocked_reminder_s=blocked_reminder_s, uncertain_repeat_s=uncertain_repeat_s,
                        possible_change_cooldown_s=possible_change_cooldown_s, deescalate_min_s=deescalate_min_s)

    def _decide(self):
        levels = [f.level for f in self.frames]
        last = levels[-1]
        if last == CAMERA_UNAVAILABLE:
            return CAMERA_UNAVAILABLE
        if sum(lv == BLOCKED_VIEW for lv in levels) >= 2:
            return BLOCKED_VIEW
        if sum(lv in (BLOCKED_VIEW, POSSIBLE_OBSTACLE) for lv in levels) >= 2:
            return POSSIBLE_OBSTACLE
        if len(levels) >= 2 and levels[-1] == UNCERTAIN and levels[-2] == UNCERTAIN:
            return UNCERTAIN
        if len(levels) == self.frames.maxlen and all(lv == CLEAR_VIEW for lv in levels):
            return CLEAR_VIEW
        return self.state   # not enough evidence for a change: keep the current state (hysteresis)

    @staticmethod
    def _signature(fa):
        return tuple(sorted({(o["side"], o["level"]) for o in fa.in_path}))   # zones, not counts

    def update(self, fa, t):
        """Add one FrameAssessment at time t. Returns dict(state, changed, announce, text, category, reason)."""
        self.frames.append(fa)
        new = self._decide()
        prev, changed, announce, text = self.state, False, False, None
        if new is not None and new != self.state:
            escalation = self.state is None or SEVERITY[new] > SEVERITY[self.state]
            quiet_long_enough = self.last_spoken_any is None or t - self.last_spoken_any >= self.cfg["deescalate_min_s"]
            if escalation or quiet_long_enough:
                self.state, self.since, changed = new, t, True
                announce, text = True, MESSAGES[self.mode][new]
        elif new is not None and new == self.state:
            last = self.last_spoken.get(new)
            if new == BLOCKED_VIEW and last is not None and t - last >= self.cfg["blocked_reminder_s"]:
                announce, text = True, REMINDER[self.mode]
            elif new in (UNCERTAIN, CAMERA_UNAVAILABLE) and last is not None and t - last >= self.cfg["uncertain_repeat_s"]:
                announce, text = True, MESSAGES[self.mode][new]
            elif new == POSSIBLE_OBSTACLE and last is not None and t - last >= self.cfg["possible_change_cooldown_s"]:
                if self._signature(fa) and self._signature(fa) != self.last_obstruction:
                    announce, text = True, MESSAGES[self.mode][new]     # the obstruction changed
        if announce:
            self.last_spoken[self.state] = t
            self.last_spoken_any = t
            if self.state in (POSSIBLE_OBSTACLE, BLOCKED_VIEW):
                self.last_obstruction = self._signature(fa)
        return {"state": self.state, "previous": prev, "changed": changed, "announce": announce, "text": text,
                "category": CATEGORY.get(self.state, "info"), "reason": fa.reason,
                "frame_level": fa.level, "in_path": fa.in_path, "at_side": fa.at_side}

    def camera_unavailable(self, t):
        return self.update(FrameAssessment(CAMERA_UNAVAILABLE, "no usable camera frame"), t)
