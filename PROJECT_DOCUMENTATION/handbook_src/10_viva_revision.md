# Part 10 – Faculty Viva Questions and Answers

## 10.1 Project and architecture

**Q1. What problem does NeuroSonic solve?** It gives a blind or low-vision walker spoken, calm information about
the walking path ahead (clear, caution, stop), people or vehicles moving into the path, offline walking directions,
and an optional scene description. It is a research prototype, not a safety device.

**Q2. Why does the phone not run the AI itself?** The laptop GPU runs RF-DETR in about 53 ms per frame. The phone is a
thin client: camera, microphone, GPS, speaker and display. This keeps the phone app a plain web page with no install.

**Q3. Why a web app instead of a native iOS app?** No App Store, no Mac needed to build it, and the same code runs on
any phone. iPhones allow camera, microphone and GPS on HTTPS pages, which is why `tls.py` creates a local certificate
authority.

**Q4. Which framework is the backend?** Python's standard library `http.server` (`ThreadingHTTPServer`). No Flask or
FastAPI – fewer dependencies and full control over TLS handshakes and timeouts.

**Q5. Does it need internet?** No, except for the optional Gemini description. Detection, voice, speech recognition,
maps and routing all run on the laptop.

## 10.2 AI and models

**Q6. Which model detects obstacles?** RF-DETR Nano (COCO-pretrained) on the RTX 4050 in FP16, with SSDLite320-
MobileNetV3 on the CPU as automatic fallback.

**Q7. Did you train a model?** No. Both use public COCO weights. We benchmarked candidates and chose by accuracy,
speed and licence.

**Q8. What is the difference between RF-DETR and YOLO/SSD?** RF-DETR is a detection transformer: object queries each
predict one object, so no NMS is needed. SSD and YOLO predict many overlapping candidate boxes and remove duplicates
with non-maximum suppression.

**Q9. What is FP16 and does it reduce accuracy?** 16-bit floating point. In our test the person AP@0.5 was 0.6600
(FP16) vs 0.6597 (FP32), and paced latency dropped from 66.5 to 53.2 ms.

**Q10. What happens if the GPU is not available?** `make_detector()` falls back to SSDLite on the CPU and the phone
sends a frame every 400 ms instead of 200 ms. If RF-DETR fails mid-session, `FallbackDetector` switches and
re-analyses the same frame.

**Q11. What is the confidence threshold?** 0.40 for both detectors.

**Q12. Can it measure distance?** No. A single RGB camera has no depth; the app never states a distance.

**Q13. Can it see steps, kerbs and potholes?** No. COCO has no such classes. This is a stated limitation.

**Q14. What is the base paper's model and why isn't it used live?** WOAD fuses near-infrared and depth images with a
transformer. It needs the CS30 sensor, not a phone camera. We reproduced it on Windows (identical output) and measured
person AP@0.5 0.218 on the published data.

## 10.3 Algorithms

**Q15. How do you decide "path blocked"?** A trapezoid in the lower centre of the image is the path. If an object
covers ≥ 30 % of it (centred) in 2 of the last 3 frames, the state is BLOCKED. CLEAR needs 3 clear frames.

**Q16. Why not announce every object?** Too much speech is dangerous and tiring. Only state changes and specific
events are spoken, with priorities and cooldowns.

**Q17. How do you separate the user's own movement from object movement?** `tracking.py` tracks background corner
points with Lucas–Kanade optical flow and fits a similarity transform with RANSAC; object motion is measured relative
to that.

**Q18. What tracker do you use?** A small own implementation of the ByteTrack idea: match confident detections first,
then low-confidence ones to existing tracks, by IoU within the same class.

**Q19. What is IoU?** Intersection over union – overlap area divided by the combined area of two boxes.

**Q20. How does navigation work offline?** `maps.py` loads a local OpenStreetMap extract of Vellore and runs A* on
the walking graph; `nav.js` turns GPS positions into spoken turn instructions.

## 10.4 Engineering and testing

**Q21. What was the hardest bug?** Server memory grew about 2 MiB/s because the GPU model ran on ever-new request
threads. Moving all inference onto one dedicated thread fixed it (10-minute soak: 0 errors, flat memory).

**Q22. How do you know it works?** 204 automated tests, 7 browser tests with a fake camera, benchmarks and a soak test.
Physical iPhone and street tests are still pending.

**Q23. How is privacy protected?** Camera images are processed in memory and never stored; history keeps text only;
GPS stays on the phone; the Gemini key stays on the laptop; online description needs explicit consent.

**Q24. What would you do next?** Field tests with the iPhone, tests with visually impaired users, a model trained for
kerbs, steps and poles, and depth estimation for distance.

# Part 11 – Quick Revision Sheet

## 11.1 Numbers to remember

| Item | Value |
|---|---|
| Live detector | **RF-DETR Nano**, RTX 4050, **FP16**, 384 px input |
| Fallback | **SSDLite320-MobileNetV3**, CPU, 320 px |
| Confidence threshold | **0.40** |
| Frame interval | **200 ms GPU** (5 fps) / 400 ms CPU |
| Phone upload | **320 px wide JPEG, quality 0.7**, 5 s timeout, one request at a time |
| Latency | RF-DETR paced **53.2 ms** (FP32 66.5); camera → answer median **67 ms** |
| Accuracy (near-IR set) | person AP@0.5 RF-DETR **0.660**, SSDLite 0.542 |
| Path states | CLEAR_VIEW, POSSIBLE_OBSTACLE, BLOCKED_VIEW, UNCERTAIN, CAMERA_UNAVAILABLE |
| Confirmation | BLOCKED 2 of 3 frames; CLEAR 3 frames |
| Tests | **204** Python tests OK, **7/7** browser tests |
| Soak test | 10 min, 2,980 frames, **0 errors** |
| WOAD reproduction | output identical (diff 0.0); person AP@0.5 **0.218** |
| Ports | **8765** HTTPS app, **8766** setup page |
| Environment | Python 3.12.10, torch 2.15.0+cu132, CUDA 13.2, rfdetr 1.11.2 |

## 11.2 The pipeline in one line

**Phone camera → 320 px JPEG → HTTPS POST `/api/awareness/frame` → `server.py` → `awareness.py` (quality check →
RF-DETR on GPU → tracking with camera-motion compensation → path state → events) → JSON → `app.js` draws and
`speech.js` speaks with Piper voice from `/api/tts`.**

## 11.3 Which file does what

| If asked about … | Show this file |
|---|---|
| Start-up | `neurosonic_app.py`, `START_NEUROSONIC.ps1` |
| API / server | `neurosonic/server.py` |
| Camera pipeline | `neurosonic/awareness.py` |
| AI model, GPU, FP16 | `neurosonic/detectors.py` |
| Clear / caution / stop | `neurosonic/pathguide.py` |
| Moving objects | `neurosonic/tracking.py`, `neurosonic/events.py` |
| Voice out / voice in | `neurosonic/tts.py` (Piper), `neurosonic/voicecmd.py` (Vosk) |
| Maps and routing | `neurosonic/maps.py`, `web/js/nav.js` |
| History | `neurosonic/store.py` |
| HTTPS on iPhone | `neurosonic/tls.py` |
| Online description | `neurosonic/vision/assistant.py`, `gemini.py` |
| Base paper | `woad/` |
| Phone UI | `web/index.html`, `web/js/app.js`, `web/js/speech.js` |
| Tests / benchmarks | `tests/`, `tools/` |

## 11.4 Honest limitations (always say them)

1. Not a safety device; does not replace a cane or guide dog.
2. No distance; no steps, kerbs, potholes, poles or walls.
3. Forward camera view only, not 360 degrees.
4. Thresholds not validated with users; no iPhone field test yet.
5. Accuracy measured on near-IR images, not phone photos.

## 11.5 Demo checklist

1. `START_NEUROSONIC.ps1` → log shows `Camera awareness: RF-DETR Nano (Roboflow, COCO, 384 px) on the NVIDIA GPU ready (cuda; frame interval 200 ms; …)`.
2. iPhone Safari → `https://<laptop-ip>:8765` → Start → point at a person → "Caution" / "Stop" is spoken.
3. Show `/api/awareness/status`: `cuda`, `fp16`.
4. `nvidia-smi` shows python.exe on the GPU.
5. Speak "navigate to …" → route is spoken.
6. History tab shows the spoken alerts.
