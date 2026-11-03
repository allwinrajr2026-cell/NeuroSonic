# Part 5 – Backend Explanation

## 5.1 What the backend is made of

The backend is **one Python process** started by `neurosonic_app.py`. The web server uses only Python's standard
library (`http.server.ThreadingHTTPServer`) – no Flask, Django or FastAPI.

| Layer | Files | Job |
|---|---|---|
| Start-up | `neurosonic_app.py`, `START_NEUROSONIC.ps1` | read options, create every engine, start the servers |
| Web layer | `neurosonic/server.py` | HTTPS, routing, request size limits, JSON responses, static files |
| Engines | `awareness.py`, `detectors.py`, `pathguide.py`, `tracking.py`, `events.py`, `tts.py`, `voicecmd.py`, `maps.py`, `vision/` | the actual work |
| Research | `service.py` + `woad/` | WOAD replay, IR + depth upload, event log |
| Storage | `store.py` | SQLite history and saved places |
| Security / network | `tls.py`, `netcheck.py` | local certificate authority, Windows firewall check |

## 5.2 How a request is handled

1. The phone opens a connection to port **8765**. `NeuroSonicHTTPServer` gives it its own thread
   (`ThreadingHTTPServer`, `daemon_threads = True`).
2. `finish_request()` performs the **TLS handshake in that worker thread** with a 10 s timeout
   (`TLS_HANDSHAKE_TIMEOUT`). One slow phone can therefore never freeze the whole server.
3. `do_GET` / `do_POST` call `_dispatch()`, which looks up the path in the `GET` or `POST` dictionary.
4. Unknown GET paths go to `_static()`, which serves files from `web/` and rejects path traversal (`../`).
5. The route function (`r_awareness_frame`, `r_tts`, …) does its work and replies with `_json()`.
6. Errors become proper HTTP codes: `ApiError` → its own code, bad input → **400**, voice engine failure → **503**,
   anything unexpected → **500**. A phone that disconnects is closed quietly.

## 5.3 All API endpoints

| Method and path | Purpose | Handled by |
|---|---|---|
| `GET /api/status`, `GET /api/events?since=` | app status; new alert events | `service.py` |
| `POST /api/awareness/frame?session=&mode=&describe=` | **one camera JPEG → path state, events, boxes** | `awareness.py` |
| `GET /api/awareness/status` | detector, device, FP16/FP32, frame interval, fallback reason | `awareness.py` |
| `GET /api/tts?text=`, `GET /api/tts/status` | Piper neural voice as WAV (supports HTTP Range for iPhone) | `tts.py` |
| `POST /api/voicecmd?lat=&lon=`, `GET /api/voicecmd/status` | 16 kHz WAV → text → intent | `voicecmd.py` |
| `GET /api/map/info`, `/api/map/data`, `/api/map/search?q=` | offline map information, layers, place search | `maps.py` |
| `POST /api/route` | walking route with A* | `maps.py` |
| `GET /api/history`, `GET /api/stats`, `POST /api/history/clear` | alert history | `store.py` |
| `GET/POST /api/places`, `POST /api/places/delete` | saved places | `store.py` |
| `POST /api/alerts` | log a client-side alert (navigation, simulation) | `service.py` |
| `POST /api/voice/report`, `GET /api/voice/reports` | phone reports whether audio played | `server.py` |
| `GET /api/vision/status`, `POST /api/vision/describe?consent=1` | optional online description | `vision/assistant.py` |
| `POST /api/replay/start`, `/stop`, `GET /api/replay/state`, `/frame.jpg` | WOAD replay of recorded frames | `service.py` → `woad/` |
| `POST /api/detect` | one IR + depth pair → WOAD detections | `service.py` → `woad/` |

A second, plain-HTTP server on port **8766** (`make_setup_server`) serves only the setup page and the local CA
certificate, so the iPhone can trust the HTTPS server once.

## 5.4 Concurrency – who runs where

| Thread | What runs on it |
|---|---|
| Main thread | `serve_forever()` accepts connections |
| One thread per connection | handshake, routing, JSON, Piper synthesis, Vosk recognition, routing |
| `neurosonic-infer` (exactly one) | every RF-DETR / SSDLite inference (`ThreadPoolExecutor(max_workers=1)`) |
| Replay thread (`service.py`) | WOAD replay frames |
| Setup server thread | port 8766 |

A lock (`self._lock`) and the single inference thread mean two phones never use the GPU model at the same time.

## 5.5 Data stored and privacy

`store.py` keeps **text only** in `data/neurosonic.sqlite3`: alert history (time, source, kind, sentence) and saved
places. **No camera image is stored**: frames are decoded in memory and discarded. GPS positions stay on the phone;
only the start and end points of a requested route are sent to the laptop.

# Part 6 – Frontend Explanation

## 6.1 Technology

Plain **HTML, CSS and JavaScript modules** (`<script type="module">`), with no framework and no build step. The
page is served by the laptop and runs in Safari on the iPhone.

| File | Job |
|---|---|
| `web/index.html` | all screens: Home (camera awareness), Navigate, History, Settings |
| `web/style.css` | high-contrast dark theme, large buttons, iPhone safe areas |
| `web/js/app.js` | the controller: tabs, camera loop, voice commands, navigation, history |
| `web/js/speech.js` | `SpeechQueue` (priorities, de-duplication, stale-dropping) and `Announcer` (plays Piper WAV, browser voice as backup) |
| `web/js/nav.js` | GPS maths: distance, bearing, compass words, route following, off-route detection |
| `web/js/mapview.js` | draws the offline map and route on a canvas |
| `web/js/recorder.js` | records the microphone and converts it to 16 kHz mono WAV for Vosk |
| `web/js/eventsim.js` | simulated events for demonstrations and tests |

## 6.2 Camera loop on the phone – app.js

1. **Start** → `startAwareness()` asks for the rear camera (`facingMode: "environment"`, 640 × 480).
2. `awarenessStep()` runs every `recommended_frame_ms` (200 ms GPU / 400 ms CPU):
   - skip while the page is hidden; after 4 s without a picture say "camera unavailable";
   - draw the video into a **320-pixel-wide canvas**, encode **JPEG quality 0.7**;
   - `POST /api/awareness/frame`, cancelled after **5 s** by an `AbortController`;
   - only one request is ever in flight; the next one is scheduled in `finally`.
3. With the answer: `drawAwareness()` draws the path trapezoid and boxes, `setPathState()` changes the large coloured
   card, and `voice.say(text, category, …)` speaks the events.
4. Three errors in a row → "Cannot reach the laptop for camera analysis".

## 6.3 Speech priorities – speech.js

| Category | Priority | Interrupts? | Dropped if older than |
|---|---|---|---|
| `urgent` ("Stop") | 4 | yes | 2.5 s |
| `system` | 3 | yes | 15 s |
| `obstacle` | 2 | yes | 4 s |
| `motion`, `navigation`, `scene` | 1 | no | 3 s / 15 s / 30 s |
| `info`, `description` | 0 | no | 10 s / 3 s |

Messages with the same `key` (e.g. `"path"`) replace each other in the queue, so an out-of-date "Caution" is never
spoken after the path became clear. Fixed warning sentences are fetched in advance so "Stop" is not delayed.

## 6.4 Accessibility features in the code

- Screen-reader labels (`aria-label`) on every section and button; large touch targets.
- Everything important is **spoken**, not only shown.
- High-contrast colours: green = appears clear, orange = caution, red = stop, grey = uncertain.

# Part 7 – GPU and Python Environment

## 7.1 Hardware

| Item | Value |
|---|---|
| GPU | NVIDIA GeForce RTX 4050 Laptop GPU, 6 GB (6141 MiB), driver 592.82 |
| CPU / RAM | AMD Ryzen 7 7840HS (8 cores / 16 threads), about 16 GB |
| OS | Windows 11 |

## 7.2 Two Python environments (both Python 3.12.10)

| | `.venv-gpu` (normal use) | `.venv` (CPU-only) |
|---|---|---|
| PyTorch | `2.15.0+cu132` (CUDA 13.2) | `2.15.0+cpu` |
| torchvision | `0.29.1+cu132` | `0.29.2` |
| Extra | `rfdetr 1.11.2` | – |
| `torch.cuda.is_available()` | **True** | False |
| Camera detector | RF-DETR Nano, GPU, FP16 | SSDLite, CPU |
| Started by | `START_NEUROSONIC.ps1` | `START_NEUROSONIC.ps1 -Cpu` |

Shared packages (from `requirements.txt`): NumPy 2.5.4, OpenCV 5.0, piper-tts 1.8.0, onnxruntime 1.31.1, vosk
0.3.45, google-genai 2.34.0 (optional).

## 7.3 How to check the GPU in front of the faculty

```powershell
..\.venv-gpu\Scripts\python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# 2.15.0+cu132 True NVIDIA GeForce RTX 4050 Laptop GPU
nvidia-smi          # shows the python.exe process using GPU memory while the app runs
```

In the app: open `https://<laptop-ip>:8765/api/awareness/status` and show `"device": "cuda"`, `"precision": "fp16"`,
`"recommended_frame_ms": 200`.

## 7.4 Two GPU details worth mentioning

- **CPU threads limited to 2** while the GPU runs: PyTorch's default 8 idle threads were spinning, measured 712 % of
  one core vs 121 % with 2 threads, at the same latency.
- **Low-power state:** at 5 frames per second the laptop GPU drops to its lowest clock between frames, so paced
  latency (53 ms FP16) is higher than a back-to-back benchmark (17 ms). FP16 reduces this penalty.
