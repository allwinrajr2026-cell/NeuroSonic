"""Replay pipeline: source -> quality check -> detector (or cached detections) -> alert engine."""
from pathlib import Path

from .quality import UNUSABLE


def run_replay(source, engine, checker, detector=None, cached=None):
    """Yields (frame_record, events) per frame.

    detector: WOADDetector (runs the model) or None when `cached` is given.
    cached:   {ir_filename: detections} from a previous woad_detect.py results.json (fast, deterministic replays).
    Frames whose input is UNUSABLE are not passed to the detector (their detections would not be trusted).
    """
    if (detector is None) == (cached is None):
        raise ValueError("give exactly one of detector / cached")
    for frame in source:
        q = checker.check(frame.ir, frame.depth)
        dets, err = None, frame.error
        if err is None and q.status != UNUSABLE:
            if cached is not None:
                dets = cached.get(frame.frame_id)
                if dets is None:
                    err = f"no cached detections for {frame.frame_id}"
            else:
                dets = detector.detect_arrays(frame.ir, frame.depth)["detections"]
        width = frame.ir.shape[1] if frame.ir is not None else 640
        events = engine.process(time=frame.timestamp, frame_index=frame.index, frame_id=frame.frame_id,
                                image_width=width, detections=dets, quality=q,
                                segment_start=frame.segment_start, error=err)
        record = {"frame_index": frame.index, "frame_id": frame.frame_id, "time": round(frame.timestamp, 3),
                  "segment": frame.segment, "segment_start": frame.segment_start, "quality": q.as_dict(),
                  "error": err, "detections": None if dets is None else len(dets),
                  "events": [e.text for e in events]}
        yield record, events


def load_cached_detections(results_json):
    """{ir filename: detections} from a woad_detect.py results.json, plus its metadata."""
    import json
    meta = json.loads(Path(results_json).read_text(encoding="utf-8"))
    cached = {}
    for r in meta["results"]:
        name = Path(r["ir_path"].replace("\\", "/")).name
        cached[name] = r["detections"]
    return cached, meta
