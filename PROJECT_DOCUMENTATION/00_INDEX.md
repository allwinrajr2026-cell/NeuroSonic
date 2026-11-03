# NeuroSonic: technical documentation (index)

> **Live demo video:** [https://drive.google.com/file/d/1yJS2f8_ee3ZwV55mkA9e1c6mm9f5xkYd/view?usp=sharing](https://drive.google.com/file/d/1yJS2f8_ee3ZwV55mkA9e1c6mm9f5xkYd/view?usp=sharing)

These documents describe the NeuroSonic source code as it is in this repository. Function names and line numbers
were checked against the code with an automatically generated symbol index (`SYMBOL_INDEX.md`). Measured results come
from test runs, captured API responses and the result files in `../outputs/`.

## 1. Documents

| File | Content |
|---|---|
| `01_PROJECT_OVERVIEW.md` | problem statement, objectives, status vocabulary (implemented / automated-tested / browser-E2E / simulated / physically verified), safety position |
| `02_SYSTEM_ARCHITECTURE.md` | deployment and sequence diagrams, start-up sequence, design decisions |
| `03_MODULE_REFERENCE.md` | every major Python and JavaScript module: problem, technology, input/output, algorithm, functions with line numbers, flow, excerpt |
| `04_OFFLINE_MAP_AND_ROUTING.md` | OpenStreetMap data, map package build, place search, A\* routing and its verification |
| `05_GPS_AND_ROUTE_FOLLOWING.md` | Geolocation API, stale-fix guard, route following, off-route detection, re-routing |
| `06_SPEECH_RECOGNITION_VOSK.md` | Vosk/Kaldi, recorder, two-pass recognition, intent parser, place matching, measured accuracy |
| `07_TEXT_TO_SPEECH_PIPER.md` | Piper/VITS voice, cache, byte ranges, iOS playback, fallback, measurements |
| `08_RGB_OBJECT_DETECTION_SSDLITE.md` | SSDLite320-MobileNetV3 (CPU fallback detector), obstacle classes, carrying modes |
| `09_WOAD_MODEL.md` | WOAD two-stream transformer-fusion architecture, inputs, classes, equivalence, evaluation |
| `10_API_REFERENCE.md` | all 28 HTTP endpoints with parameters, captured responses and error codes |
| `11_DATA_STORAGE.md` | SQLite schema, caches, TLS files, browser settings, privacy |
| `12_HTTPS_NETWORK_IPHONE.md` | local certificate authority, TLS robustness, firewall, iOS measures, security |
| `13_DEPENDENCIES_MODELS_LICENCES.md` | packages, models, sizes, sources, licences and their implications |
| `14_TESTING_AND_RESULTS.md` | test levels, per-module counts, browser end-to-end results, bugs found, what is not yet proven |
| `15_LIMITATIONS_AND_FUTURE_WORK.md` | limitations and prioritised future work |
| `16_PRODUCT_REFINEMENT.md` | walking-path states, object description, voice pacing, GPS quality, iPhone interface |
| `17_ONLINE_VISION.md` | optional online scene description (cloud, opt-in, provider-independent) |
| `PROJECT_DEMO_EXISTING_VS_PROPOSED.md` | differentiation: base-paper WOAD work vs. this implementation vs. proposed work |
| `SYMBOL_INDEX.md` | generated index of all classes and functions with line ranges |

Related documents:

* `../docs/NEUROSONIC_FINAL_TECHNICAL_DOCUMENTATION.md`: architecture, RF-DETR selection, tracking and events, tests,
  measured results, screenshots.
* `../docs/PHASE1_GPU_DETECTOR_BENCHMARK.md`, `../docs/EVALUATION.md`: detector benchmark and WOAD evaluation.
* `../docs/IPHONE_VALIDATION_PROTOCOL.md`: planned iPhone and field validation (23 scenarios × 5 trials).
* `../publication/`: manuscript, slides, testing report, installation guide, user guide.
* `../submission/`: university review documents (PDF), including the final consolidated report.

## 2. Key source files

| File | Main parts |
|---|---|
| `neurosonic_app.py` | `main`: start-up order of all engines |
| `neurosonic/server.py` | routing tables, `NeuroSonicHTTPServer.finish_request` (per-connection TLS), `_send_media` |
| `neurosonic/awareness.py` | `RGBAwareness.process_frame`: the live camera pipeline |
| `neurosonic/detectors.py` | `RFDETRDetector` (GPU, FP16), `SSDLiteDetector` (CPU), `FallbackDetector`, `make_detector` |
| `neurosonic/pathguide.py` | `assess_frame` (per-frame path level), `PathGuide.update` (confirmed states, announcements) |
| `neurosonic/tracking.py`, `events.py` | camera-motion estimate, ByteTrack-style tracker, entering / crossing events |
| `woad/arch/yolo.py` | `Model._forward_once`: cross-modal transformer fusion |
| `woad/alerts.py` | `AlertConfig`, `AlertEngine.process` |
| `neurosonic/tts.py`, `voicecmd.py`, `maps.py` | Piper synthesis, Vosk intents, A\* routing |
| `web/js/app.js`, `speech.js`, `nav.js` | camera loop, speech priority queue, route following |

## 3. Commands

```powershell
# tests (about 1.5 min)
..\.venv-gpu\Scripts\python -m unittest discover -s tests -t .

# app: laptop only (http://127.0.0.1:8765)
..\.venv-gpu\Scripts\python neurosonic_app.py

# app: phone on the same Wi-Fi (one-time CA install: see 12_HTTPS_NETWORK_IPHONE.md)
..\.venv-gpu\Scripts\python neurosonic_app.py --host 0.0.0.0 --https
#   phone: https://<laptop-ip>:8765    one-time setup page: http://<laptop-ip>:8766
```

## 4. Main limitations (details in `15_LIMITATIONS_AND_FUTURE_WORK.md`)

1. iPhone checks so far are informal (2.5–4.8 fps, 217–372 ms camera → answer over Wi-Fi); no formal outdoor
   or user validation yet.
2. The phone depends on the laptop over local Wi-Fi; there is no standalone phone mode.
3. The camera detectors are general COCO models: no steps, kerbs or holes, and no distance.
4. WOAD needs the CS30 near-IR + depth sensor, so it runs on recordings only; person AP@0.5 is 0.17–0.22 on the
   published data, and the authors' 0.669 mAP could not be verified.
5. Spoken place names are unreliable (10/24 correct on synthetic speech), so destinations are confirmed first.
6. OpenStreetMap data for Vellore is sparse (few named streets, no pavements or crossings).
7. There is no authentication on the local-network API.
8. iOS suspends web pages when the screen locks, so background guidance would need a native app.
