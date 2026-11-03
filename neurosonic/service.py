"""NeuroSonic detection service: wraps the WOAD detector, input-quality check and alert engine.

* One model instance, guarded by a lock (replay thread and uploads share it).
* Replay runner: a background thread replays a known demo set at a real-time pace and publishes the latest
  annotated frame, detections, input quality and alert events. Clients poll.
* Upload: one IR + depth pair -> detections, quality, alert texts, annotated JPEG.
Only server-side known replay sets can be played (no client-supplied paths).
"""
import base64
import collections
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from woad.alerts import AlertConfig, AlertEngine
from woad.detector import WOADDetector
from woad.model_loader import DEFAULT_WEIGHTS
from woad.quality import UNUSABLE, InputQualityChecker
from woad.sources import ReplaySource
from woad.visualize import draw_detections, side_by_side

ROOT = Path(__file__).resolve().parents[1]

REPLAY_SETS = {
    # name: (folder, segment_gap, description)
    "detec_test": (ROOT / "demo_data" / "detec_test", 10, "600 real IR+depth frames (published by the WOAD authors)"),
    "reconstructed_val": (ROOT / "demo_data" / "reconstructed_val", None,
                          "187 degraded frames rebuilt from exp72 validation plots"),
    "sensor_recording": (ROOT.parent / "datasets" / "test1730450780_paired", None,
                         "raw CS30 recording - too dark for the model (shows input-quality warnings)"),
}


class InvalidInput(ValueError):
    pass


def decode_image(data, role):
    """bytes -> 8-bit BGR image, with the same rules as woad.preprocess.read_image."""
    if not data:
        raise InvalidInput(f"{role} image missing")
    im = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if im is None:
        raise InvalidInput(f"{role} image could not be decoded")
    if im.dtype != np.uint8:
        raise InvalidInput(f"{role} image must be 8-bit (got {im.dtype}); raw 16-bit depth is not supported")
    if im.ndim == 2:
        if role == "depth":
            raise InvalidInput("depth must be the colour-mapped (3-channel) depth image, not a grey depth map")
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    elif im.shape[2] == 4:
        im = cv2.cvtColor(im, cv2.COLOR_BGRA2BGR)
    return im


def render(ir, depth, detections, width=960, quality=85):
    panel = side_by_side(draw_detections(ir, detections), draw_detections(depth, detections))
    h, w = panel.shape[:2]
    if w > width:
        panel = cv2.resize(panel, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", panel, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes()


class EventLog:
    """In-memory ring of recent alert events with increasing ids (for client polling)."""

    def __init__(self, store=None, maxlen=300):
        self._lock = threading.Lock()
        self._events = collections.deque(maxlen=maxlen)
        self._next = 1
        self.store = store

    def add(self, source, kind, text, priority=10, data=None, frame_id=None):
        data = data or {}
        with self._lock:
            ev = {"id": self._next, "time": time.time(), "source": source, "kind": kind, "text": text,
                  "priority": priority, "data": data, "frame_id": frame_id}
            self._next += 1
            self._events.append(ev)
        if self.store is not None:
            self.store.add_alert(source, kind, text, class_name=data.get("class_name"), position=data.get("position"),
                                 confidence=data.get("max_confidence"), frame_id=frame_id)
        return ev

    def since(self, last_id):
        with self._lock:
            return [e for e in self._events if e["id"] > last_id]

    @property
    def last_id(self):
        with self._lock:
            return self._next - 1


class ReplayRunner(threading.Thread):
    def __init__(self, service, name, fps, start=0, loop=True):
        super().__init__(daemon=True, name=f"replay-{name}")
        folder, gap, _ = REPLAY_SETS[name]
        self.service, self.set_name, self.fps, self.loop = service, name, float(fps), loop
        self.source = ReplaySource.from_root(folder, fps=self.fps, segment_gap=gap, start=start)
        self.engine = AlertEngine(AlertConfig())
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.state = {"running": True, "set": name, "fps": self.fps, "frames": len(self.source), "frame_index": None,
                      "frame_id": None, "segment": None, "quality": None, "detections": [], "available": True,
                      "seq": 0, "error": None, "inference_ms": None, "loops": 0}
        self.jpeg = None

    def stop(self):
        self.stop_event.set()

    def _publish(self, **kw):
        with self.lock:
            self.state.update(kw)

    def snapshot(self):
        with self.lock:
            return dict(self.state), self.jpeg

    def run(self):
        svc, period = self.service, 1.0 / self.fps
        try:
            while not self.stop_event.is_set():
                for frame in self.source:
                    if self.stop_event.is_set():
                        break
                    t0 = time.perf_counter()
                    q = svc.checker.check(frame.ir, frame.depth)
                    dets, err, ms = None, frame.error, None
                    if err is None and q.status != UNUSABLE:
                        with svc.model_lock:
                            t1 = time.perf_counter()
                            dets = svc.detector.detect_arrays(frame.ir, frame.depth)["detections"]
                            ms = round((time.perf_counter() - t1) * 1000)
                    events = self.engine.process(time=frame.timestamp + self.state["loops"] * len(self.source) / self.fps,
                                                 frame_index=frame.index, frame_id=frame.frame_id,
                                                 image_width=frame.ir.shape[1] if frame.ir is not None else 640,
                                                 detections=dets, quality=q, segment_start=frame.segment_start, error=err)
                    for e in events:
                        svc.events.add("replay", e.kind, e.text, e.priority, e.data, frame.frame_id)
                    jpeg = render(frame.ir, frame.depth, dets or []) if frame.ir is not None else None
                    with self.lock:
                        self.state.update(frame_index=frame.index, frame_id=frame.frame_id, segment=frame.segment,
                                          quality=q.as_dict(), detections=dets or [], available=self.engine.available,
                                          error=err, inference_ms=ms, seq=self.state["seq"] + 1)
                        if jpeg is not None:
                            self.jpeg = jpeg
                    self.stop_event.wait(max(0.0, period - (time.perf_counter() - t0)))
                if not self.loop:
                    break
                self._publish(loops=self.state["loops"] + 1)
                self.engine = AlertEngine(AlertConfig())
        except Exception as e:  # never die silently: report to clients
            self._publish(error=f"replay failed: {e}")
            svc.events.add("replay", "system", "Obstacle detection unavailable: replay error.", 100)
        finally:
            self._publish(running=False)


class DetectionService:
    def __init__(self, store=None, weights=DEFAULT_WEIGHTS, device="cpu"):
        self.detector = WOADDetector(weights, device, conf_thres=0.25)
        self.model_lock = threading.Lock()
        self.checker = InputQualityChecker()
        self.events = EventLog(store)
        self.replay = None
        self._replay_lock = threading.Lock()

    def info(self):
        i = self.detector.info
        return {"names": i["names"], "sha256": i["sha256"], "num_params": i["num_params"], "device": i["device"],
                "checkpoint_date": i["date"]}

    @staticmethod
    def replay_sets():
        return [{"name": n, "available": (f / "ir").is_dir() and (f / "depth").is_dir(), "description": d}
                for n, (f, _, d) in REPLAY_SETS.items()]

    # ---- replay control
    def start_replay(self, name, fps=4.0, start=0, loop=True):
        if name not in REPLAY_SETS:
            raise InvalidInput(f"unknown replay set '{name}'")
        if not 0.5 <= float(fps) <= 10:
            raise InvalidInput("fps must be between 0.5 and 10")
        with self._replay_lock:
            if self.replay is not None:
                self.replay.stop()
                self.replay.join(timeout=5)
            self.replay = ReplayRunner(self, name, fps, start=int(start), loop=bool(loop))
            self.replay.start()
        return self.replay_state()

    def stop_replay(self):
        with self._replay_lock:
            if self.replay is not None:
                self.replay.stop()
                self.replay.join(timeout=5)
        return self.replay_state()

    def replay_state(self):
        if self.replay is None:
            return {"running": False}
        return self.replay.snapshot()[0]

    def replay_jpeg(self):
        return None if self.replay is None else self.replay.snapshot()[1]

    # ---- single pair
    def detect_upload(self, ir_bytes, depth_bytes):
        ir, depth = decode_image(ir_bytes, "IR"), decode_image(depth_bytes, "depth")
        q = self.checker.check(ir, depth)
        result = {"quality": q.as_dict(), "image_size": {"width": ir.shape[1], "height": ir.shape[0]},
                  "detections": [], "alerts": []}
        if q.status == UNUSABLE:
            text = f"Obstacle detection unavailable: {q.reasons[0]}."
            self.events.add("upload", "system", text, 100)
            result["alerts"].append(text)
        else:
            with self.model_lock:
                res = self.detector.detect_arrays(ir, depth)
            result["detections"] = res["detections"]
            result["timing_ms"] = res["timing_ms"]
            # single image: no temporal confirmation, same wording/merging rules as the stream
            engine = AlertEngine(AlertConfig(confirm_hits=1, confirm_window=1, max_object_alerts_per_frame=3))
            for e in engine.process(time=0.0, frame_index=0, frame_id="upload", image_width=ir.shape[1],
                                    detections=res["detections"], quality=q):
                self.events.add("upload", e.kind, e.text, e.priority, e.data, "upload")
                result["alerts"].append(e.text)
        result["annotated_jpeg_base64"] = base64.b64encode(render(ir, depth, result["detections"])).decode()
        return result
