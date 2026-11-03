"""Replay recorded IR + depth frames through the detector and the alert engine; write an alert transcript.

Stage 2 of the roadmap: text alerts only (no speech yet). Timestamps are synthetic (frame index / --fps),
so a replay is deterministic. See docs/STAGE2_ALERTS.md for the alert rules and their limits.

Examples:
  python woad_replay.py --source demo_data/detec_test --segment-gap 10
  python woad_replay.py --source demo_data/detec_test --segment-gap 10 ^
      --from-results outputs/demo_detec_test/results.json        (reuse detections: fast)

Outputs (new auto-incremented run folder, never overwritten):
  transcript.jsonl   one alert event per line (time, frame, kind, priority, text, data)
  transcript.txt     the same as readable lines
  frames.jsonl       per frame: segment, input quality, number of detections, alerts
  summary.json       source, model, settings, counts
Exit codes: 0 ok, 2 usage / pairing / checkpoint error.
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from woad import __version__  # noqa: E402
from woad.alerts import AlertConfig, AlertEngine  # noqa: E402
from woad.model_loader import DEFAULT_WEIGHTS, CheckpointError  # noqa: E402
from woad.pairing import PairingError  # noqa: E402
from woad.quality import InputQualityChecker, QualityThresholds  # noqa: E402
from woad.replay import load_cached_detections, run_replay  # noqa: E402
from woad.sources import ReplaySource  # noqa: E402
from woad_detect import increment_dir  # noqa: E402


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--source", type=Path, help="folder with ir/ and depth/")
    src.add_argument("--ir-dir", type=Path)
    ap.add_argument("--depth-dir", type=Path)
    ap.add_argument("--fps", type=float, default=5.0, help="nominal replay rate for synthetic timestamps")
    ap.add_argument("--segment-gap", type=int, default=None,
                    help="start a new clip when the filename number jumps by more than this")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--from-results", type=Path, help="reuse detections from a woad_detect.py results.json")
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--conf", type=float, default=0.25, help="detector confidence threshold")
    d = AlertConfig()
    ap.add_argument("--alert-conf", type=float, default=d.alert_conf)
    ap.add_argument("--confirm", default=f"{d.confirm_hits}/{d.confirm_window}", help="N/M frames to confirm")
    ap.add_argument("--cooldown", type=float, default=d.cooldown_s)
    ap.add_argument("--repeat", type=float, default=d.repeat_s)
    ap.add_argument("--max-alerts", type=int, default=d.max_object_alerts_per_frame)
    ap.add_argument("--project", type=Path, default=ROOT / "outputs")
    ap.add_argument("--name", default="replay")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.ir_dir and not a.depth_dir:
        ap.error("--ir-dir requires --depth-dir")
    try:
        n, m = (int(x) for x in a.confirm.split("/"))
    except ValueError:
        ap.error("--confirm must look like N/M, e.g. 2/3")
    a.alert_config = AlertConfig(alert_conf=a.alert_conf, confirm_hits=n, confirm_window=m, cooldown_s=a.cooldown,
                                 repeat_s=a.repeat, max_object_alerts_per_frame=a.max_alerts)
    return a


def main(argv=None):
    a = parse_args(argv)
    try:
        a.alert_config.validate()
        kw = dict(fps=a.fps, segment_gap=a.segment_gap, start=a.start, limit=a.limit)
        source = ReplaySource.from_root(a.source, **kw) if a.source else ReplaySource(a.ir_dir, a.depth_dir, **kw)
        detector = cached = None
        if a.from_results:
            cached, rmeta = load_cached_detections(a.from_results)
            if rmeta["settings"]["conf_thres"] > a.alert_config.alert_conf:
                raise ValueError(f"cached detections used conf {rmeta['settings']['conf_thres']} > --alert-conf")
            model = {**rmeta["model"], "detections_from": str(a.from_results)}
            det_settings = rmeta["settings"]
        else:
            from woad.detector import WOADDetector
            detector = WOADDetector(a.weights, a.device, conf_thres=a.conf)
            model, det_settings = detector.info, detector.settings()
    except (PairingError, CheckpointError, ValueError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    run = increment_dir(a.project, a.name)
    run.mkdir(parents=True)
    engine, checker = AlertEngine(a.alert_config), InputQualityChecker(QualityThresholds())
    t0 = time.perf_counter()
    quality_counts, n_frames, all_events, segments = Counter(), 0, [], set()
    with open(run / "transcript.jsonl", "w", encoding="utf-8") as ft, \
            open(run / "transcript.txt", "w", encoding="utf-8") as fx, \
            open(run / "frames.jsonl", "w", encoding="utf-8") as ff:
        for record, events in run_replay(source, engine, checker, detector=detector, cached=cached):
            n_frames += 1
            segments.add(record["segment"])
            quality_counts[record["quality"]["status"]] += 1
            ff.write(json.dumps(record) + "\n")
            for e in events:
                all_events.append(e)
                ft.write(json.dumps(e.as_dict()) + "\n")
                line = f"[{e.time:8.1f}s  #{e.frame_index:<4} {e.frame_id}] {e.text}"
                fx.write(line + "\n")
                if not a.quiet:
                    print(line)

    summary = {
        "tool": "woad_replay.py", "woad_version": __version__, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source.describe(), "model": model, "detector_settings": det_settings,
        "alert_config": vars(a.alert_config), "quality_thresholds": vars(checker.t),
        "frames": n_frames, "segments": len(segments), "quality": dict(quality_counts),
        "events": len(all_events),
        "object_alerts": sum(e.kind == "object" for e in all_events),
        "system_alerts": sum(e.kind == "system" for e in all_events),
        "alerts_by_text": dict(Counter(e.text for e in all_events).most_common()),
        "replay_duration_s": round(n_frames / a.fps, 1), "elapsed_s": round(time.perf_counter() - t0, 1),
    }
    (run / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"{n_frames} frames ({len(segments)} segments, {summary['replay_duration_s']} s at {a.fps} fps): "
          f"{summary['object_alerts']} object alerts, {summary['system_alerts']} system alerts; "
          f"quality {dict(quality_counts)}")
    print(f"results: {run}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
