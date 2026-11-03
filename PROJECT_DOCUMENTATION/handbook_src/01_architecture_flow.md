# Part 1 – Project Architecture Overview

## 1.1 What the system is

NeuroSonic has two halves that talk over the home Wi-Fi:

- **iPhone (thin client).** Safari opens a web page served by the laptop. The page uses the phone's rear camera,
  microphone, GPS and speaker. It does almost no computing; it captures, sends, displays and speaks.
- **Laptop (server).** One Python program, `neurosonic_app.py`, runs the web server and every engine: AI object
  detection (RF-DETR Nano on the NVIDIA RTX 4050 GPU, SSDLite on the CPU as fallback), walking-path rules, tracking,
  neural speech (Piper), speech recognition (Vosk), offline map routing (A*), history (SQLite), and an optional online
  scene description (Google Gemini). It also contains the re-implemented base-paper model, **WOAD**.

All local functions work **without internet**. Only the optional Gemini description needs it.

## 1.2 Block diagram

```text
 iPhone Safari  (web/index.html + web/js/*.js)                    Laptop  (neurosonic_app.py)
 ─────────────────────────────────────────────                    ──────────────────────────────────────────────
 camera ─ 320 px JPEG every 200 ms ── HTTPS POST ──────────────►  server.py  r_awareness_frame
                                                                   └► awareness.py  RGBAwareness.process_frame
                                                                        ├ quality()          brightness check
                                                                        ├ detectors.py       RF-DETR (GPU, FP16) / SSDLite (CPU)
                                                                        ├ tracking.py        camera motion + ByteTracker
                                                                        ├ pathguide.py       5 path states
                                                                        └ events.py          entering / crossing
                         ◄──────────── JSON (state, events, boxes) ─┘
 speaker ◄── WAV ───────────────────── GET /api/tts?text= ───────  tts.py  (Piper neural voice, cached)
 mic ── 16 kHz WAV ─────────────────── POST /api/voicecmd ───────►  voicecmd.py  (Vosk) → intent + place
 GPS (stays on phone) ── from/to ───── POST /api/route ──────────►  maps.py  (A* on offline Vellore graph)
 History screen ◄───────────────────── GET /api/history ─────────  store.py  (SQLite, text only)
 "Describe" (opt-in) ── 1 photo ────── POST /api/vision/describe ►  vision/assistant.py → vision/gemini.py (internet)
 Research tools ────────────────────── /api/replay/*, /api/detect ► service.py → woad/*  (base-paper WOAD model)
```

## 1.3 Folder map (only the important files)

| Folder / file | What it contains |
|---|---|
| `neurosonic_app.py` | Entry point: reads command-line options, starts every engine and the server |
| `neurosonic/server.py` | Web server, all API routes, HTTPS handling |
| `neurosonic/awareness.py` | Live camera pipeline (one frame in, path state and events out) |
| `neurosonic/detectors.py` | RF-DETR Nano (GPU, FP16) and SSDLite (CPU) detectors, automatic fallback |
| `neurosonic/pathguide.py` | Walking-path region and the five path states |
| `neurosonic/tracking.py` | Camera-motion estimate and ByteTrack-style object tracker |
| `neurosonic/events.py` | "Moving into your path" and "crossing in front" rules |
| `neurosonic/tts.py`, `voicecmd.py`, `maps.py` | Piper voice, Vosk voice commands, offline map and A* routing |
| `neurosonic/store.py`, `service.py` | SQLite history; WOAD replay/upload service and event log |
| `neurosonic/tls.py`, `netcheck.py` | Local certificate authority for HTTPS; Windows firewall check |
| `neurosonic/vision/` | Optional online scene description: `assistant.py`, `gemini.py`, `base.py`, `mock.py` |
| `woad/` | Base-paper WOAD model: loader, network (`arch/`), preprocessing, quality gate, alert engine |
| `web/` | Frontend: `index.html`, `style.css`, `js/app.js`, `speech.js`, `nav.js`, `mapview.js`, `recorder.js`, `eventsim.js` |
| `tools/` | Benchmarks, evaluation, soak test, figure and map builders (not used by the running app) |
| `tests/` | 204 Python tests (including Node.js tests for the JavaScript) and browser tests |
| `START_NEUROSONIC.ps1`, `STOP_NEUROSONIC.ps1` | Start and stop the server as a background process |
| `models/`, `weights/`, `maps/vellore/` | Model files (binary), WOAD checkpoint copy, offline map data |

**Frameworks actually used:** PyTorch (with torchvision and the `rfdetr` package), OpenCV, NumPy, ONNX Runtime (only
inside Piper), Vosk, and the optional `google-genai`. **TensorFlow is not used**: it is not installed in either Python
environment and no project file imports it. The web server uses only Python's standard library (`http.server`), and
the frontend is plain JavaScript with no framework.

# Part 2 – Complete Application Execution Flow

## 2.1 The ten steps from start-up to spoken warning

1. **The application starts.** `START_NEUROSONIC.ps1` runs
   `..\.venv-gpu\Scripts\python.exe neurosonic_app.py --host 0.0.0.0 --https` as a background process (through Windows
   WMI, so it keeps running when the terminal closes) and writes a log to `logs\neurosonic_<time>.log`.
2. **The Python environment is chosen.** `.venv-gpu` contains PyTorch 2.15.0 built for CUDA 13.2 plus `rfdetr`
   1.11.2, so the GPU detector can load. With `-Cpu` the script uses `.venv` (CPU PyTorch), and the app automatically
   uses SSDLite instead.
3. **The backend server starts** (`neurosonic_app.py` `main()`, L28):
   - `ensure_certificates()` creates or reuses the local CA and server certificate (`tls.py`);
   - `Store` opens the SQLite database; `DetectionService` loads the WOAD checkpoint;
   - `PiperTTS.warm_up()`, `OfflineMap(...)`, `VoiceCommands.warm_up()` load the voice, map and speech model;
   - `RGBAwareness.warm_up()` loads RF-DETR on the GPU (or SSDLite) and runs one blank test frame;
   - `make_provider()` and `SceneAssistant` set up the optional Gemini description (no request is made);
   - `make_server()` opens port 8765 (HTTPS), `make_setup_server()` opens port 8766 (certificate setup page);
   - it prints `NeuroSonic running: …` and the iPhone address, then `serve_forever()` waits for requests.
4. **The frontend is loaded.** The iPhone opens `https://192.168.1.5:8765`. `server.py` `_static()` sends
   `web/index.html`, `style.css` and the JavaScript modules. `app.js` calls `init()` (`/api/status`) and starts
   `pollEvents()`, and fetches `/api/awareness/status`, `/api/tts/status`, `/api/map/info`, `/api/voicecmd/status`.
5. **Camera input is received.** The user taps **Start**. `startAwareness()` (app.js L541) asks for the rear camera
   with `getUserMedia({video: {facingMode: "environment", width 640, height 480}})`.
6. **Frames are processed and sent.** Every `recommended_frame_ms` (200 ms on the GPU, 400 ms on the CPU)
   `awarenessStep()` (L580) draws the video into a 320-pixel-wide canvas, encodes JPEG (quality 0.7) and sends it with
   `fetch("/api/awareness/frame?session=…&mode=chest&describe=0", {method: "POST", body: blob})`. Only one request is
   in flight at a time; a request that takes more than 5 s is cancelled.
7. **The AI model performs detection.** `server.py` `r_awareness_frame()` (L377) reads the JPEG and calls
   `RGBAwareness.process_frame()` (awareness.py L205), which decodes it with OpenCV, checks brightness, and runs the
   detector on the single inference thread. RF-DETR Nano returns boxes, class ids and confidences; only obstacle
   classes with confidence ≥ 0.40 are kept.
8. **Results are combined and returned.** The same function estimates camera motion and updates the tracker
   (`tracking.py`), decides the walking-path state (`pathguide.py`), checks for entering/crossing events
   (`events.py`), and returns JSON: `path.state`, `events` (sentences to speak), `detections`, `tracks`, `timing`,
   `detector`. The server also adds each spoken event to the history (`service.events.add` → `store.add_alert`).
9. **The user is informed.** `app.js` draws the path region and boxes on the video, updates the large state card
   (green "Path appears clear", orange "Caution", red "Stop"), and calls `voice.say(text, category)`. `speech.js`
   puts the sentence in a priority queue, fetches the Piper audio from `/api/tts?text=…` and plays it. A "Stop"
   message (category `urgent`) interrupts lower-priority speech such as a navigation instruction.
10. **Other features run alongside.**
    - **Voice commands:** the 🎤 Speak button records 16 kHz WAV (`recorder.js`) → `/api/voicecmd` → Vosk text →
      intent (e.g. `navigate` + place).
    - **Navigation:** place search `/api/map/search`, route `/api/route` (A*), then `nav.js` `followRoute()` turns GPS
      positions into spoken turn instructions.
    - **History:** every spoken alert is stored as text in SQLite and shown on the History screen.
    - **Online description (opt-in):** one photo → `/api/vision/describe` → Gemini → filtered spoken sentence.

## 2.2 What one camera frame costs (measured on the laptop)

| Measurement (laptop browser with a fake camera; Wi-Fi not included) | Result |
|---|---|
| Frames sent per second with the GPU detector | 4.91–4.95 |
| Camera capture → analysed answer (final code) | median 67 ms, p90 73 ms |
| Event received → speech starts (neural voice) | about 257–260 ms |
| RF-DETR Nano FP16, paced at 5 frames/s (`benchmark_precision.py`) | median 53.2 ms (FP32: 66.5 ms) |
