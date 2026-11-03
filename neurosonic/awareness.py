"""Live RGB camera awareness: a general COCO object detector on ordinary phone/webcam frames.

This is NOT the WOAD model (WOAD needs CS30 near-IR + depth). It is torchvision's SSDLite320-MobileNetV3-Large,
COCO weights (box mAP 21.3 on COCO val2017 - a small, fast, modest detector), used here only for obstacle-relevant
COCO classes. It has not been validated for assistive use, cannot see steps/kerbs/holes/poles/walls, and gives
NO distance (a single RGB camera cannot measure distance; we never estimate it).

Frames are sent by the phone to the laptop (JPEG) and analysed. Two outputs:
  * Walking Guidance (always on, the main experience): neurosonic/pathguide.py turns detections, image quality and
    sharpness into one of five path states (CLEAR_VIEW, POSSIBLE_OBSTACLE, BLOCKED_VIEW, UNCERTAIN,
    CAMERA_UNAVAILABLE), confirmed over frames, and speaks only on meaningful changes.
  * Object Description (optional, describe=True): object names with left/centre/right via the existing WOAD alert
    engine (woad/alerts.py: confidence threshold, 2-of-3 frame confirmation, cooldowns, merging).
Wording depends on how the phone is carried:
  chest    - camera faces the walking direction:  "Stop. The walking path may be blocked." / "Person ahead."
  handheld - camera direction is unknown:          "... in front of the camera" / "Person in camera view, left."
BLOCKED_VIEW is spoken with the urgent priority (interrupts navigation speech); POSSIBLE_OBSTACLE with the obstacle
priority. Object descriptions never interrupt. No message is ever a distance or a safety guarantee.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import torch

from woad.alerts import AlertConfig, AlertEngine

from .pathguide import MESSAGES as PATH_MESSAGES, PATH_POLYGON, REMINDER as PATH_REMINDER, SEVERITY, PathGuide
from .pathguide import assess_frame, sharpness
from .detectors import make_detector
from .events import PathEventDetector
from .tracking import ByteTracker, estimate_camera_motion, small_gray
from woad.quality import OK, UNUSABLE, WARN, QualityReport

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEIGHTS = ROOT / "models" / "rgb" / "ssdlite320_mobilenet_v3_large_coco-a79551df.pth"

# COCO class id -> (spoken singular, plural, priority). Only obstacle-relevant classes are announced.
OBSTACLE_CLASSES = {
    1: ("Person", "people", 2), 2: ("Bicycle", "bicycles", 3), 3: ("Car", "cars", 4), 4: ("Motorcycle", "motorcycles", 4),
    6: ("Bus", "buses", 4), 8: ("Truck", "trucks", 4), 10: ("Traffic light", "traffic lights", 1),
    11: ("Fire hydrant", "fire hydrants", 2), 13: ("Stop sign", "stop signs", 1), 15: ("Bench", "benches", 2),
    17: ("Cat", "cats", 1), 18: ("Dog", "dogs", 3), 19: ("Horse", "horses", 3), 21: ("Cow", "cows", 3),
    62: ("Chair", "chairs", 2), 63: ("Sofa", "sofas", 2), 64: ("Potted plant", "potted plants", 2),
    67: ("Table", "tables", 2), 72: ("TV", "TVs", 1), 78: ("Microwave", "microwaves", 1),
    82: ("Refrigerator", "refrigerators", 2), 28: ("Umbrella", "umbrellas", 1), 33: ("Suitcase", "suitcases", 2),
}
MODES = {
    "chest": {"left": "on the left", "ahead": "ahead", "right": "on the right"},
    "handheld": {"left": "in camera view, left", "ahead": "in camera view, centre", "right": "in camera view, right"},
}
URGENT_AREA = 0.25   # kept for reference; urgency now comes from the BLOCKED_VIEW path state
SESSION_IDLE_S = 120
# frame interval the phone is asked to use: the GPU detector keeps up with 5 frames/s, the CPU fallback with 2.5
FRAME_MS_GPU, FRAME_MS_CPU = 200, 400
DETECTOR_INFO = {
    "rf-detr-nano": {"model": "RF-DETR Nano (Roboflow, COCO, 384 px) on the NVIDIA GPU",
                     "licence": "Apache-2.0 (rfdetr); COCO annotations CC BY 4.0", "coco_box_map": 48.4},
    "ssdlite320": {"model": "SSDLite320-MobileNetV3-Large (torchvision, COCO)",
                   "licence": "BSD-3-Clause (torchvision); COCO annotations CC BY 4.0", "coco_box_map": 21.3},
}


class _Session:
    """Per-phone state: alert engine (object description), walking-path guide, tracker, event rules, last frame."""

    def __init__(self, engine, mode, guide):
        self.engine, self.mode, self.guide = engine, mode, guide
        self.tracker = ByteTracker()
        self.events = PathEventDetector(mode)
        self.prev_gray = None
        self.last_entering_t = None   # the specific "moving into your path" message replaces the generic caution
        self.last = time.time()


class RGBAwareness:
    def __init__(self, weights=DEFAULT_WEIGHTS, score_thres=0.40, max_side=320, detector=None, events=True, log=print):
        """detector: auto | rfdetr | ssdlite (default: $NEUROSONIC_DETECTOR, else ssdlite). `weights` = SSDLite weights,
        which must exist: SSDLite is the guaranteed fallback."""
        self.weights = Path(weights)
        self.score_thres, self.max_side = score_thres, max_side
        self.detector_preference = detector
        self.enable_events = events
        self.log = log
        self._model = None            # the active detector (FallbackDetector), created on first use
        self._detector_info = {}
        self._lock = threading.Lock()
        # All detector work runs on ONE long-lived thread. The HTTP server handles every request on a new thread, and
        # running the GPU model from ever-new threads made PyTorch/CUDA create per-thread state each time: in a
        # 10-minute soak test (2026-11-03) server RAM grew ~2 MiB/s and latency crept up. One inference thread keeps
        # that state warm and bounded.
        self._infer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="neurosonic-infer")
        self._sessions = {}
        self.error = None
        self.stats = {"frames": 0, "last_ms": None, "load_ms": None, "frames_by_detector": {}}
        self.clients = {}             # per device (IP): frames, last frame size, detector, recent processing times
        #                               - counters only; no image is kept

    def available(self):
        if not self.weights.exists():
            self.error = f"detector weights missing: {self.weights}"
            return False
        return True

    def detector_name(self):
        return self._model.name if self._model is not None else None

    def info(self):
        name = self.detector_name() or "ssdlite320"
        d = DETECTOR_INFO.get(name, DETECTOR_INFO["ssdlite320"])
        det = {"name": name, "device": self._model.device if self._model else None, "loaded": self._model is not None,
               "requested": self._detector_info.get("requested"),
               "precision": getattr(getattr(self._model, "active", None), "precision", "fp32") if self._model else None,
               "fallback_reason": (self._model.fallback_reason if self._model and self._model.fallback_reason
                                   else self._detector_info.get("fallback_reason"))}
        return {"available": self.available(), "model": d["model"], "detector": det,
                "recommended_frame_ms": FRAME_MS_GPU if det["device"] == "cuda" else FRAME_MS_CPU,
                "events": "entering the walking path, crossing in front (camera-motion compensated)" if self.enable_events else "off",
                "weights": "rf-detr-nano.pth" if name == "rf-detr-nano" else self.weights.name,
                "fallback_weights": self.weights.name, "licence": d["licence"],
                "coco_box_map": d["coco_box_map"], "classes": sorted({v[0] for v in OBSTACLE_CLASSES.values()}),
                "distance": "not available (single RGB camera)", "modes": list(MODES), "error": self.error,
                "loaded": self._model is not None,
                "clients": {ip: {"frames": c["frames"], "last_frame": c["last_frame"], "detector": c["detector"],
                                 "processing_ms_median": (sorted(c["ms"])[len(c["ms"]) // 2] if c["ms"] else None),
                                 "events_spoken": c["events"], "last_seen_s_ago": round(time.time() - c["t"], 1)}
                            for ip, c in self.clients.items()},
                "path_states": list(SEVERITY), "path_messages": PATH_MESSAGES, "path_reminders": PATH_REMINDER,
                **self.stats}

    def _load(self):
        if self._model is None:
            if not self.available():
                raise RuntimeError(self.error)
            t = time.perf_counter()
            self._model, self._detector_info = make_detector(OBSTACLE_CLASSES, self.detector_preference,
                                                             self.score_thres, self.max_side, self.weights, self.log)
            self.stats["load_ms"] = round((time.perf_counter() - t) * 1000)
        return self._model

    def warm_up(self):
        try:
            self.detect(np.zeros((240, 320, 3), np.uint8))
            return True
        except Exception as e:  # noqa: BLE001 - reported in status
            self.error = f"{type(e).__name__}: {e}"
            return False

    # ------------------------------------------------------------------ detection
    def detect(self, bgr):
        """bgr uint8 HxWx3 -> list of {class_id, class_name, confidence, box_xyxy} (obstacle classes only).
        RF-DETR on the GPU when available, otherwise (or after any RF-DETR failure) SSDLite on the CPU.
        Runs on the dedicated inference thread (see __init__)."""
        return self._infer.submit(self._detect_on_worker, bgr).result()

    def _detect_on_worker(self, bgr):
        with self._lock:
            m = self._load()
            t = time.perf_counter()
            dets = m.detect(bgr)
            self.stats["last_ms"] = round((time.perf_counter() - t) * 1000)
            self.stats["frames"] += 1
            fb = self.stats["frames_by_detector"]
            fb[m.name] = fb.get(m.name, 0) + 1
        return dets

    @staticmethod
    def quality(bgr):
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        mean, std = float(g.mean()), float(g.std())
        if mean < 20 or std < 6:
            return QualityReport(UNUSABLE, [f"camera image too dark or covered (brightness {mean:.0f})"], mean, std, None)
        if mean < 45:
            return QualityReport(WARN, [f"camera image dark (brightness {mean:.0f})"], mean, std, None)
        return QualityReport(OK, [], mean, std, None)

    # ------------------------------------------------------------------ sessions (one alert engine per device)
    def _engine(self, session, mode):
        return self._session(session, mode)[0]

    def _session(self, session, mode):
        """(AlertEngine, PathGuide) for one phone session; recreated when the carrying mode changes."""
        st = self._state(session, mode)
        return st.engine, st.guide

    def _state(self, session, mode):
        now = time.time()
        for k in [k for k, v in self._sessions.items() if now - v.last > SESSION_IDLE_S]:
            del self._sessions[k]
        cur = self._sessions.get(session)
        if cur is None or cur.mode != mode:
            cfg = AlertConfig(confirm_hits=2, confirm_window=3, cooldown_s=6.0, repeat_s=20.0,
                              max_object_alerts_per_frame=2, unavailable_after_s=2.0, resume_after_s=1.0,
                              position_text=dict(MODES[mode]), detected_word="",
                              spoken_names={v[0]: (v[0], v[1]) for v in OBSTACLE_CLASSES.values()},
                              class_priority={v[0]: v[2] for v in OBSTACLE_CLASSES.values()})
            cur = _Session(AlertEngine(cfg), mode, PathGuide(mode))
        cur.last = now
        self._sessions[session] = cur
        return cur

    def process_frame(self, jpeg_bytes, session="default", mode="chest", t=None, describe=False):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {list(MODES)}")
        bgr = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("camera frame could not be decoded")
        t_start = time.perf_counter()
        h, w = bgr.shape[:2]
        q = self.quality(bgr)
        dets = self.detect(bgr) if q.status != UNUSABLE else None
        t_det = time.perf_counter()
        st = self._state(session, mode)
        engine, guide = st.engine, st.guide
        t = time.time() if t is None else t
        # tracking with camera-motion compensation (background optical flow outside the detected objects)
        gray, gs = small_gray(bgr)
        cam = estimate_camera_motion(st.prev_gray, gray, [[v * gs for v in tr.box] for tr in st.tracker.tracks])
        if cam.ok and gs != 1.0:
            cam.A = cam.A.copy()
            cam.A[:, 2] /= gs                         # translation back to full-resolution pixels
        st.prev_gray = gray
        tracks = st.tracker.update(dets or [], t, w, h, cam)
        # 1. walking guidance (always)
        fa = assess_frame(dets, w, h, q.status, q.ir_mean, sharpness(bgr))
        path = guide.update(fa, t)
        out = []
        if path["announce"]:
            out.append({"time": round(t, 3), "kind": "path", "text": path["text"], "category": path["category"],
                        "priority": {"urgent": 40, "obstacle": 30, "system": 20, "info": 5}[path["category"]],
                        "urgent": path["category"] == "urgent", "data": {"state": path["state"], "reason": path["reason"]}})
        # 1b. temporal events (entering the path / crossing in front); conservative, see neurosonic/events.py
        evs = st.events.update(tracks, t, w, h, cam, path["state"]) if self.enable_events else []
        if (out and out[0]["kind"] == "path" and path["state"] == "POSSIBLE_OBSTACLE" and st.last_entering_t is not None
                and t - st.last_entering_t < 2.0):
            out.pop(0)                 # "Caution. A person is moving into your path…" was just said; no generic repeat
        for ev in evs:
            if ev["type"] == "entering":
                st.last_entering_t = t
            item = {"time": round(t, 3), "kind": "event", "text": ev["text"], "category": "obstacle", "priority": 30,
                    "urgent": False, "data": {k: v for k, v in ev.items() if k != "text"}}
            if out and out[0]["kind"] == "path" and path["state"] == "POSSIBLE_OBSTACLE" and ev["type"] == "entering":
                out[0] = dict(item, data=dict(item["data"], state=path["state"]))   # more specific than the generic caution
            else:
                out.append(item)
        # 2. object description (only when enabled); the alert engine still tracks objects either way
        events = engine.process(time=t, frame_index=self.stats["frames"], frame_id="camera", image_width=w,
                                image_height=h, detections=dets, quality=q)
        for e in events:
            if e.kind == "system":
                continue   # availability is reported by the path state (UNCERTAIN) instead
            if not describe:
                continue
            d = e.as_dict()
            d["category"] = "description"   # never interrupts; spoken after path guidance
            d["urgent"] = False
            out.append(d)
        t_end = time.perf_counter()
        ip = str(session).split(":", 1)[0]
        c = self.clients.setdefault(ip, {"frames": 0, "last_frame": None, "detector": None, "ms": [], "events": 0, "t": 0})
        c["frames"] += 1
        c["last_frame"] = f"{w}x{h}"
        c["detector"] = self.detector_name()
        c["ms"] = (c["ms"] + [round((t_end - t_start) * 1000, 1)])[-100:]
        c["events"] += sum(1 for e in out if e["kind"] == "event")
        c["t"] = time.time()
        return {"width": w, "height": h, "quality": q.as_dict(), "detections": dets or [], "events": out,
                "tracks": [tr.as_dict() for tr in tracks], "camera_motion": cam.as_dict(),
                "detector": {"name": self.detector_name(), "device": self._model.device if self._model else None},
                "timing": {"detect_ms": round((t_det - t_start) * 1000, 1), "total_ms": round((t_end - t_start) * 1000, 1)},
                "path": {"state": path["state"], "frame_level": path["frame_level"], "reason": path["reason"],
                         "in_path": path["in_path"], "at_side": path["at_side"], "polygon": PATH_POLYGON,
                         "sharpness": round(fa.sharpness, 1) if fa.sharpness is not None else None},
                "describe": bool(describe), "available": engine.available, "inference_ms": self.stats["last_ms"],
                "mode": mode}
