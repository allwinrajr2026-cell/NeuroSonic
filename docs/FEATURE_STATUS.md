# NeuroSonic — feature status and acceptance tests

Status date: **2026-11-02** (product-refinement update: walking guidance, GPS handling, iPhone interface;
details in `PROJECT_DOCUMENTATION/16_PRODUCT_REFINEMENT.md`, manual tests in `docs/MANUAL_TESTING.md`).

NeuroSonic is a **voice-first, offline-capable assistive navigation and environmental-awareness prototype**
built on the WOAD research implementation. This file is the single place that says what works, and how we
know. Categories:

| Code | Meaning |
|---|---|
| **T1** | Previously implemented and tested (before 2026-11-02 voice/map work) |
| **T2** | Newly implemented and tested (2026-11-02) |
| **T3** | Implemented and tested in the product-refinement stage (2026-11-02, later the same day) |
| **DEV** | Implemented but **not yet verified where it matters** (e.g. on the iPhone), or partially implemented |
| **PLAN** | Planned future work / research |
| **NO** | Not technically supported yet; must not be claimed |

"Tested" means an automated test or a recorded manual check named in the Evidence column. "Offline" means
tested with network access blocked, in-process (`tests/_offline.py`) or in Chrome (`--host-resolver-rules`).
**No test has yet been run with the laptop's network physically disconnected.**

## 1. Voice (highest priority)

| Feature | Status | Evidence / notes |
|---|---|---|
| Local neural TTS engine (Piper 1.8.0, Indian-English voice `en_IN-spicor`) | **T2** | `tests/test_voice_and_map.py::TestPiperVoice`: acceptance sentence → 5.3 s WAV, 22.05 kHz, non-silent; works with the network blocked. Windows speech recogniser transcribed it as the right sentence (models/tts/README.md) |
| `/api/tts` WAV delivery incl. HTTP Range (needed by iOS) | **T2** | `TestVoiceMapApi.test_tts_endpoint_and_ranges` (200, 206 `bytes=0-1`, open range, 416) |
| Browser plays the neural voice after a tap; Test Voice speaks the acceptance sentence | **T2 (laptop Chrome)** | `tests/js/ui_voice_map_cdp.mjs`: a real tap on Test Voice, then the audio element played 5.24 s to `ended`; server report "neural PLAYED" |
| **iPhone actually plays the neural voice** | **DEV, not verified** | Cannot be tested from the laptop. Acceptance test A1 below must be done by a person with the iPhone |
| Browser speech as fallback | **T1/T2** | Used automatically if neural fails or is unavailable (`speech.js`); fallback path not exercised on a phone |
| Speaking indicator, error status, voice badge reflecting real state | **T2** | Settings → "Speaking (neural voice): …", errors shown; badge "Neural voice / Tap to enable sound / Speaking… / Voice error" |
| Priority queue, no overlap, no stale/duplicate speech | **T1** (+T2 for neural) | `web_logic.test.mjs` speech-queue tests; the one `<audio>` element plays sequentially; per-clip timeouts so a stuck clip cannot block the queue |
| Audio caching | **T2** | server disk cache (`data/tts_cache`) + memory cache + client blob cache; `test_cache_and_limits` |
| Urgent warnings interrupt routine speech; interrupted step re-played once | **T2** | `web_logic.test.mjs` (interrupt rules, re-queue once, stale still dropped); browser E2E `ui_final_cdp.mjs`: "Caution. Car ahead." cut off a long navigation message, which was then re-played |
| Speech pacing: per-category cooldowns, latest-wins for path states, 250 ms gap, stale descriptions dropped, warning audio prefetched | **T3** | `tests/js/refinement.test.mjs` (latest wins, cooldowns, interruption incl. descriptions, stale drop) |
| Calmer Piper style (length 1.08, noise 0.6 / 0.7) | **T3 (subjective)** | style is part of the cache key; not rated by listeners |
| Recovery after interruptions | **DEV** | timeouts + fallback implemented; behaviour after phone calls/lock screen not tested |
| **Offline voice commands** (push-to-talk: navigate to / search for / start / stop navigation / repeat / start / stop awareness / status / help / test voice) | **T2 (laptop Chrome)** · **DEV (iPhone)** | Vosk Indian-English small model on the laptop (`models/asr/README.md`). Fixed commands 8/8 from synthetic speech; browser E2E through Chrome's fake microphone. Not tested with human voices or street noise |
| Spoken destination names | **T2, unreliable** | correct place first in 10/24 synthetic utterances (in the top 3 in 11/24); therefore only *proposed*: spoken back and guidance waits for "start navigation" |
| Spoken status report and "repeat instruction" | **T2** | voice commands `status`, `repeat`; `statusReport()` covers location, map coverage, route, camera, voice, internet |
| Playback reports visible on the laptop | **T2** | `/api/voice/report`, printed as `[voice] <ip> iPhone/Safari: neural voice PLAYED …` |
| Welcome message after audio is enabled | **T2** | spoken after the first tap (E2E trace) |
| Tamil voice | **NO** | not downloaded or tested |
| Other Indian-English voices / comparison | **PLAN** | |

## 2. Offline map and routing (Vellore)

| Feature | Status | Evidence / notes |
|---|---|---|
| Vellore OSM extract (12.86–13.00 °N, 79.07–79.21 °E) | **T2** | `maps/vellore/README.md`, `manifest.json` (SHA-256 of raw files) |
| Buildings layer | **NO** | Overpass HTTP 502 at download time; not included |
| Offline map display in the Navigate tab (canvas, pan/zoom, coverage box, attribution) | **T2 (laptop Chrome)** | E2E screenshot; map loads with internet blocked |
| Clear coverage boundary / outside-area message | **T2** | dashed box; spoken "outside the offline map area"; route API 400 outside |
| Offline place/street search (813 names) | **T2** | `TestOfflineMap.test_search`; E2E "CMC Hospital" |
| Offline walking route (A*) | **T2** | equals Dijkstra on random pairs (`test_route_is_shortest_path`); works with network blocked |
| Turn-by-turn spoken instructions, pre-announcements, arrival | **T2 (simulated walk)** | `web_logic.test.mjs` route-following tests; E2E: Katpadi → CMC Hospital, 5.3 km, 264 simulated 20 m steps, arrival announced |
| Off-route detection + recalculation | **T2 (logic)** / **DEV (real GPS)** | unit tests: two consecutive fixes, accuracy-aware; never tested with real walking |
| Real GPS walking test in Vellore | **DEV, not done** | acceptance test M3 |
| Major-road warning | **T2** | "This is a main road. Take care." from OSM `trunk/primary` tags only |
| Clearer turn instructions (20 m probe angle, ≥ 30° turns, named-street "Continue onto", micro-steps merged, short pre-announcements, no "unnamed road") | **T3** | `test_refinement_ui_nav.py::TestRouteSteps` on 3 real Vellore routes; e.g. Katpadi → CMC Hospital in 6 instructions. Not checked against the real streets (M3) |
| Re-routing rate limit (once per 15 s) | **T3 (logic)** | `refinement.test.mjs` |
| Map: centres on the first position, follows during guidance, start / destination markers, resize on rotation | **T3 (Chrome)** | `refinement.test.mjs` (stub canvas), `ui_refine_cdp.mjs` (1248 × 1080 → 2204 × 660 backing store) |
| Sidewalk/crossing/traffic awareness | **NO** | not in the data |
| Map outside Vellore / download manager for other regions | **PLAN** | `tools/build_offline_map.py` works for any downloaded box |
| Voice destination input (speech recognition) | **T2, limited** | see Voice section: offline, but local names often misheard |

## 3. GPS and journey workflow

| Feature | Status | Evidence / notes |
|---|---|---|
| Browser GPS (watchPosition), permission/no-signal/timeout messages, stale-fix pause | **T1** | `NEUROSONIC_APP.md`; not tested on the iPhone |
| GPS fix quality: good ≤ 50 m, weak 50–100 m, inaccurate > 100 m and stale > 15 s are not used for guidance; location panel with accuracy and fix age | **T3 (logic + Chrome GPS emulation)** · **DEV (iPhone)** | `refinement.test.mjs`; `ui_refine_cdp.mjs`: good fix, 300 m fix → "Guidance paused", permission denied spoken |
| GPS loss / recovery during guidance ("GPS signal lost. Guidance paused…", "…restored") | **T3 (logic)** | `refinement.test.mjs`; never tested outdoors |
| Saved places (SQLite), coordinates, straight-line fallback guidance | **T1** | `test_app.py`, `web_logic.test.mjs` |
| Simulated position for testing (purple, labelled) | **T2** | E2E |
| Start-up check of camera/microphone/GPS/voice availability | **DEV** (partial) | server prints voice, map, voice-command and camera-detector status at start; the page shows them in Settings; the phone's camera/mic/GPS permissions are requested only when used (browser rule), with spoken errors |
| Phone carrying modes (chest-mounted / handheld) | **T2 (wording)** | Settings → Carrying mode. Chest: "Person ahead"; handheld: "Person in camera view, left", never "ahead" (`test_handheld_wording_never_says_ahead`). Device-orientation sensors are not used yet |
| Device heading (compass) for relative directions | **PLAN** | guidance uses compass directions and route turns |

## 4. Camera and obstacle awareness

| Feature | Status | Evidence / notes |
|---|---|---|
| WOAD exp72 IR+depth detector (person, Ebike, Car), bit-exact with the original | **T1** | 38 original tests; `docs/EVALUATION.md` |
| Measured accuracy | **T1** | person AP@0.5 0.218 (val) / 0.173 (train) on the published dataset (cross-dataset); training-plot figures unverified |
| Replay of recorded IR+depth, quality gate, alert engine | **T1** | `test_alerts.py`, `test_app.py` |
| Live CS30 IR+depth sensor | **NO** | hardware not connected (roadmap Stage 3) |
| **Live phone-camera awareness (RGB)** | **T2 (recorded frames, laptop Chrome)** · **DEV (iPhone, real streets)** | general COCO detector SSDLite320-MobileNetV3 (mAP 21.3) on the laptop, ~45 ms/frame, ~2.5 frames/s from the phone; obstacle-relevant classes only; 2-of-3 confirmation; spoken alerts; dark-image check. **Not WOAD, not validated for assistive use, no distance** (`models/rgb/README.md`) |
| Broad obstacle classes (furniture, walls, poles, steps, kerbs, holes …) | **NO** / **PLAN** | not supported by any model in this project |
| **Walking Guidance** (default): path states CLEAR_VIEW / POSSIBLE_OBSTACLE / BLOCKED_VIEW / UNCERTAIN / CAMERA_UNAVAILABLE from the lower-central path region, box overlap, side vs centre, 2-of-3 / 3-of-3 temporal confirmation, image quality + sharpness | **T3 (recorded frames, synthetic boxes, Chrome fake camera)** · **DEV (iPhone, real streets)** | `neurosonic/pathguide.py`; `tests/test_pathguide.py` (20 tests); `ui_final_cdp.mjs` spoke "Caution. An object is detected in the walking path." with no object names. Thresholds are unvalidated engineering defaults |
| "The visible path appears clear. Continue carefully." | **T3, restricted meaning** | means only "no *recognised* object in the visible path region for 3 good frames"; never "safe"; never said for dark/blurred frames. Steps, kerbs, holes, poles and walls remain invisible to the detector |
| **Object Description** (optional): object names with left / centre / right | **T3** | switch on Home and in Settings (kept in sync, `ui_refine_cdp.mjs`); `describe=1` on the endpoint; never interrupts |
| Old urgency heuristic ("Caution. Person ahead.", object ≥ 25 % of the image) | **replaced** | urgency now comes from BLOCKED_VIEW ("Stop. The walking path may be blocked.") |
| Distance to obstacles | **NO** | only possible with raw depth (CS30) or a validated method; never from RGB |
| Event-camera simulation (webcam frame differencing) | **T1** (demo) | motion only; **not** obstacle detection, not a real event camera |

## 4a. GPU perception (2026-11-03)

| Feature | Status | Evidence / notes |
|---|---|---|
| RF-DETR Nano (Apache-2.0) as the primary detector on the NVIDIA GPU, from `.venv-gpu` | **T3 (laptop, fake camera)** · **DEV (iPhone, streets)** | `tests/test_perception_pipeline.py::TestRFDETROnGPU`; `ui_events_cdp.mjs` PASS; benchmark person AP@0.5 0.660 vs SSDLite 0.542 (near-IR set) |
| Automatic fallback to SSDLite (no CUDA / package / weights, failed warm-up, run-time failure) | **T3** | `TestDetectorFallback`; production `.venv` uses SSDLite automatically |
| Camera-motion estimation + ByteTrack-style tracking | **T3 (synthetic + recorded)** | `TestCameraMotion`, `TestTracking` |
| Events: entering the walking path, crossing in front (camera-compensated, conservative) | **T3 (synthetic, composited clip)** · **DEV (real streets)** | `TestEvents`, `TestEndToEnd`, `ui_events_cdp.mjs`; "approaching" deliberately not announced |
| 200 ms frame interval with the GPU detector (4.95 fps measured), capture → answer median 85 ms | **T3 (laptop loopback)** | `ui_events_cdp.mjs`; Wi-Fi / iPhone latency unmeasured |
| FP16 inference for RF-DETR (falls back to FP32 if unsupported); precision shown in `/api/awareness/status` | **T3 (laptop)** | `outputs/benchmarks/precision/results.json`: same person quality as FP32, lower latency at 5 fps |
| All detector work on one long-lived inference thread (was: a new HTTP thread per frame) | **T3 (laptop)** | 10-minute soak tests before / after: `outputs/benchmarks/soak/` |
| Detector chip on Home ("RF-DETR · GPU" / "SSDLite · CPU (fallback)") | **T3 (Chrome)** | `web/index.html` `#a-det`, `web/js/app.js` `renderDetector`; browser tests PASS |
| Long-run stability (10 min at 5 fps with slow cloud requests in parallel) | **T3 (laptop loopback)** | `tools/soak_test.py`; 0 errors; not yet run over Wi-Fi with the iPhone |
| Depth estimation, segmentation, potholes / kerbs | **NO (future work)** | see `docs/REAL_TIME_VISION_TECHNICAL_INVESTIGATION.md` |

## 4b. Online scene description (Sprint 1, cloud, opt-in)

| Feature | Status | Evidence / notes |
|---|---|---|
| Provider-independent cloud vision layer (`neurosonic/vision/`: interface, typed errors, JSON scene schema) | **T3** | `tests/test_vision.py` (40 tests, no network) |
| SceneAssistant: consent, rate limit (5 s / session, 60 / hour), 30 s per attempt / 45 s budget (configurable), deadline ≥ 10 s, no retry after a timeout, one full retry for a quick 503 / network error, circuit breaker, spoken fallbacks, "still waiting" after 15 s | **T3 (mock)** · **not yet checked live** | `test_vision.py`; `ui_vision_cdp.mjs` simulated outage |
| Safety filter (no distances, no "safe" / "clear" / "no obstacles"), "AI description:" prefix, ≤ 400 chars | **T3 (mock)** | `TestSafetyFilter` |
| Gemini provider (`gemini-3.8-flash`, SDK retries off, timeouts, error mapping, key scrubbing) | **T3 (fake client)** · **live: timed out** | the one approved live request (2026-11-02 22:07) got no reply within 25 s (ReadTimeout); **no successful real description yet** (`docs/ONLINE_VISION.md`) |
| Endpoints `/api/vision/status`, `/api/vision/describe` | **T3** | `TestVisionEndpoints` (consent, 400/415/503, fallback, text-only history) |
| Phone: opt-in on first use, Describe button, question box, Settings consent, status, "describe surroundings" / question voice commands | **T3 (Chrome iPhone emulation, mock)** · **DEV (iPhone)** | `ui_vision_cdp.mjs` PASS |
| No camera images stored (history / logs / database) | **T3** | endpoint and browser tests check history contents; images handled in memory only |
| Real-world quality and latency of cloud descriptions | **NOT MEASURED** | needs approved live requests and phone tests |

## 5. Platform, offline-first, safety

| Feature | Status | Evidence / notes |
|---|---|---|
| Mobile-first accessible UI, large controls, `aria-live`, no layout shift while tapping | **T1/T2** | Layout-shift bug that swallowed the first Test Voice tap was found and fixed on 2026-11-02 |
| **Compact iPhone interface** (Home / Navigate / Speak / History / Settings / How it works; safe areas; research tools moved to a sub-screen) | **T3 (Chrome emulating iPhone 17 Pro Max 440 × 956 @3x)** · **DEV (Safari on a real iPhone)** | `tests/js/ui_refine_cdp.mjs` PASS: no horizontal overflow on 6 screens, touch targets ≥ 40 px, nothing under the fixed bars, rotation; `test_refinement_ui_nav.py` |
| **How It Works** tab (10 topics + architecture diagram, states laptop dependence) | **T3** | `test_refinement_ui_nav.py::test_how_it_works_content`; browser E2E |
| Permissions panel and offline-status list in Settings | **T3** | browser E2E (no JS errors); iPhone permission flow PENDING |
| HTTPS for phones with a local CA, firewall check | **T1** (laptop), **DEV** (iPhone) | `test_mobile_access.py`; iPhone access not yet confirmed by the user |
| SQLite history/statistics | **T1** | `test_app.py` |
| Offline operation of the local layer (walking guidance, voice, map, routing, history); online scene description needs internet | **T2 (simulated offline)** | in-process network block + Chrome with no DNS: 0 external requests. **Physical disconnect test pending (O1)** |
| Installable PWA / native Android | **PLAN** | |
| Safety statements (not a replacement for cane/guide dog/human help) | **T1** | Settings → About; docs |

## Acceptance tests

| ID | Test | How | Pass criterion | Status |
|---|---|---|---|---|
| **A1** | **iPhone Test Voice** | Start the app with `--https`; on the iPhone open the app, tap the screen once, Settings → **Test Voice** | You hear "Hello. This is NeuroSonic. Your voice assistant is working correctly." in the Indian-English neural voice **and** the laptop console prints `[voice] … iPhone/…: neural voice PLAYED: "Hello. This is NeuroSonic…"` | **PENDING** (needs the iPhone) |
| A2 | Laptop Test Voice | same on the laptop browser | sentence heard; console `PLAYED` | automated equivalent passes (`ui_voice_map_cdp.mjs`); listening by a person pending |
| A3 | Fallback | Settings → Voice engine → "This device's built-in voice" → Test Voice | sentence heard in the phone's own voice | PENDING |
| M1 | Offline map display | Navigate tab | map of Vellore with dashed coverage box | passes in Chrome (laptop); iPhone PENDING |
| M2 | Offline route | search "CMC Hospital" → choose → simulated position at map centre → Start guidance → "Move 20 m" repeatedly | route drawn, instructions spoken, arrival announced | passes (automated E2E, laptop) |
| M3 | Real walk in Vellore | real GPS, short known route | instructions match the streets; off-route recalculates | PENDING (field test, with a sighted companion) |
| O1 | Physical offline | disconnect the laptop from the internet, keeping phone and laptop on the same local Wi-Fi (e.g. router without WAN) | Test Voice, map, search, route and replay detection all work | PENDING |
| W1 | WOAD still works | `python -m unittest discover -s tests -t .` and Settings → Research tools → WOAD replay | all tests pass; replay alerts | passes (141 tests incl. 29 Node tests + 4 browser E2E tests, 2026-11-02) |
| **V1** | iPhone voice command | iPhone: tap **🎤 Speak**, allow the microphone, say "start awareness", then "status" | camera awareness starts; status is spoken; laptop console prints `[voicecmd] … heard "…" -> …` | **PENDING** |
| **C1** | iPhone walking guidance | chest-mounted iPhone, the scenes C1.1–C1.9 in `docs/MANUAL_TESTING.md` (with a sighted companion) | correct path state within ~1–2 s; no false "clear" for a recognised object in the path; no repeated messages | **PENDING** (field test) |
| G1 | GPS states on the iPhone | `docs/MANUAL_TESTING.md` G1.1–G1.3 | good / weak / inaccurate / denied shown and spoken correctly | PENDING (automated equivalent with Chrome GPS emulation passes) |
| U1 | iPhone Safari layout | `docs/MANUAL_TESTING.md` U1.1–U1.5 | no sideways scroll, nothing hidden, VoiceOver names | PENDING (Chrome emulation passes) |
| V2 | Interruption | while a route instruction is being spoken, an obstacle appears | the instruction stops, the warning is spoken, the instruction is repeated | passes in laptop Chrome (E2E); iPhone PENDING |
