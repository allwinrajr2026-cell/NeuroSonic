# Project demo: existing implementation and proposed work (differentiation)

This document separates three things clearly:

* **(A)** what the original WOAD research provided;
* **(B)** what this project implemented on top of it (existing and demonstrable today);
* **(C)** what is proposed but not yet implemented or not yet verified.

## A. Base work: the original WOAD research (not our contribution)

Location: `F:\Projects\WOAD-Research\original\` (unchanged).

| Item | Content | State when received |
|---|---|---|
| Cross-modal detector | YOLOv5s-based two-stream network (near-IR + colour-mapped depth) with transformer fusion; classes person, Ebike, Car | trained checkpoint `runs/train/exp72/weights/best.pt` |
| Training/validation scripts | `train.py`, `val.py`, `detect.py` | **broken** with current libraries: single-input calls against a two-input model, `np.int`, `torch.load` defaults, a missing `clouddir` argument; `detect.py` exits before NMS |
| Reported accuracy | mAP@0.5 0.669 (training plot only) | no results file, empty TensorBoard log |
| Data | published `VOCdetiv_data.rar` | turned out to be a *different* dataset (different classes, none of exp72's validation frames) |
| Other parts | FPGA deployment, Android app with a stock COCO TFLite model, RL video compression, CS30 capture SDK | not used, except the SDK finding (vendor colormap) |

## B. Existing implementation (this project; demonstrable now)

| # | Contribution | Where | Verification level |
|---|---|---|---|
| B1 | **Faithful, standalone WOAD inference**: checkpoint loading with hash and architecture checks, training-identical preprocessing, CLI | `woad/`, `woad_detect.py` | automated-tested; outputs identical to the original (max diff 0.0) |
| B2 | **Dataset audit and honest evaluation**: dataset identity checks, an mAP tool using the original metric code, person AP@0.5 0.218/0.173 cross-dataset, IR-brightness experiment | `tools/evaluate.py`, `docs/EVALUATION.md`, `experiments/` | measured |
| B3 | **Alert engine**: confirmation, positions, cooldowns, availability messages; input-quality gate | `woad/alerts.py`, `woad/quality.py` | automated-tested |
| B4 | **NeuroSonic application**: stdlib HTTP(S) server, REST API, SQLite history and places, mobile-first accessible UI | `neurosonic/`, `web/` | automated + browser-E2E-tested on the laptop |
| B5 | **Local neural voice**: Piper, Indian English; iOS-aware playback; priority queue with interruption; fallback | `neurosonic/tts.py`, `web/js/speech.js` | automated + browser-E2E (laptop); **iPhone pending** |
| B6 | **Offline voice commands**: Vosk, two-pass recognition, intent parser, sound-alike place matching | `neurosonic/voicecmd.py`, `web/js/recorder.js` | automated with synthetic speech + browser E2E (fake mic); real voices pending |
| B7 | **Offline Vellore map and walking navigation**: OSM extract, place search, A* routing, turn instructions, route following, re-routing | `tools/build_offline_map.py`, `neurosonic/maps.py`, `web/js/nav.js`, `web/js/mapview.js` | automated (A* = Dijkstra) + browser E2E (simulated walk); real walk pending |
| B8 | **Live phone-camera awareness**: SSDLite320 COCO detector, obstacle classes, chest/handheld wording, urgency heuristic | `neurosonic/awareness.py`, `app.js` | automated + browser E2E (fake camera with recorded frames); real streets pending |
| B9 | **Phone connectivity**: local CA (iOS-compliant certificates), robust TLS server, firewall check, setup page | `neurosonic/tls.py`, `server.py`, `netcheck.py` | automated-tested |
| B10 | **Event-camera simulation** (demo): frame differencing, motion alerts | `web/js/eventsim.js` | automated + browser E2E; explicitly *not* obstacle detection |
| B11 | **Test suite**: 204 tests (incl. 32 Node tests), 7 browser E2E scripts, an offline guard, 1 opt-in live cloud test | `tests/` | all pass (2026-11-02) |

## C. Proposed work (not implemented, or implemented but not physically verified)

| # | Proposal | Why it is needed | Dependency |
|---|---|---|---|
| C1 | **Physical acceptance tests** on the iPhone (voice, microphone, camera), a physically offline test, and a short real walk in Vellore with a sighted companion | nothing has been physically verified yet | the user's iPhone, the field site |
| C2 | **Assistive RGB detector**: a Vellore street dataset; measure SSDLite; fine-tune or replace it (YOLO family); add steps/kerbs/poles/holes | the current detector is generic (COCO mAP 21.3) and blind to ground hazards | data collection and labelling |
| C3 | **Live WOAD with the CS30 sensor**: SDK capture bridge, the vendor colormap, exposure settings matching training, **metric distance from raw depth** | WOAD cannot run live today; distances are not available | CS30 hardware |
| C4 | **Standalone phone app**: on-device inference (TFLite/Core ML/ONNX), on-device Piper/Vosk, background operation | the phone currently depends on the laptop | mobile build effort, validation of the exported models |
| C5 | **Better place-name recognition**: a Vellore lexicon/grammar or a larger model; real-user recordings | spoken destinations are right first only 10/24 times (synthetic) | recordings |
| C6 | **Pedestrian routing**: footway preference, crossings, a larger region, buildings | OSM data is sparse; routes follow major roads | better data |
| C7 | **Orientation-aware guidance** (compass, handheld mode) | turn words assume the user faces along the route | device sensors |
| C8 | **Security and licences**: pairing/authentication; a GPL/AGPL review | the API is open on the LAN; copyleft voice components | — |
| C9 | **User study** with visually impaired participants; tune thresholds and wording | defaults are engineering guesses | ethics approval |

## Demo storyline: one sentence per part

1. **"We started from a research model that could not even run"** (A). We made it run identically and measured
   it honestly (B1, B2).
2. **"We turned it into a voice-first assistant"** (B3–B8): the laptop does the AI, the phone is the
   eyes/ears/mouth, and nothing needs the internet.
3. **"Here is what is still a proposal"** (C), especially physical validation, ground hazards and a standalone
   phone app.
