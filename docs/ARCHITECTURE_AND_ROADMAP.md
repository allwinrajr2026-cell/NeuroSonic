# NeuroSonic (WOAD) — Product architecture and roadmap

Status date: 2026-11-02 (direction update). This document defines the **final product** and how to get there.
The current, test-backed status of every feature is in [`FEATURE_STATUS.md`](FEATURE_STATUS.md). The original
research repository, the exp72 checkpoint and the datasets are read-only inputs to all stages.

## 00. Direction change: online-first AI environmental intelligence (Sprint 1, 2026-11-02 evening)

The project owner set the product direction to **online-first AI environmental intelligence**: rich scene
understanding comes from cloud vision models, starting with Google Gemini behind a provider-independent interface
(`neurosonic/vision/`, see [`ONLINE_VISION.md`](ONLINE_VISION.md)). This change does **not** remove the local layer:

| Layer | Needs internet | Role |
|---|---|---|
| Walking guidance (SSDLite + `pathguide.py`), voice commands (Vosk), Piper voice, offline map, routing, GPS, history | no (needs the laptop) | always on, safety-relevant warnings; must never depend on the cloud |
| Online scene description (`/api/vision/*`) | yes (on the laptop) | on demand, opt-in, AI descriptions and answers to questions; never safety statements |

The rule from section F, "detection never depends on cloud APIs", is kept for walking guidance; it is enforced by
`tests/test_vision.py::TestLocalGuidanceIndependence` (no imports of the cloud package from local modules) and the
browser test `ui_vision_cdp.mjs` (guidance keeps running during a simulated cloud outage). Statements in this
document that the whole product is offline-first describe the local layer only.

## 0. Product direction: voice-first assistive navigation (2026-11-02)

NeuroSonic should help a visually impaired person understand their surroundings, reach a destination and
learn about potential obstacles **without looking at the phone**. Speech and audio are the primary interface.
The phone is the primary device. Processing stays local wherever practical. The first deployment and test area
is **Vellore, Tamil Nadu**.

### 0.1 Camera and sensor input paths, kept strictly separate

| Path | Input | Model | Status | May be presented as |
|---|---|---|---|---|
| A. WOAD | Synexens CS30 near-IR + SDK colour-mapped depth | exp72 (person, Ebike, Car) | recorded data only; live sensor not connected | obstacle detection **for those 3 classes**, with measured limits (EVALUATION.md) |
| B. RGB camera (phone / webcam) | ordinary colour video | SSDLite320-MobileNetV3, COCO (general, mAP 21.3) | implemented (laptop inference, phone frames) | "objects recognised in the camera view" for the listed COCO classes, no distance, not validated |
| C. Event-camera simulation | webcam frame differencing | no learned model | demo | "motion here" demonstration only; **not** obstacle detection, not a real event camera |
| D. Future sensors | phone LiDAR/ToF, stereo, real event camera, CS30 live | — | research | only after integration and validation |

Distances are reported only from a depth sensor (path A with raw depth, or D), never estimated from RGB.

### 0.2 Phone carrying modes (planned)

* **Mode A, chest-mounted:** the camera roughly faces the walking direction. Forward-path monitoring is
  possible, with announcements through headphones.
* **Mode B, handheld:** camera direction changes constantly. Directions must be stated relative to the camera
  ("in the camera view, left"), or use the device's orientation sensors. The camera direction must never be
  assumed to be the walking direction.

The user selects the mode. Not implemented yet.

### 0.3 Priorities, dependencies and status

| Priority | Work | Depends on | Status (2026-11-02) |
|---|---|---|---|
| **1** | Neural voice engine + **verified iPhone playback** | phone reaches laptop over HTTPS (local CA + firewall rule) | engine, API, UI, fallback, tests **done**; **iPhone acceptance test A1 pending** |
| **2** | Vellore offline map, display, walking routes | OSM extract; routing engine | **done** for the 15 × 15 km box (own A* router, no external engine); buildings missing; real-walk test pending |
| **3** | GPS destination + navigation workflow | 1, 2 | search → route → turn-by-turn → off-route recalculation → arrival **done (simulated walk)**; real GPS walk pending; voice destination input not started |
| **4** | Live camera-based environmental awareness | sensor/model decision (0.1 path B or D); mounting modes | **first version done (path B)**: general COCO detector SSDLite320 on the laptop, phone frames, chest/handheld wording, urgency heuristic; tested on recorded frames + browser E2E. Open: real-street validation, a stronger or assistive-specific model, ground hazards (steps/kerbs/holes), on-phone inference |
| **5** | One coherent spoken experience (navigation + warnings) | 1–4 | **done in software**: one queue, urgent/obstacle warnings interrupt navigation speech and the step is re-played; offline voice commands (Vosk) control navigation, awareness and status. Open: field test with users |

### 0.4 Conflicts between the new direction and the current implementation

1. **The voice is generated on the laptop**, not on the phone. "Local" here means "local network, no internet".
   A phone-only voice would need Piper on Android/iOS (WebAssembly or native). Not done.
2. **No obstacle detection runs on the phone camera.** WOAD needs CS30 IR + depth. The vision's "camera
   continuously inspects surroundings" requires path B or D (priority 4).
3. **The map is a 15 × 15 km box**, not a municipal boundary, and has no buildings or pavement data.
4. **Routing is a custom A* on OSM data**, not GraphHopper/Valhalla. It's simpler with no extra
   dependencies, but has no pedestrian-specific costs (crossings, surfaces).
5. **Licences:** Piper is GPL-3.0+ and the en-IN voice is AGPL-3.0. Fine for research; review before any
   distribution or hosted service.
6. **The web app needs the laptop.** A standalone phone app (PWA/native) is still in the plan (Stage 7).

Legend used in the requirement tables:

| Tag | Meaning |
|---|---|
| **DONE** | implemented and tested in `implementation/` |
| **MODEL-OK** | achievable with the existing exp72 model; software engineering only |
| **ENG** | needs new engineering/components, but no new hardware or retraining |
| **HW** | needs specific hardware (sensor, GPS, phone) that we must obtain/validate |
| **DATA/TRAIN** | cannot be met by the existing model; needs new data and/or retraining |
| **UNVERIFIED** | depends on a fact we have not confirmed yet |

---

## 1. The hard constraint that shapes everything: the model's inputs

The exp72 model takes **two** images and nothing else works as a substitute:

1. **Near-infrared (IR) frame** from the Synexens **CS30** RGB-ToF sensor, 640×480.
2. **Colour-mapped depth** produced by the **Synexens SDK's own colormap**
   (`frame->apply_colormap()` / `sy3_get_colormap_table` in `libsynexens3`, used by
   `save_depth_ir_rgb.exe` in `original/Data collection and pre-processing/`). It is a vendor
   lookup table, **not** OpenCV's `COLORMAP_JET`, and its depth range/clipping settings are not
   documented in the repository.

Consequences (these apply to every requirement below):

* An ordinary webcam or phone **RGB camera cannot drive this model.** Feeding RGB as "IR" plus a
  fake depth image is out of distribution, and its results would be meaningless. Our ablation
  shows IR carries most of the signal (blank IR → 0 % of the detection confidence remains), and
  depth carries about a third (blank depth → 65 % remains).
* Live detection therefore requires a **CS30, or a sensor proven equivalent** (same NIR band and
  the same depth colourisation reproduced exactly), plus the vendor SDK on the host platform.
* Supporting RGB cameras or phone ToF sensors is a **DATA/TRAIN** item: it needs a new dataset
  and a new model, validated separately. It is not a port.
* The model outputs class + box + confidence only. **Distance is not an output.** A distance
  could be read from the *raw* 16-bit depth at the box location (the CS30 provides it), but never
  from the colourised image without the exact colormap and range. Until that is implemented and
  validated, the product must not state distances.

---

## 2. Requirements → feasibility

### A. Core AI obstacle detection

| Requirement | Status | Notes |
|---|---|---|
| Original trained WOAD model | **DONE** | exp72, SHA-256 verified at every load; output identical to the original code (max diff 0.0) |
| NIR + colour-mapped depth inputs | **DONE** (files) | training-faithful preprocessing; 16-bit or single-channel depth is rejected |
| Person, Ebike, Car | **DONE** (outputs) / **accuracy partly unverified** | training plots: person 0.771, Ebike 0.839, Car 0.395 (exp72 data unpublished, not reproducible). Measured on the published dataset: person AP@0.5 0.17–0.22 (cross-dataset, low recall); Ebike/Car cannot be measured. See docs/EVALUATION.md |
| Boxes + confidence | **DONE** | JSON + annotated images, boxes in original IR coordinates |
| Image input | **DONE** | single pair, folder pair, `ir/`+`depth/` source |
| Live camera/sensor input | **HW + ENG** | CS30 + SDK capture bridge reproducing the SDK colourisation, validated against stored dataset frames. Webcam/phone RGB: **DATA/TRAIN** |
| Local inference, no internet | **DONE** (laptop CPU, ~100 ms per frame) | GPU untested (torch is a CPU build) |

### B. Voice assistance

| Requirement | Status | Notes |
|---|---|---|
| Announce detections aloud | **MODEL-OK + ENG** | template phrases from class names only; no invented content |
| "Person/Car/E-bike detected ahead" | **MODEL-OK** | "ahead/left/right" can come from the box's horizontal position (fixed thirds of the frame). "Ahead" must mean *in the camera's view*, not a distance claim |
| Offline TTS | **DONE (laptop)** / iPhone pending | Piper 1.8.0 + Indian-English voice `en_IN-spicor` on the laptop, streamed to the phone as WAV; browser `speechSynthesis` as fallback. iPhone playback acceptance test A1 pending (FEATURE_STATUS.md). Tamil: not available |
| Avoid repetition | **ENG** | per-class cooldown, simple track persistence (announce on entry and re-announce after N s), N-of-M frame confirmation to suppress single-frame flicker |
| Voice, volume, rate settings | **ENG** | stored in SQLite settings |
| Coordinate with navigation | **ENG** | one speech queue with priorities: hazard alerts > turn instructions > info; turn prompts are not dropped, only deferred |

### C. Location and GPS navigation

| Requirement | Status | Notes |
|---|---|---|
| Current location | **HW** | phone: GNSS via Android Location APIs. Laptops usually have **no GNSS**; Windows location uses Wi-Fi positioning, which needs internet. Offline laptop location needs a USB/Bluetooth GNSS receiver |
| Destination search, text | **ENG** | offline: a geocoding index built from an OpenStreetMap extract (e.g. Photon, or a reduced address/POI SQLite index). Online: optional Nominatim or another provider |
| Destination search, voice | **ENG** | offline speech recognition (e.g. Vosk or whisper.cpp). Model size and accuracy for the user's language are **UNVERIFIED** |
| Interactive map | **ENG** | MapLibre with offline vector tiles (PMTiles/MBTiles from OSM). For blind users, map *display* is secondary; spoken output is primary |
| Walking directions + turn-by-turn voice | **ENG** | offline pedestrian routing: GraphHopper (Java, runs on Android) or Valhalla (C++, has mobile builds). Turn instructions go through the shared speech queue |
| Downloadable offline maps/routing | **ENG** | region packs = tiles + routing graph + geocoding index, versioned and with checksums. OSM data is ODbL, so attribution is required |
| Optional online maps/routing | **ENG** | pluggable provider, used only when online and enabled |
| Permissions / no-GPS handling | **ENG** | explicit states (denied, no fix, low accuracy, stale fix) are spoken and shown. No navigation guidance is given without a valid fix |

### D. Laptop application

| Requirement | Status | Notes |
|---|---|---|
| Responsive web dashboard | **ENG** | local server on 127.0.0.1 (e.g. FastAPI) plus a static front end; no external CDN, assets bundled |
| Inference + visualisations | **MODEL-OK** | wraps `WOADDetector`; uploads of image pairs, replay of dataset sequences, live CS30 stream (Stage 3) |
| Detection history + statistics | **ENG** | SQLite |
| Research demonstration / experiment results | **MODEL-OK** | genuine evaluation metrics (Stage 1) shown **separately** from training-plot figures and reconstructed-demo results |
| Local operation without internet | **ENG** | no runtime network calls; verified by a firewall-off test |

### E. Android smartphone application

| Requirement | Status | Notes |
|---|---|---|
| Mobile UI / installable PWA | **ENG** | a PWA is enough for UI, maps and history. It is **not enough** for USB sensors, reliable offline TTS or background GPS, so a native app (Kotlin) or hybrid wrapper is likely required. Decision at the start of Stage 6 |
| Native Android if required | **ENG** | see above |
| Smartphone GPS | **HW** (phone) + **ENG** | fused location provider, foreground service for navigation |
| Camera + compatible IR/depth sensor | **HW + UNVERIFIED** | the phone's own cameras are **not compatible** with the model (section 1). The CS30 would have to connect over USB-C (OTG/UVC) with a working **Android build of libsynexens3**, and it is unconfirmed that one exists. Fallbacks: (a) the laptop or a small board runs sensor + model and the phone is the UI/GPS/voice client over local Wi-Fi/Bluetooth; (b) **DATA/TRAIN** a phone-camera model |
| Local AI inference on the phone | **ENG + validation** | export the two-input model to ONNX → ONNX Runtime Mobile, or TFLite / ExecuTorch. It must match PyTorch on the dataset (box IoU and score tolerance, and the same mAP within a stated margin) before it's used. The repo's existing `best-fp16.tflite` is a **stock 80-class COCO model**, not WOAD, and must not be used |
| Voice + navigation on phone | **ENG** | Android `TextToSpeech`; the routing engine from C |

### F. Offline-first architecture

| Requirement | Status | Notes |
|---|---|---|
| Detection never depends on cloud APIs | **DONE** for the engine | must stay so; enforced by a test that runs with networking disabled |
| SQLite local database | **ENG** | schema in section 3 |
| Local voice | **ENG** | see B |
| Offline maps and routing | **ENG** | see C; storage cost depends on region size (a city is typically tens to hundreds of MB, **UNVERIFIED** per region) |
| Internet optional | **ENG** / **DONE for scene description** | each online feature has an offline path or degrades to "unavailable"; online scene description degrades to a spoken "unavailable … Local walking guidance continues" (Sprint 1) |
| Online/offline indicator | **ENG** | visible badge plus spoken on change; reflects reachability *and* which offline packs are installed |

### G. Safety and reliability

| Requirement | Status | Notes |
|---|---|---|
| Never invent detections, locations, directions | **ENG** (policy + tests) | speech only from model output above threshold or from a routing result; no LLM-generated content in the alert path; no last-known position presented as current |
| No guaranteed avoidance/safety claims | **policy** | wording reviewed; first-run disclaimer; documentation |
| Report unavailable sensors / failed permissions | **ENG** | a heartbeat watchdog on the sensor stream: "Obstacle detection unavailable" is spoken if frames stop, are stale, or inference fails |
| Assistive prototype, not a cane/guide-dog replacement | **policy** | stated in the UI, README and any demo |
| Known model limits disclosed | **policy** | 3 classes only (no poles, steps, holes, kerbs); Car recall is low; trained on a limited dataset; performance under sunlight or rain is untested |

### Summary: what the existing model can and cannot deliver

* **Achievable with the existing model and software engineering only:** all of A for stored
  images, B (announcements with left/centre/right), D, F, the safety policies in G, and on-device
  inference *if* export validation passes.
* **Needs hardware:** live detection (a CS30 and its Windows SDK on the laptop), GNSS on the
  laptop (an external receiver), a test Android phone, and the phone-side sensor connection
  (an Android SDK for CS30 is **unverified**).
* **Needs new data/retraining:** any detection from ordinary RGB phone or webcam cameras, extra
  obstacle classes (stairs, poles, kerbs), and better Car recall.
* **Needs separate validation before trust:** the depth colourisation in live capture, the
  mobile-exported model, and distance estimates.

---

## 3. Target architecture

```
                         ┌──────────────── Device (laptop or phone) ────────────────┐
 CS30 sensor ──SDK──► Sensor bridge ──► Frame validator ──► Detection engine (WOAD) ─┐
 (IR + raw depth)      (colourise as    (resolution, staleness,  exp72, local only    │
                        SDK does; keep   colormap checks)                             │
                        raw depth)                                                    ▼
 GNSS ─────────────► Location service ──► Navigation engine ─────────────► Alert/Speech manager ──► offline TTS
 (perm. states)       (fix quality)       (offline routing, geocoding,      (priority queue,
                                           region packs)                     cooldowns, wording policy)
                                                    │                                 │
                                                    ▼                                 ▼
                                        SQLite: settings, detection history, trips, region-pack registry
                                                    │
                                        Local API (127.0.0.1) ──► Web dashboard / mobile UI
                                                                    (map, live view, history, stats,
                                                                     research results, online/offline badge)
```

Design rules:

* The **detection engine is the existing `woad` package**, unchanged. On the phone, an exported
  model sits behind the same interface and must pass the equivalence suite.
* All components talk through one in-process event bus or local API. Nothing in the
  detection → speech path makes a network call.
* SQLite tables (initial):
  * `settings`
  * `detections` (time, frame ID, class, confidence, box, position bucket, announced flag)
  * `sessions`
  * `trips` (start, destination, route summary)
  * `region_packs` (name, version, checksum, size)
  * `events` (sensor loss, permission changes, online/offline)
  * Location history is **opt-in** with a retention limit.

---

## 4. Dependencies (planned, not installed)

| Area | Laptop | Android |
|---|---|---|
| Inference | torch 2.15 CPU (installed); optional CUDA build | ONNX Runtime Mobile *or* TFLite/ExecuTorch (choose after export tests) |
| Sensor | Synexens `libsynexens3` + cs30-driver v.11 (Windows DLLs in the original repo) + a Python binding (ctypes/C++ shim) | Android build of the SDK — **UNVERIFIED** |
| Backend / UI | FastAPI + uvicorn, a static front end, MapLibre GL JS | Kotlin app (or a PWA in a wrapper), MapLibre Native |
| Database | sqlite3 (stdlib) | Room / SQLite |
| TTS | SAPI5 via `pyttsx3` or OS voices | Android `TextToSpeech` |
| Speech recognition | Vosk or whisper.cpp | Vosk Android |
| Maps / routing / geocoding | PMTiles/MBTiles; GraphHopper or Valhalla; Photon or a custom SQLite index | same engines' mobile builds |
| Data | OpenStreetMap regional extracts (ODbL attribution) | same, as downloadable packs |

## 5. Hardware requirements

* **Required for live detection:** a Synexens CS30 with the cs30-driver, USB connection,
  Windows 11 host (the SDK provided in the repository is Windows x64).
* **Laptop:** the current machine (CPU about 100 ms per frame, so roughly 8–10 FPS at best end to
  end). The RTX 4050 needs a CUDA torch build, not yet tested.
* **Laptop GNSS (offline navigation on the laptop):** a USB or Bluetooth GNSS receiver (NMEA).
* **Android test phone:** Android 10 or later, USB-C OTG (for the sensor path), and enough
  storage for region packs.
* **Wearable mounting and power:** a battery pack for sensor + phone/laptop; the mounting must
  match the training viewpoint (chest/head height). A viewpoint change is a model risk.

## 6. Technical risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Live input differs from the training data: depth colormap (vendor table, close to but not equal to JET) **and IR brightness. The published raw CS30 recording (test1730450780) has IR mean 59 vs about 140 in all training-type data, and the model detects nothing useful on it. Experiment (EVALUATION.md section 8): darkening removes about 73 % of detections on training-like frames, but histogram correction of the real recording finds the one person in 1 of about 13 frames and adds 56 false alarms on doors, so brightness is necessary, not sufficient** | silent accuracy loss or blindness | Find the capture settings or post-processing behind the training IR; capture with `save_depth_ir_rgb` settings; compare live histograms with dataset frames; regression set from recorded live frames; never run live without this check |
| R2 | No Android SDK for CS30 | no on-phone live detection | Hub architecture (laptop or board does detection, phone is the client) or retrain for phone sensors |
| R3 | Exported model (ONNX/TFLite) diverges from PyTorch: the custom transformer fusion, avg-pool, interpolation | wrong detections on the phone | Golden equivalence + dataset mAP gate; fp32 first, quantise later only with a re-measured mAP |
| R4 | Low recall: Car (training-time AP 0.395, 45 % missed) and **person on unfamiliar scenes (measured AP@0.5 0.17–0.22, recall about 0.2–0.3; cyclists and distant people missed)** | missed hazards | Report honestly; never imply complete coverage; retraining on more diverse data (DATA/TRAIN) |
| R5 | Only 3 classes; no stairs, poles, kerbs or holes | the user may over-trust the device | Safety messaging; roadmap item for new classes (DATA/TRAIN) |
| R6 | Laptop has no GNSS; Wi-Fi location needs internet | no offline navigation on the laptop | External GNSS receiver, or phone-only navigation |
| R7 | Offline TTS/ASR voices not installed or poor quality | silent or misheard device | Mitigated for TTS: local Piper voice + Test Voice + playback reports to the laptop + browser fallback. ASR (voice input) not started. Voice quality not yet rated by users |
| R8 | GPS accuracy in cities (5–20 m) is too coarse for pedestrian turns | wrong-turn guidance | Report accuracy; delay instructions when accuracy is poor; never present a route as safe |
| R9 | Latency: CPU ~100 ms plus capture and TTS | late alerts | Measure end-to-end; GPU/ONNX acceleration; drop stale frames rather than queue them |
| R10 | **Confirmed:** the published dataset is not exp72's data (no Ebike/Car labels) | training-time mAP cannot be verified | Check the other Drive links or contact the authors; until then report the training figures as unverified |
| R11 | Privacy of location/detection history | data exposure | Local only, opt-in, retention limit, no telemetry |

## 7. Implementation stages

| Stage | Content | Exit criteria | Blocked by |
|---|---|---|---|
| 0 ✅ | Inference engine, CLI, 38 regression tests | done | — |
| 1 ✅ | **Dataset evaluation:** archive downloaded and verified, structure and labels inspected, `tools/evaluate.py` (original metrics, verified equal) | done: person AP@0.5 0.218 val / 0.173 train (cross-dataset). exp72's own data is unavailable, so Ebike/Car are unmeasured | — |
| 2 ✅ | Replay source, input-quality check (IR brightness/contrast, depth validity) and alert logic (position thirds, 2-of-3 confirmation, cooldown/repeat, merging, priorities, unavailable/resumed, stall watchdog); `woad_replay.py` | done: byte-identical transcripts (live model vs cached detections); 18 tests; see docs/STAGE2_ALERTS.md. Open: defaults not user-validated; detec_test is not a continuous stream; unavailable/resumed flapping | — |
| 3 | CS30 live capture bridge on the laptop (SDK colourisation, raw depth kept), stream validator, watchdog | live frames statistically match dataset frames; watchdog speaks on sensor loss | **CS30 hardware** |
| 4 ◐ | **NeuroSonic app (sprint 2026-11-02):** mobile-first web UI + stdlib server, live replay detection, upload detection, browser voice + panned tones, SQLite history/stats, online/offline + detection badges, browser GPS straight-line guidance, webcam event-camera simulation (demo) | done: 73 tests + headless-Chrome smoke test (docs/NEUROSONIC_APP.md). Open: research-results page, speech tests on real devices, PWA/offline caching | Stage 3 for live sensor view |
| 5 | Model export (ONNX → mobile runtime) + equivalence and mAP gate | exported mAP within an agreed margin of PyTorch on the dataset | Stage 1 |
| 6 ◐ | Navigation: Vellore OSM package, offline search, A* walking routes, turn-by-turn speech, off-route recalculation, GPS states | done (simulated walk, network blocked): docs/FEATURE_STATUS.md. Open: real walk in Vellore, buildings layer, voice destination input, other regions | phone for field tests |
| 7 | Android app (native or hybrid decision), phone GPS/TTS/ASR, the sensor path decided by R2 | the app runs fully offline on the test phone | Android phone; R2 outcome |
| 8 | Supervised field evaluation with sighted safety monitors; latency and false-alarm study | documented results and limitations | Stages 3–7 |
| (future) | Retraining for more classes, better Car recall, phone-camera models | new validated model | new data |
