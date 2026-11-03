# 14. Automated testing methodology and actual results

## 14.1 Test levels

| Level | Tool | Location | What it proves |
|---|---|---|---|
| Unit and integration tests (Python) | standard-library `unittest` | `tests/test_*.py` | functions, engines and HTTP API behave as specified; uses real models and real demo data |
| Unit tests (browser logic) | Node.js built-in `node --test`, no packages | `tests/js/web_logic.test.mjs` (run from `tests/test_web_js.py`) | pure JavaScript logic: speech queue, interruption, navigation maths, route following, recorder, event simulation |
| Browser end-to-end (manual scripts) | headless Chrome over the DevTools protocol, Node's built-in WebSocket | `tests/js/ui_smoke_cdp.mjs`, `ui_voice_map_cdp.mjs`, `ui_final_cdp.mjs` | the real page in a real browser engine: clicks are real input events; Chrome's fake camera/microphone play recorded media; internet DNS is blocked; every request is logged |
| Offline guard | `tests/_offline.py::no_internet` | context manager patching `socket.connect`, `create_connection`, `getaddrinfo` | code under test makes **no** non-loopback network access (the guard itself is tested) |
| Equivalence | `tools/verify_equivalence.py` | runs the original `models/yolo.py` in a subprocess | the vendored WOAD model gives identical outputs (max diff 0.0) |
| Mutation checks (manual) | edit the pipeline, run the tests | — | tests fail when preprocessing or input order is broken; the TLS-stall test fails on the old server design |

**Run all automated tests:**

```bat
cd F:\Projects\WOAD-Research\implementation
..\.venv\Scripts\python -m unittest discover -s tests -t . -v
```

## 14.2 Actual result

After Sprint 1 (online scene description, 2026-11-02 evening): `Ran 204 tests … OK` (Node 32/32), with
`test_vision` (40 tests, mock provider and a fake Gemini client) and `tests/js/vision.test.mjs` (3) added;
`ui_vision_cdp.mjs`, `ui_vision_slow_cdp.mjs` (added with the deadline fix) and the four earlier browser tests PASS. The opt-in live test (`test_vision_live`, skipped by
default) made the single approved Gemini request: **timeout after 25.9 s** (see `18_ONLINE_VISION.md`).

After the product refinement (2026-11-02, about 14:30):

```
Ran 141 tests in 96.213s
OK
```

Node unit tests: `tests 29, pass 29, fail 0` (17 in `web_logic.test.mjs`, 12 in `refinement.test.mjs`).
New modules: `test_pathguide` (20), `test_refinement_ui_nav` (7); `test_voice_and_map` now counts 14 including the
A*/Dijkstra test. Browser E2E: `ui_smoke_cdp`, `ui_voice_map_cdp`, `ui_final_cdp` (updated for Walking Guidance)
and the new `ui_refine_cdp` (iPhone 17 Pro Max metrics) all PASS. Details: `17_PRODUCT_REFINEMENT.md` §17.6.

Earlier run (2026-11-02 13:20, before the refinement): `Ran 114 tests in 96.724s OK`, Node 17/17.

| Test module | Tests | Covers |
|---|---|---|
| `test_model.py` | 13 | checkpoint hash, architecture checks, rejection of the 5-class root `best.pt`, two-input forward shape (B, 25200, 8), single-input call rejected |
| `test_preprocess_pairing.py` | 10 | letterbox geometry, median blur on depth only, BGR→RGB, 16-bit / single-channel depth rejected, filename pairing |
| `test_detection.py` | 9 | golden detections, known objects, box mapping at 2× resolution, input-order and blank-modality ablations |
| `test_cli.py` | 6 | `woad_detect.py` outputs, never-overwrite run folders, pairing errors |
| `test_evaluate.py` | 6 | metric code equals the original `ap_per_class`; label rules; class mapping; end-to-end evaluation sanity |
| `test_demo_detec_test.py` | 2 | demo-set layout and known detections |
| `test_alerts.py` | 18 | alert engine (flicker suppression, wording, repetition, merging, availability, watchdog), quality checker, replay source, deterministic replay CLI |
| `test_app.py` | 8 | HTTP API: status, upload detection, bad input, places, client alerts, error codes, path traversal, replay stream |
| `test_mobile_access.py` | 12 | idle TLS connection does not block; certificates meet iOS rules and verify by IP/host name; renewal; MIME types of the whole module graph; LAN binding; setup page; exclusive port; firewall check (mocked); older-WebKit syntax |
| `test_voice_and_map.py` | 14 | Piper produces real audio (5.3 s, non-silent), cache, offline; map coverage, search, **A\* = Dijkstra**, island handling; TTS byte ranges; map/route endpoints |
| `test_final_integration.py` | 15 | intent parser; 8 spoken fixed commands (≥ 7 required, 8/8 measured); saved-place resolution; bad audio; Vosk offline; SSDLite detection with 2-frame confirmation, handheld wording, dark frames, urgency, bad input, offline; voice-command and awareness endpoints |
| `test_web_js.py` | 1 (runs 29 Node tests: 17 in `web_logic.test.mjs`, 12 in `refinement.test.mjs`) | speech queue and interruption, navigation maths, route following, recorder (16 kHz WAV, end-of-speech), frame differencing, motion alerter |
| **Total** | **114** | |

## 14.3 Browser end-to-end results (manual scripts, PASS on 2026-11-02)

| Script | Setup | Checked |
|---|---|---|
| `ui_smoke_cdp.mjs` | app on localhost + WOAD replay running | camera simulation produces events; tabs; no horizontal overflow at phone width; 0 JavaScript errors |
| `ui_voice_map_cdp.mjs` | Chrome **cannot resolve internet hosts** | real tap on Test Voice → neural audio played to `ended` (5.24 s) and reported to the server; map loads; search "CMC Hospital"; simulated walk Katpadi → CMC Hospital (264 steps) with spoken steps and arrival; **0 external requests** |
| `ui_final_cdp.mjs` | fake microphone (`tools/make_e2e_media.py`: Piper speech "navigate to Katpadi Junction") + fake camera (Y4M video of recorded frames with people) | Test Voice; **urgent warning interrupts navigation speech, which is then replayed**; voice command heard ("navigate took out body junction") → Katpadi Junction → route planned → waits for "start navigation"; camera awareness speaks "Person …"; 0 external requests; 0 JS errors |

```bat
:: start the app first (another terminal): ..\.venv\Scripts\python neurosonic_app.py
python tools\make_e2e_media.py --out e2e_media
node tests\js\ui_final_cdp.mjs http://127.0.0.1:8765 "C:/Program Files/Google/Chrome/Application/chrome.exe" e2e_media\fake_mic.wav e2e_media\fake_cam.y4m
```

## 14.4 Model evaluation results (WOAD)

These are documented fully in `docs/EVALUATION.md`.

| Measurement | Value |
|---|---|
| Re-implementation vs original code | max abs. difference **0.0** |
| Person AP@0.5, published dataset `VOCdevkit_nc_10` val (365 images, 129 people) | **0.218** (AP@0.5:0.95 0.073) |
| Person AP@0.5, train split (1,286 images, 458 people) | **0.173** (AP@0.5:0.95 0.050) |
| Authors' training-plot mAP@0.5 (exp72's own data) | 0.669; **not reproducible**, data unpublished |
| Brightness experiment | darkening keeps 27 % of detections; histogram matching recovers 87 % on synthetic darkening, but on the real dark recording gives 1 correct vs 56 false alarms |

## 14.5 Bugs found by testing (and fixed)

| Bug | Found by |
|---|---|
| iPhone "stays loading": TLS handshake blocking + iOS-rejected certificate + firewall | reproduction script; `test_mobile_access.py` |
| First Test Voice tap swallowed by a layout shift | browser E2E trace (`ui_voice_map_cdp.mjs`) |
| Map canvas blurry when created in a hidden tab | E2E screenshot |
| Simulated walk stuck on long route segments | E2E (`pointAtAlong` regression test added) |
| Stale server instance answering on a shared port (Windows) | end-to-end LAN check; `test_second_instance_cannot_share_the_port` |
| Vellore Fort route impossible (island in OSM data) | route tests; island snapping added |
| Voice destination "the new bus start" matched a wrong place | E2E voice test; matching heuristics revised and re-measured |

## 14.6 What the tests do **not** prove

* **On the real device:** audible speech on an iPhone; iPhone microphone and camera; real GPS movement.
* **On real users and places:** human voices and accents; street noise; real street video; a physically
  disconnected network.
* **Safety:** usability with visually impaired users. The fixed thresholds (alert confidence 0.40, 2-of-3
  confirmation, cooldowns, urgency at 25 % of the image area) are engineering defaults and have not been
  validated with users.
* **Biased evaluation:** synthetic-speech recognition results come from Piper's own voice, so they are biased.
  The destination heuristics were tuned on the same 24 samples.
