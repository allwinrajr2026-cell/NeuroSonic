# Part 8 – Testing and Benchmarking

## 8.1 Automated tests (summary of Part 3, F5)

| Kind | Count / result | How |
|---|---|---|
| Python unit and integration tests | **204 tests, OK** (3 Nov 2026) in `.venv-gpu` (1 skipped: live Gemini) and `.venv` (3 skipped: GPU-only) | `python -m unittest discover -s tests -t .` |
| JavaScript logic tests | run inside the Python suite through Node.js (`test_web_js.py`) | speech queue, navigation maths, GPS states |
| Browser tests | **7 of 7 pass** | headless Chrome, iPhone screen size, fake camera and microphone |
| Offline checks | several tests forbid every non-local network connection | proves voice, map and routing work offline in-process |

## 8.2 Benchmarks and what they proved

| Benchmark (tool) | Data | Key result |
|---|---|---|
| Detector choice (`benchmark_detectors.py`) | 365 near-IR validation images, 129 people | RF-DETR Nano person AP@0.5 **0.660** vs SSDLite 0.542; RF-DETR 21.3 ms on GPU (FP32) |
| FP16 vs FP32 (`benchmark_precision.py`) | same images; 320×240 frames paced at 5 fps | same accuracy (0.6600 vs 0.6597); median **53.2 vs 66.5 ms** |
| Stability (`soak_test.py`) | demo clip, 10 minutes, 5 fps | 2,980 frames, **0 errors**, 4.97 fps, flat memory after the one-thread fix |
| End-to-end in browser | laptop Chrome, fake camera | camera → answer median **67 ms**; event → speech about 260 ms |
| WOAD reproduction (`evaluate.py`, `verify_equivalence.py`) | published WOAD dataset | copy identical to original (max difference 0.0); person AP@0.5 **0.218** |

## 8.3 Detector comparison (Phase 1, RTX 4050)

| Detector | Device | Median latency | Person AP@0.5 | Recall @ 0.40 | Licence |
|---|---|---|---|---|---|
| SSDLite320 | CPU | 43.7 ms | 0.542 | 0.574 | BSD-3 |
| **RF-DETR Nano** | **GPU** | **20.6 ms** | **0.660** | **0.729** | Apache-2.0 |
| YOLO26n | GPU | 11.8 ms | 0.619 | 0.628 | AGPL-3.0 |
| YOLO26s | GPU | 11.4 ms | 0.628 | 0.651 | AGPL-3.0 |

**Why RF-DETR and not the faster YOLO26?** Highest accuracy and recall (missing a person is the worst error for a blind
user), fast enough for 5 frames per second, and a permissive licence.

## 8.4 What is NOT yet tested (say this honestly)

- No test on the **physical iPhone** while walking; no field test on Vellore streets.
- No test with **blind or low-vision users**; thresholds are engineering defaults.
- No test with the Wi-Fi physically disconnected (only in-process network blocking).
- Accuracy numbers come from near-IR images, the only labelled data available, not from phone photos.
- Soak test was 10 minutes; a run of an hour or more is pending.

# Part 9 – Important Code Snippets Explained Line by Line

## 9.1 Server start-up – `neurosonic_app.py`

```python
store = Store(a.db)                                         # 1
service = DetectionService(store, a.weights, a.device)      # 2
tts = PiperTTS(a.voice_model, cache_dir=ROOT / "data" / "tts_cache")
if tts.warm_up(): ...                                       # 3
awareness = RGBAwareness(a.rgb_weights,
        detector=a.detector or os.environ.get("NEUROSONIC_DETECTOR") or "auto",
        events=not a.no_events)                             # 4
if awareness.warm_up(): ...                                 # 5
httpd = make_server(service, store, a.host, a.port, ssl_context=ctx, tts=tts,
        offline_map=offline_map, voicecmd=voicecmd, awareness=awareness, vision=vision)  # 6
```

1. Open (or create) the SQLite database for history and places.
2. Load the WOAD checkpoint for the research screens (hash-checked).
3. Load the Piper voice; if it fails the app still runs and the phone uses its built-in voice.
4. Create the camera pipeline. The detector choice comes from `--detector`, then the environment variable, else `auto`.
5. Warm-up runs one detection on a black image, so the first real frame is not slow and errors appear at start-up.
6. Every engine is handed to the server ("dependency injection"); the server itself creates nothing.

## 9.2 Routing – `server.py` `_dispatch`

```python
url = urlparse(self.path)                  # 1  split "/api/tts?text=hi" into path and query
fn = routes.get(url.path)                  # 2  look up the handler in the GET or POST table
if fn is None:
    if self.command in ("GET", "HEAD"):
        return self._static(url.path)      # 3  not an API path: serve a file from web/
    raise ApiError(404, "not found")
fn(self, url)                              # 4  run the handler
except (InvalidInput, ValueError) as e:
    self._json({"error": str(e)}, 400)     # 5  bad input -> clear error, server keeps running
```

## 9.3 Camera frame endpoint – `server.py` `r_awareness_frame`

```python
jpg = self._raw_body(3 * 1024 * 1024, {"image/jpeg", "application/octet-stream"})   # 1
session = (q.get("session", ["default"])[0] or "default")[:64]                       # 2
res = awareness.process_frame(jpg, session=f"{self.client_address[0]}:{session}",
                              mode=mode, describe=describe)                           # 3
for e in res["events"]:
    if e["kind"] in ("object", "path", "event"):
        service.events.add("awareness", e["kind"], e["text"], e["priority"], e["data"], "camera")  # 4
self._json(res)                                                                       # 5
```

1. Read the raw JPEG body, at most 3 MB and only allowed content types.
2. The session id from the phone, cut to 64 characters.
3. Session key = phone IP + session id, so two phones never share tracking history.
4. Each spoken event is also written to the event log and the SQLite history.
5. Send the result as JSON.

## 9.4 One inference thread – `awareness.py`

```python
self._infer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="neurosonic-infer")   # 1

def detect(self, bgr):
    return self._infer.submit(self._detect_on_worker, bgr).result()                      # 2

def _detect_on_worker(self, bgr):
    with self._lock:                                                                     # 3
        m = self._load()                                                                 # 4
        dets = m.detect(bgr)                                                             # 5
```

1. One long-lived worker thread for all model work (fixed the ~2 MiB/s memory growth).
2. The request thread hands the image over and waits for the answer.
3. The lock makes sure only one inference runs at a time.
4. Load the detector on first use (`make_detector`: RF-DETR or SSDLite).
5. Run it; the result is a list of `{class_id, class_name, confidence, box_xyxy}`.

## 9.5 GPU detector with FP16 – `detectors.py`

```python
if device == "cuda" and not torch.cuda.is_available():
    raise DetectorUnavailable(...)                       # 1 no GPU -> caller falls back to SSDLite
os.environ.setdefault("HF_HUB_OFFLINE", "1")             # 2 never download anything
torch.set_num_threads(GPU_MODE_CPU_THREADS)              # 3 2 CPU threads are enough
self.model = RFDETRNano(device=device, pretrain_weights=str(weights))   # 4
try:
    self.model.inference(compile=False, dtype=torch.float16)            # 5
    self.precision = "fp16"
except Exception:
    pass                                                 # 6 keep FP32 if FP16 is unsupported
```

## 9.6 Automatic fallback during a session – `FallbackDetector.detect`

```python
try:
    return self.active.detect(bgr)                       # 1 normal case
except Exception as e:
    if isinstance(self.active, SSDLiteDetector):
        raise                                            # 2 SSDLite itself failed: report it
    self.fallback_reason = f"{self.active.name} failed during inference ..."
    torch.set_num_threads(self.active.prev_threads)      # 3 give SSDLite all CPU threads again
    self.active = self._fallback_factory()               # 4 switch permanently to SSDLite
    return self.active.detect(bgr)                       # 5 answer the SAME frame
```

## 9.7 Phone side – `app.js` `awarenessStep`

```javascript
const w = 320, h = Math.round((v.videoHeight / v.videoWidth) * 320);   // 1
aCanvas.getContext("2d").drawImage(v, 0, 0, w, h);
const blob = await new Promise((r) => aCanvas.toBlob(r, "image/jpeg", 0.7));   // 2
const kill = setTimeout(() => ctl.abort(), 5000);                      // 3
const res = await fetch(`/api/awareness/frame?session=${aSession}&mode=${settings.mode}...`,
  { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: blob, signal: ctl.signal });  // 4
for (const e of r.events) {
  if (e.kind === "path") voice.say(e.text, e.category, null, { key: "path" });               // 5
}
...
finally { scheduleFrame(Math.max(0, frameMs() - (Date.now() - t0))); }                     // 6
```

1. Scale the video frame to 320 px wide, keeping the aspect ratio (small upload, fast on Wi-Fi).
2. Compress to JPEG, quality 0.7 (small enough for Wi-Fi at 5 frames per second).
3. If the laptop does not answer within 5 s, cancel – a stuck request must not stop guidance.
4. Send the image to the laptop.
5. Speak each path message; `key: "path"` replaces any older path message still waiting.
6. Schedule the next frame so that frames are evenly spaced (200 ms minus the time already used).
