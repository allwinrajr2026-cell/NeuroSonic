## F1. File: tools/benchmark_detectors.py {: .file}

#### 1. Purpose
The **Phase 1 controlled benchmark** that chose the detector: SSDLite vs RF-DETR Nano vs YOLO26n/s, each on CPU and
GPU, with identical inputs. Not used by the running app. Output: `outputs/benchmarks/phase1/results.json`.

#### 2. How it works
- **Quality:** the published WOAD dataset `VOCdevkit_nc_10` validation split (365 near-IR images, 129 people); person
  AP@0.5 and AP@0.5:0.95 computed with the project's own metric code (`woad.metrics.ap_per_class`).
- **Speed:** the first frames of the recorded `detec_test` sequence (640×480); latency = preprocessing + inference +
  postprocessing on an in-memory frame; also CPU load and GPU memory.

#### 6. Faculty demonstration explanation
> "Before replacing the detector I measured all candidates on the same images. RF-DETR Nano was the most accurate and
> fast enough on the GPU, so it became the main detector, with SSDLite kept as the CPU fallback."

#### 7. Possible faculty questions
- **Are these phone images?** No – near-infrared images, the only labelled data available. The comparison between
  detectors is fair; absolute numbers for phone photos are unknown.

## F2. File: tools/benchmark_precision.py {: .file}

#### 1. Purpose
Measures RF-DETR Nano **FP32 vs FP16**: accuracy on the same 365 images, and latency at the phone frame size
(320×240), both back-to-back and **paced at 5 frames/s** (as in the app).

#### 2. Result (`outputs/benchmarks/precision/results.json`)

| | FP32 | FP16 |
|---|---|---|
| Person AP@0.5 | 0.6597 | 0.6600 |
| Recall at 0.40 | 0.7287 | 0.7287 |
| Latency back-to-back (median) | 17.3 ms | 16.9 ms |
| Latency paced at 5 frames/s (median / p90) | 66.5 / 78.6 ms | 53.2 / 60.8 ms |

#### 6. Faculty demonstration explanation
> "Pacing matters: at five frames per second the laptop GPU drops to a low-power state between frames (we logged P8 at
> about 200–400 MHz), so real latency is higher than a back-to-back benchmark. FP16 keeps the same accuracy and cuts
> the paced latency from 66.5 to 53.2 milliseconds."

## F3. File: tools/soak_test.py {: .file}

#### 1. Purpose
A long-duration stability test of the running server: streams the demo clip to `/api/awareness/frame` at 5 frames/s
(one request at a time, like the phone) and records every 10 s: frames/s, latency, server memory (RSS), GPU memory and
utilisation, events. Optional slow mock cloud requests run in parallel.

#### 2. Results (`outputs/benchmarks/soak/`)
- **Before the fix:** server memory grew about 2 MiB per second; request medians 62–104 ms.
- **After the fix (one inference thread):** 2,980 frames in 10 minutes, **0 errors**, 4.97 frames/s, medians
  70–78 ms, no upward memory trend, 7 of 7 slow (20 s) mock cloud requests answered.

#### 7. Possible faculty question
- **Does 10 minutes prove there is no leak?** No; it rules out the large leak we found. A run of an hour or more is
  still pending.

## F4. Files: tools/evaluate.py and tools/verify_equivalence.py {: .file}

#### 1. Purpose
- `evaluate.py` evaluates the WOAD checkpoint on a labelled IR + depth dataset, following the original validation
  pipeline (conf 0.001, IoU 0.6, max 300 boxes, IoU 0.50:0.05:0.95, original `ap_per_class`). A `--class-map` option
  maps dataset classes to model classes.
- `verify_equivalence.py` runs the original model code in a separate process and our copy on the same seeded random
  inputs and compares the outputs (exit code 0 = identical).

#### 2. Results
Maximum difference 0.0. Person AP@0.5 on the published dataset: **0.218** (val, 365 images) and 0.173 (train, 1,286
images). The authors' reported 0.669 mAP could not be verified, because their exact training data is not published.

#### 6. Faculty demonstration explanation
> "Reproducing a paper means proving the code is the same and measuring honestly. Our copy gives exactly the same
> output as the original. On the data that is actually published, the model finds people with AP 0.218 – much lower
> than the authors' plot, mostly because it misses people in new scenes."

## F5. Folder: tests/ (Python, Node.js and browser tests) {: .file}

#### 1. Purpose
Automated proof that each part works and keeps working after changes.

#### 2. What is in it

| Test file(s) | What they check |
|---|---|
| `test_model.py`, `test_detection.py`, `test_preprocess_pairing.py`, `test_cli.py`, `test_evaluate.py`, `test_demo_detec_test.py` | WOAD loading and hash, two-input forward pass, preprocessing, pairing, CLI outputs, golden detections, metric equivalence |
| `test_alerts.py` | alert engine: confirmation, repetition, merging, unavailable/resumed |
| `test_app.py`, `test_mobile_access.py` | real server on a test port: every API route, errors, path-traversal blocking, TLS certificate rules, the "one idle client froze the server" regression |
| `test_voice_and_map.py` | Piper, Vosk intents, place matching, A* routes vs an independent shortest-path check |
| `test_pathguide.py`, `test_refinement_ui_nav.py` | path states, thresholds, route steps, interface structure |
| `test_perception_pipeline.py` | detector fallback, tracking, camera-motion compensation, entering/crossing events (RF-DETR GPU tests are skipped in the CPU environment) |
| `test_vision.py`, `test_vision_live.py` | online description with mock and fake clients (timeouts, 503, breaker, filter); the live test runs only with `NEUROSONIC_LIVE_VISION=1` |
| `test_final_integration.py` | offline voice commands, live camera awareness, their APIs, and offline operation |
| `test_web_js.py` + `js/*.test.mjs` | runs the JavaScript unit tests in Node.js (speech queue, navigation maths, GPS states, event simulation) |
| `js/ui_*_cdp.mjs` (7 files) | browser tests: headless Chrome with a fake camera and microphone, at iPhone size, checking speech, guidance, events, vision consent, no external requests and no JavaScript errors |

`_offline.py` is a helper used in several tests to forbid any network access except to the laptop itself. Those
tests show that voice, map search and routing work without internet in-process; it does not replace a test with the
network physically disconnected (still pending).

**Final result (3 Nov 2026):** `Ran 204 tests … OK` in `.venv-gpu` (1 skipped: the opt-in live Gemini test) and in
`.venv` (3 skipped: GPU-only tests); browser tests **7 of 7 pass**.

Command: `..\.venv-gpu\Scripts\python -m unittest discover -s tests -t .`

#### 6. Faculty demonstration explanation
> "There are 204 automated tests. Some start a real server and call every endpoint, some run the JavaScript logic in
> Node, and seven drive a real Chrome browser with a fake camera. Several tests block all non-local network access, which
> shows the voice, map and routing work without internet. None of this is a substitute for the iPhone and street tests, which are still pending."
