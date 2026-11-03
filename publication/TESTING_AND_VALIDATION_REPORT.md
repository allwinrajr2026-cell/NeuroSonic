# NeuroSonic: testing and validation report

* **Date:** 2026-11-03.
* **Code state:** after the final changes (FP16, one inference thread, quiet handling of client disconnects, detector
  chip).
* **Rule used throughout:** every number below comes from a file or log produced on this date. Each is labelled with its
  evidence level:
  * **LAPTOP:** measured on the laptop;
  * **BROWSER:** headless Chrome with a fake camera and microphone, on loopback;
  * **IPHONE / FIELD:** not yet done.

## 1. Summary

| Level | Result | Evidence |
|---|---|---|
| Python unit, integration and API tests, `.venv-gpu` | **Ran 204, OK** (1 skipped: opt-in live cloud test) | `python -m unittest discover -s tests -t .` |
| Same, production `.venv` (CPU only) | **Ran 204, OK** (3 skipped: 2 GPU-only + live cloud) | same command, `..\.venv\Scripts\python` |
| Browser end-to-end (7 scripts) | **7 / 7 PASS** | `tests/js/ui_*_cdp.mjs`; logs below |
| 10-minute soak, final code | 2980 frames, **0 errors**, 4.97 fps, 7/7 cloud requests answered | `outputs/benchmarks/soak/soak_10min_after_fix.json` |
| Detector benchmark | RF-DETR Nano best AP and recall of 4 | `outputs/benchmarks/phase1/results.json` |
| FP32 vs FP16 | same quality; at 5 fps median 66.5 → 53.2 ms | `outputs/benchmarks/precision/results.json` |
| Quality gate (documented launch) | GPU and CPU launches both work end to end | section 6 |
| Production `.venv` unchanged | `pip freeze` identical to the backup | `backups/20261103-000843-env-before-gpu-phase1/venv_pip_freeze.txt` |
| **iPhone, Wi-Fi, streets, users** | **NOT DONE** | `docs/IPHONE_VALIDATION_PROTOCOL.md` |

## 2. Automated test suites (LAPTOP)

`tests/` holds 17 Python test files with 204 test cases. One of them, `test_web_js.py`, runs the 32 Node tests of the
browser logic.

| File | Tests | Covers |
|---|---|---|
| `test_vision.py` | 40 | online description: consent, rate limits, timeouts, retries, safety filter, endpoints (mock only) |
| `test_perception_pipeline.py` | 22 | detector fall-back, RF-DETR on GPU offline, camera motion, tracking, events, end-to-end API |
| `test_pathguide.py` | 20 | walking-path states and their confirmation |
| `test_alerts.py` | 18 | object-description wording, cooldowns |
| `test_final_integration.py` | 15 | whole-app integration, offline operation |
| `test_voice_and_map.py` | 14 | Vosk intents, place search, A* routing |
| `test_model.py` | 13 | WOAD model |
| `test_mobile_access.py` | 12 | HTTPS, local CA, TLS robustness |
| `test_preprocess_pairing.py` | 10 | WOAD data pairing |
| `test_detection.py` | 9 | WOAD detection service |
| `test_app.py` | 8 | API and history |
| `test_refinement_ui_nav.py` | 7 | interface structure, How it works |
| `test_cli.py`, `test_evaluate.py` | 6 + 6 | command-line tools, evaluation code |
| `test_demo_detec_test.py` | 2 | demo data |
| `test_web_js.py` | 1 (runs 32 Node tests) | browser logic: speech queue, navigation, vision client |
| `test_vision_live.py` | 1 (skipped) | live Gemini; runs only with explicit opt-in |

**Run on 2026-11-03 after the last code change:**

* `.venv-gpu`: `Ran 204 tests in 84.9s — OK (skipped=1)`.
* `.venv`: `Ran 204 tests — OK (skipped=3)`.

## 3. Browser end-to-end tests (BROWSER)

**Setup:**

* the server ran from `.venv-gpu` with `--vision-provider mock`;
* headless Chrome at iPhone size, with a fake camera and fake microphone;
* DNS was blocked, so no request left the laptop.

| Test | Result | Key observations |
|---|---|---|
| `ui_smoke_cdp.mjs` | PASS | all screens load, no JS errors |
| `ui_voice_map_cdp.mjs` | PASS | Test Voice played with the neural voice; 3 navigation instructions played |
| `ui_refine_cdp.mjs` | PASS | no horizontal overflow, touch targets, no external requests |
| `ui_final_cdp.mjs` | PASS | spoken destination recognised (Katpadi Junction); full workflow |
| `ui_vision_cdp.mjs` (mock script `ok,503,503`) | PASS | opt-in before upload; description; outage spoken clearly; guidance continues; consent withdrawal stops uploads; history text only |
| `ui_vision_slow_cdp.mjs` (mock `slow20`) | PASS | "Still waiting…" at 15.2 s, description at 20.1 s, 99 frames analysed during the wait |
| `ui_events_cdp.mjs` | PASS | RF-DETR FP16 on CUDA; 4.91 fps at the 200 ms interval; capture → answer **median 67 ms, p90 73, max 81** (44 frames); "Caution. A person is moving into your path from the left." → neural audio started after **257 ms** |

**Note:** the vision test needs its own server started with `NEUROSONIC_VISION_MOCK_SCRIPT=ok,503,503`. Against the
`slow20` server it fails on purpose, because no outage is simulated there. On the first run of this session it was
started against the wrong server; it passed when rerun against the correct one.

## 4. Performance measurements (LAPTOP)

### 4.1 Detector benchmark (Phase 1)

| Detector | GPU ms | CPU ms | Person AP@0.5 | AP@0.5:0.95 | Recall @0.40 |
|---|---|---|---|---|---|
| SSDLite320 | 42.3 | 43.7 | 0.542 | 0.208 | 0.574 |
| **RF-DETR Nano** | 21.3 | 121.9 | **0.660** | **0.304** | **0.729** |
| YOLO26n | 12.4 | 27.8 | 0.619 | 0.268 | 0.628 |
| YOLO26s | 11.8 | 57.5 | 0.628 | 0.292 | 0.651 |

**Setup:** mean latency over 640×480 recorded frames, FP32, back to back. Quality was measured on 365 near-infrared
images with 129 people. These are not phone images.

### 4.2 FP32 vs FP16 (`tools/benchmark_precision.py`)

| | AP@0.5 | AP@0.5:0.95 | Precision @0.40 | Recall @0.40 | Back to back, median / p90 | At 5 fps, median / p90 |
|---|---|---|---|---|---|---|
| FP32 | 0.660 | 0.304 | 0.588 | 0.729 | 17.3 / 21.7 ms | 66.5 / 78.6 ms |
| **FP16** | 0.660 | 0.305 | 0.595 | 0.729 | 16.9 / 20.4 ms | 53.2 / 60.8 ms |

At 5 fps, `nvidia-smi` showed the GPU at P8 (210–405 MHz) between frames. On the event clip, FP32 and FP16 gave the
same class counts.

### 4.3 CPU threads

With RF-DETR on the GPU at 5 fps, server CPU use depended on the PyTorch CPU thread count:

* 8 threads (default): 712 % of one core;
* 4 threads: 326 %;
* **2 threads (used): 121 %**.

### 4.4 Soak tests (`tools/soak_test.py`)

| | Before (FP32, request threads) | After (final code) |
|---|---|---|
| Frames / errors | 2980 / 0 | 2980 / 0 |
| fps | 4.97 | 4.97 |
| Request-latency window medians | 62–104 ms (median 92.7) | **70–78 ms (median 74.8)** |
| Worst window p90 | 111.3 ms | **92.4 ms** |
| Server RAM, min–max | 851–2426 MiB | 2255–2431 MiB |
| Server CPU, median | 142 % of one core | 130 % |
| GPU memory, all processes | 735 MiB, flat | 845 MiB, flat |
| Cloud requests (20 s each) | 7 / 7 OK | 7 / 7 OK |
| Events | 0 (clip played at half speed) | 148 (100 person, 48 bicycle) |

**Interpretation:**

* There is no upward memory trend in either run.
* Latency is steadier after the changes.
* The two runs differ in how the clip was sampled, so their event counts cannot be compared.
* Ten minutes on loopback does not exclude a slow leak over hours, or effects of Wi-Fi.

**Regenerate:**

```bat
..\.venv-gpu\Scripts\python tools\soak_test.py --base http://127.0.0.1:8799 --clip e2e_media\event_cam.y4m --minutes 10 --server-pid <pid> --cloud-every 60 --out outputs\benchmarks\soak\soak_10min_after_fix.json
```

## 5. Defects found and fixed in this phase

| Defect | How found | Fix | Verified by |
|---|---|---|---|
| Idle PyTorch CPU threads (712 % of one core) | CPU measurement while streaming | 2 CPU threads in GPU mode | in-process measurement; tests |
| GPU inference on a new HTTP thread for every request | soak test, thread experiment (+3 ms per call) | one long-lived inference thread | soak after the fix; 204 tests |
| Live latency several times the benchmark | timing inside the server | root cause: GPU P8 power state at 5 fps; FP16 lowers it by ~20 % | `benchmark_precision.py` |
| Status reported the SSDLite weights file while RF-DETR was active | quality gate | status names the active weights; `fallback_weights` added | `/api/awareness/status` |
| A client disconnect during a reply logged two tracebacks | server log review after the browser tests | client disconnects are closed quietly | disconnect test: no traceback, server keeps serving |
| Soak test played the clip at half speed (no events) | before-fix soak | frames sampled by elapsed time | after-fix soak: 148 events |

**Checked and not a defect:** in the soak, 48 events named a *bicycle*. Inspection of the clip showed that the
composited person is riding a bicycle, so the label is correct.

## 6. Quality gate: the documented launch (LAPTOP)

**GPU launch:**

* **Command:** `..\.venv-gpu\Scripts\python neurosonic_app.py --host 0.0.0.0 --https --port 8770 --vision-provider off`
  (port 8770 because the owner's own server was using 8765; separate test database).
* **Start-up:** printed `RF-DETR Nano … on the NVIDIA GPU ready (cuda; frame interval 200 ms …)`, the phone address
  `https://192.168.1.5:8770` and the setup page.
* **API walkthrough:** all of the following worked:
  * status: precision fp16;
  * 30 frames: entering, caution, stop and clear messages;
  * speech: WAV, 104 kB;
  * place search: "CMC Hospital";
  * route: 1330 m, 10 steps;
  * voice command: navigate intent;
  * history: text only.

**CPU launch:**

* **Command:** `..\.venv\Scripts\python neurosonic_app.py --port 8772 --detector auto`.
* **Start-up:** printed `RF-DETR unavailable: … CUDA not available …; using SSDLite on the CPU`, with a frame interval
  of 400 ms.
* **API walkthrough:** the same checks passed.

## 7. Not yet validated (needs the owner and the iPhone)

The procedure is in `docs/IPHONE_VALIDATION_PROTOCOL.md`: 23 scenarios × 5 trials. Results go in
`docs/validation_results_template.csv`.

1. **RF-DETR on real iPhone frames:** Home → Start for 1 minute, then check `GET /api/awareness/status → clients`.
2. **Wi-Fi capture → answer latency** on the iPhone: shown in the status line.
3. **iPhone audio:** Test Voice, neural voice and fall-back voice, microphone and voice commands in Safari.
4. **Real scenes:** walking-path states and entering/crossing events with a chest-mounted phone, a cane and a sighted
   companion; low light, blur, crowds.
5. **Real GPS navigation** on a short known route in Vellore.
6. **Physically disconnected internet** (router without WAN).
7. **A live Gemini description**, which needs the owner's approval for each request.
8. **Longer runs** (≥ 1 hour) over Wi-Fi, with the laptop on mains power.
