"""Create the fake microphone (WAV) and fake camera (Y4M) files used by tests/js/ui_final_cdp.mjs.

  fake_mic.wav  1 s silence + Piper (noise off) saying the command + 3 s silence, 16 kHz mono
  fake_cam.y4m  640x480 I420 video made from detec_test frames that contain people

  python tools/make_e2e_media.py --out <folder> [--command "navigate to Katpadi Junction"]
"""
import argparse
import io
import sys
import wave
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_final_integration import speech16k  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--command", default="navigate to Katpadi Junction")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    w = wave.open(io.BytesIO(speech16k(a.command)))
    speech = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    x = np.concatenate([np.zeros(16000, np.int16), speech, np.zeros(48000, np.int16)])
    with wave.open(str(a.out / "fake_mic.wav"), "wb") as o:
        o.setnchannels(1), o.setsampwidth(2), o.setframerate(16000), o.writeframes(x.tobytes())
    frames = [cv2.resize(cv2.imread(str(ROOT / "demo_data" / "detec_test" / "ir" / n)), (640, 480))
              for n in ("0000030226.png", "0000060683.png")]
    with open(a.out / "fake_cam.y4m", "wb") as f:
        f.write(b"YUV4MPEG2 W640 H480 F10:1 Ip A1:1 C420jpeg\n")
        for i in range(40):
            f.write(b"FRAME\n")
            f.write(cv2.cvtColor(frames[(i // 20) % 2], cv2.COLOR_BGR2YUV_I420).tobytes())
    print(f"wrote {a.out / 'fake_mic.wav'} and {a.out / 'fake_cam.y4m'}")


if __name__ == "__main__":
    main()
