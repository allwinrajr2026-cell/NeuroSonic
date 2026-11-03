"""Alert engine: turns per-frame detections + input quality into a small number of spoken-style alerts.

Rules (all configurable in AlertConfig, defaults are a starting point, NOT validated with users):
  * Only detections with confidence >= alert_conf are considered. Object alerts are produced only from
    detections present in the current frame - the engine never invents or extrapolates objects.
  * Position: horizontal centre of the box in the IR frame -> "on the left" / "ahead" / "on the right"
    (thirds). "ahead" means "in the middle of the camera view", NOT a distance or collision claim.
  * Confirmation: an object (a simple IoU track) must be detected in >= confirm_hits of the last
    confirm_window frames before it is announced (suppresses single-frame flicker).
  * Repetition control: a track is announced once; again only if its position bucket changes or it is still
    present after repeat_s. Within cooldown_s after "<class> <position>" was said, other tracks with the
    same class and position are treated as covered by that message.
  * At most max_object_alerts_per_frame messages per frame; same class+position are merged ("2 people
    ahead"); order: class priority (Car > E-bike > person), then box area (larger first). Deferred groups
    stay eligible for the next frames.
  * System alerts (highest priority): "Obstacle detection unavailable: <reason>" when input is unusable for
    unavailable_after_s or no frame arrives for stall_s; "Obstacle detection resumed" after resume_after_s
    of usable input; a periodic low-quality notice for WARN frames. While unavailable, no object alerts.
  * A new replay segment (clip cut) resets tracks and cooldowns.
"""
from collections import deque
from dataclasses import dataclass, field

from .quality import UNUSABLE, WARN

SPOKEN = {"person": ("Person", "people"), "Ebike": ("E-bike", "E-bikes"), "Car": ("Car", "cars")}
POSITION_TEXT = {"left": "on the left", "ahead": "ahead", "right": "on the right"}

PRIORITY_UNAVAILABLE, PRIORITY_RESUMED, PRIORITY_LOW_QUALITY, PRIORITY_OBJECT_BASE = 100, 90, 50, 10


@dataclass
class AlertConfig:
    alert_conf: float = 0.40
    confirm_hits: int = 2
    confirm_window: int = 3
    track_iou: float = 0.30
    cooldown_s: float = 5.0
    repeat_s: float = 15.0
    max_object_alerts_per_frame: int = 2
    left_edge: float = 1 / 3
    right_edge: float = 2 / 3
    class_priority: dict = field(default_factory=lambda: {"Car": 3, "Ebike": 2, "person": 1})
    unavailable_after_s: float = 1.0
    resume_after_s: float = 1.0
    stall_s: float = 2.0
    low_quality_notice_s: float = 30.0
    # wording (defaults keep the original WOAD texts): e.g. handheld mode uses "in camera view, left"
    position_text: dict = field(default_factory=lambda: dict(POSITION_TEXT))
    spoken_names: dict = field(default_factory=lambda: dict(SPOKEN))
    detected_word: str = " detected"   # "Person detected ahead." ; "" -> "Person ahead."

    def validate(self):
        if not 0 <= self.alert_conf <= 1:
            raise ValueError("alert_conf must be within [0, 1]")
        if not 1 <= self.confirm_hits <= self.confirm_window:
            raise ValueError("need 1 <= confirm_hits <= confirm_window")
        if not 0 < self.left_edge < self.right_edge < 1:
            raise ValueError("need 0 < left_edge < right_edge < 1")
        if self.max_object_alerts_per_frame < 1:
            raise ValueError("max_object_alerts_per_frame must be >= 1")
        return self


@dataclass
class AlertEvent:
    time: float
    frame_index: int
    frame_id: str
    kind: str          # "object" | "system"
    priority: int
    text: str
    data: dict = field(default_factory=dict)

    def as_dict(self):
        return {"time": round(self.time, 3), "frame_index": self.frame_index, "frame_id": self.frame_id,
                "kind": self.kind, "priority": self.priority, "text": self.text, "data": self.data}


class _Track:
    __slots__ = ("id", "cls", "box", "conf", "hits", "bucket", "announced_bucket", "last_announced")

    def __init__(self, tid, cls, box, conf, window):
        self.id, self.cls, self.box, self.conf = tid, cls, box, conf
        self.hits = deque([True], maxlen=window)
        self.bucket = None
        self.announced_bucket = None
        self.last_announced = None


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


class AlertEngine:
    def __init__(self, config=None):
        self.cfg = (config or AlertConfig()).validate()
        self.tracks = []
        self._next_id = 0
        self._said = {}               # (cls, bucket) -> time last said
        self.available = True
        self._bad_since = None
        self._bad_reason = None
        self._good_since = None
        self._last_frame_time = None
        self._last_low_quality_notice = None

    # ------------------------------------------------------------------ helpers
    def _bucket(self, box, width):
        cx = (box[0] + box[2]) / 2 / width
        return "left" if cx < self.cfg.left_edge else ("right" if cx > self.cfg.right_edge else "ahead")

    def _reset_tracking(self):
        self.tracks = []
        self._said = {}

    def _system(self, t, idx, fid, priority, text, **data):
        return AlertEvent(t, idx, fid, "system", priority, text, data)

    def _go_unavailable(self, t, idx, fid, reason):
        self.available = False
        self._good_since = None
        self._reset_tracking()
        return self._system(t, idx, fid, PRIORITY_UNAVAILABLE, f"Obstacle detection unavailable: {reason}.",
                            reason=reason)

    # ------------------------------------------------------------------ watchdog
    def tick(self, now):
        """Call periodically (live use). Detects a stalled frame stream."""
        if (self.available and self._last_frame_time is not None
                and now - self._last_frame_time >= self.cfg.stall_s):
            return [self._go_unavailable(now, None, None, "no camera frames")]
        return []

    # ------------------------------------------------------------------ main entry
    def process(self, *, time, frame_index, frame_id, image_width, detections, quality, segment_start=False,
                error=None, image_height=None):
        """detections: list of {"class_name", "confidence", "box_xyxy"} or None if inference did not run.
        quality: QualityReport. Returns a list of AlertEvent (system events first)."""
        cfg, t, events = self.cfg, time, []
        self._last_frame_time = t
        if segment_start:
            self._reset_tracking()

        usable = error is None and detections is not None and quality.status != UNUSABLE
        if not usable:
            if error is not None:
                reason = "image could not be read"
            elif quality.status == UNUSABLE and quality.reasons:
                reason = quality.reasons[0]
            else:
                reason = "detector did not run"
            if self._bad_since is None:
                self._bad_since, self._bad_reason = t, reason
            self._good_since = None
            self._reset_tracking()
            if self.available and t - self._bad_since >= cfg.unavailable_after_s:
                events.append(self._go_unavailable(t, frame_index, frame_id, self._bad_reason))
            return events

        self._bad_since = None
        if not self.available:
            if self._good_since is None:
                self._good_since = t
            if t - self._good_since >= cfg.resume_after_s:
                self.available = True
                events.append(self._system(t, frame_index, frame_id, PRIORITY_RESUMED, "Obstacle detection resumed."))
        if quality.status == WARN and self.available and (
                self._last_low_quality_notice is None or t - self._last_low_quality_notice >= cfg.low_quality_notice_s):
            self._last_low_quality_notice = t
            events.append(self._system(t, frame_index, frame_id, PRIORITY_LOW_QUALITY,
                                       "Camera image quality is low. Detections may be unreliable.",
                                       reasons=list(quality.reasons)))

        # ---- tracking (per class, greedy IoU)
        dets = [d for d in detections if d["confidence"] >= cfg.alert_conf]
        seen_now = set()
        unmatched = list(range(len(dets)))
        pairs = sorted(((_iou(tr.box, dets[j]["box_xyxy"]), ti, j) for ti, tr in enumerate(self.tracks)
                        for j in range(len(dets)) if tr.cls == dets[j]["class_name"]), reverse=True)
        used_t = set()
        for v, ti, j in pairs:
            if v < cfg.track_iou:
                break
            if ti in used_t or j not in unmatched:
                continue
            tr = self.tracks[ti]
            tr.box, tr.conf = dets[j]["box_xyxy"], dets[j]["confidence"]
            tr.hits.append(True)
            used_t.add(ti)
            unmatched.remove(j)
            seen_now.add(tr.id)
        for ti, tr in enumerate(self.tracks):
            if ti not in used_t:
                tr.hits.append(False)
        self.tracks = [tr for tr in self.tracks if any(tr.hits)]
        for j in unmatched:
            d = dets[j]
            tr = _Track(self._next_id, d["class_name"], d["box_xyxy"], d["confidence"], cfg.confirm_window)
            self._next_id += 1
            self.tracks.append(tr)
            seen_now.add(tr.id)
        for tr in self.tracks:
            tr.bucket = self._bucket(tr.box, image_width)

        if not self.available:
            return events

        # ---- candidates: confirmed, seen in this frame, due for announcement
        groups = {}
        for tr in self.tracks:
            if tr.id not in seen_now or sum(tr.hits) < cfg.confirm_hits:
                continue
            due = (tr.announced_bucket is None or tr.bucket != tr.announced_bucket
                   or t - tr.last_announced >= cfg.repeat_s)
            if not due:
                continue
            key = (tr.cls, tr.bucket)
            said = self._said.get(key)
            if said is not None and t - said < cfg.cooldown_s:
                tr.announced_bucket, tr.last_announced = tr.bucket, said   # covered by the recent message
                continue
            groups.setdefault(key, []).append(tr)

        ranked = sorted(groups.items(), key=lambda kv: (
            -cfg.class_priority.get(kv[0][0], 0),
            -max((tr.box[2] - tr.box[0]) * (tr.box[3] - tr.box[1]) for tr in kv[1]), kv[0]))
        for (cls, bucket), trs in ranked[:cfg.max_object_alerts_per_frame]:
            one, many = cfg.spoken_names.get(cls, (cls.capitalize(), cls + "s"))
            n = len(trs)
            where = cfg.position_text[bucket]
            text = f"{one}{cfg.detected_word} {where}." if n == 1 else f"{n} {many}{cfg.detected_word} {where}."
            for tr in trs:
                tr.announced_bucket, tr.last_announced = bucket, t
            self._said[(cls, bucket)] = t
            data = {"class_name": cls, "position": bucket, "count": n,
                    "max_confidence": round(max(tr.conf for tr in trs), 4),
                    "boxes_xyxy": [[round(v, 1) for v in tr.box] for tr in trs],
                    "track_ids": [tr.id for tr in trs]}
            if image_height:   # share of the image covered by the largest box (no distance claim)
                data["max_area_frac"] = round(max((tr.box[2] - tr.box[0]) * (tr.box[3] - tr.box[1]) for tr in trs)
                                              / float(image_width * image_height), 4)
            events.append(AlertEvent(t, frame_index, frame_id, "object",
                                     PRIORITY_OBJECT_BASE + cfg.class_priority.get(cls, 0), text, data))
        return events
