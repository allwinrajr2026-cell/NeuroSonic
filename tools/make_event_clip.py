"""Make a short demonstration video for the event pipeline (not used by the app).

A real person (riding a bicycle, so detectors report a person and a bicycle) cut from a recorded detec_test frame (0000060683.png) moves from left to right across a real recorded
empty background frame (0000000023.png, in which RF-DETR detects nothing); the camera is still. This is a synthetic
COMPOSITION of real recorded pixels, made only to exercise detection -> tracking -> event -> speech end to end in a
browser test (Chrome's fake camera plays the .y4m file). It is not field evidence.

    ..\\.venv-gpu\\Scripts\\python tools\\make_event_clip.py --out e2e_media
"""
import argparse
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
IR = ROOT / "demo_data" / "detec_test" / "ir"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "e2e_media")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--fps", type=int, default=10)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    bg = cv2.resize(cv2.imread(str(IR / "0000000023.png")), (640, 480))
    src = cv2.imread(str(IR / "0000060683.png"))
    x1, y1, x2, y2 = 229, 160, 342, 385                  # the person in that frame (RF-DETR box, rounded)
    person = src[y1:y2, x1:x2]
    ph, pw = person.shape[:2]
    n = int(a.seconds * a.fps)
    hold = a.fps                                          # 1 s of empty scene first (path becomes clear)
    with open(a.out / "event_cam.y4m", "wb") as f:
        f.write(f"YUV4MPEG2 W640 H480 F{a.fps}:1 Ip A1:1 C420jpeg\n".encode())
        for i in range(n):
            frame = bg.copy()
            if i >= hold:
                k = (i - hold) / max(1, n - hold - 1)
                x = int(-pw * 0.3 + k * (640 - pw * 0.4))  # from the left edge to the right side
                y = 480 - ph - 20
                xa, xb = max(0, x), min(640, x + pw)
                frame[y:y + ph, xa:xb] = person[:, xa - x:xb - x]
            f.write(b"FRAME\n")
            f.write(cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420).tobytes())
    print(f"wrote {a.out / 'event_cam.y4m'} ({n} frames, {a.fps} fps, person walks left -> right)")


if __name__ == "__main__":
    main()
