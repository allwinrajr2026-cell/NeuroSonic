"""Long-duration stability test of the running app (not used by the app).

Streams the recorded/composited demo clip to POST /api/awareness/frame at the phone's rate (default 5 frames/s, one
request at a time, like web/js/app.js) for --minutes, optionally with a slow online-description request running
in parallel (needs the server started with --vision-provider mock and NEUROSONIC_VISION_MOCK_SCRIPT=slow20).
Every 10 s it records: frames/s, request latency (median/p90/max), server process RSS (MiB), GPU memory and
utilisation (nvidia-smi), events seen. Writes JSON for the report.

    ..\\.venv-gpu\\Scripts\\python tools\\soak_test.py --base http://127.0.0.1:8799 --clip e2e_media\\event_cam.y4m
        --minutes 10 --server-pid <pid> --cloud-every 60 --out outputs\\benchmarks\\soak\\soak.json
"""
import argparse
import http.client
import json
import statistics
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import cv2
import numpy as np


def read_y4m(path, w=640, h=480):
    data = Path(path).read_bytes()
    _, rest = data.split(b"\n", 1)
    fs = w * h * 3 // 2
    frames = []
    while rest.startswith(b"FRAME\n"):
        rest = rest[6:]
        bgr = cv2.cvtColor(np.frombuffer(rest[:fs], np.uint8).reshape(h * 3 // 2, w), cv2.COLOR_YUV2BGR_I420)
        frames.append(cv2.imencode(".jpg", cv2.resize(bgr, (320, 240)), [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes())
        rest = rest[fs:]
    return frames


def gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().split(", ")
        return int(out[0]), int(out[1])
    except Exception:  # noqa: BLE001
        return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8799")
    ap.add_argument("--clip", required=True)
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--fps", type=float, default=5)
    ap.add_argument("--clip-fps", type=float, default=10,
                    help="the clip's own frame rate; frames are sampled by elapsed time, like the phone samples its camera")
    ap.add_argument("--server-pid", type=int, default=None)
    ap.add_argument("--cloud-every", type=float, default=0, help="seconds between parallel slow cloud requests (0 = off)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    import psutil
    proc = psutil.Process(a.server_pid) if a.server_pid else None
    u = urlparse(a.base)
    frames = read_y4m(a.clip)
    period = 1.0 / a.fps
    stop = threading.Event()
    cloud = []

    def cloud_loop():
        while not stop.wait(a.cloud_every):
            t = time.time()
            try:
                c = http.client.HTTPConnection(u.hostname, u.port, timeout=70)
                c.request("POST", "/api/vision/describe?session=soak&consent=1", frames[0], {"Content-Type": "image/jpeg"})
                r = json.loads(c.getresponse().read())
                c.close()
                cloud.append({"t": round(t, 1), "s": round(time.time() - t, 1), "ok": r.get("ok"), "code": r.get("code")})
            except Exception as e:  # noqa: BLE001
                cloud.append({"t": round(t, 1), "s": round(time.time() - t, 1), "error": type(e).__name__})
    if a.cloud_every:
        threading.Thread(target=cloud_loop, daemon=True).start()

    windows, lat, events, errors, n = [], [], 0, 0, 0
    t0 = tw = time.time()
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    if proc:
        proc.cpu_percent(None)
    while time.time() - t0 < a.minutes * 60:
        s = time.perf_counter()
        try:
            k = int((time.time() - t0) * a.clip_fps) % len(frames)
            conn.request("POST", "/api/awareness/frame?session=soak&mode=chest", frames[k],
                         {"Content-Type": "image/jpeg"})
            r = json.loads(conn.getresponse().read())
            events += sum(1 for e in r.get("events", []) if e.get("kind") == "event")
            lat.append((time.perf_counter() - s) * 1000)
        except Exception:  # noqa: BLE001
            errors += 1
            conn.close()
            conn = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
        n += 1
        time.sleep(max(0.0, period - (time.perf_counter() - s)))
        if time.time() - tw >= 10:
            gu, gm = gpu()
            ls = sorted(lat) or [0]
            windows.append({"t_s": round(time.time() - t0), "fps": round(len(lat) / (time.time() - tw), 2),
                            "lat_median_ms": round(statistics.median(ls), 1), "lat_p90_ms": round(ls[int(0.9 * (len(ls) - 1))], 1),
                            "lat_max_ms": round(ls[-1], 1), "errors": errors, "events_total": events,
                            "rss_mib": round(proc.memory_info().rss / 2 ** 20) if proc else None,
                            "cpu_pct_one_core": round(proc.cpu_percent(None), 1) if proc else None,
                            "gpu_util_pct": gu, "gpu_mem_mib": gm})
            print(json.dumps(windows[-1]), flush=True)
            lat, tw = [], time.time()
    stop.set()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    allw = windows
    summary = {"minutes": a.minutes, "frames_sent": n, "errors": errors, "events_total": events,
               "fps_mean": round(statistics.mean(w["fps"] for w in allw), 2) if allw else None,
               "lat_median_ms_first_last": [allw[0]["lat_median_ms"], allw[-1]["lat_median_ms"]] if allw else None,
               "lat_p90_ms_max": max(w["lat_p90_ms"] for w in allw) if allw else None,
               "rss_mib_first_last_max": [allw[0]["rss_mib"], allw[-1]["rss_mib"], max(w["rss_mib"] or 0 for w in allw)] if allw and proc else None,
               "gpu_mem_mib_first_last": [allw[0]["gpu_mem_mib"], allw[-1]["gpu_mem_mib"]] if allw else None,
               "cloud_requests": cloud}
    a.out.write_text(json.dumps({"summary": summary, "windows": windows}, indent=1), encoding="utf-8")
    print("SUMMARY", json.dumps(summary))


if __name__ == "__main__":
    main()
