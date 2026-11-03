# 1. Project overview and problem statement

## 1.1 Problem statement

People with visual impairments must detect obstacles and find their way through streets that are crowded,
irregular and changing: parked two-wheelers, pedestrians, vehicles, animals, street furniture. A white cane
reaches about one metre. Smartphone navigation apps assume the user can read a screen, and most need a
permanent internet connection.

**NeuroSonic** is a research prototype of a **voice-first, offline-capable assistive navigation and
environmental-awareness system**. It is built on an existing research model, **WOAD** ("A Wearable Obstacle
Avoidance Device for Visually Impaired Individuals with Cross-Modal Learning"), whose original code and trained
checkpoint are preserved unchanged in `F:\Projects\WOAD-Research\original\`.

The user should be able to:

1. hear obstacle warnings from a camera;
2. choose a destination and get spoken walking directions on an offline map of **Vellore, Tamil Nadu**;
3. control the system by voice;

all without looking at the phone screen, and without needing the internet.

## 1.2 What the project contains

| Layer | Content | Main location |
|---|---|---|
| Research foundation | WOAD cross-modal detector (near-infrared + colour-mapped depth, classes person / Ebike / Car). Re-implemented for inference, verified bit-exact against the original code | `woad/`, `weights/best.pt`, `tools/verify_equivalence.py` |
| Evaluation | dataset audit, mAP evaluation, IR-brightness experiment | `tools/evaluate.py`, `docs/EVALUATION.md`, `experiments/` |
| Application server (laptop) | stdlib HTTP(S) server, detection service, SQLite store, Piper TTS, Vosk speech recognition, offline map + A* router, SSDLite RGB detector, local TLS certificates | `neurosonic/`, `neurosonic_app.py` |
| Mobile web client (phone or laptop browser) | accessible UI, speech queue, GPS, route following, offline map renderer, microphone recorder, camera streaming, event-camera simulation | `web/` |
| Tests | 204 Python test cases (one of them runs 32 Node tests) + 1 opt-in live cloud test, 7 browser end-to-end scripts | `tests/` |

## 1.3 Objectives and how far each was reached

The **status vocabulary** below is used throughout this documentation and must not be blurred during the viva:

| Term | Meaning |
|---|---|
| **Implemented** | the code exists in the repository |
| **Automated-tested** | an automated test exercises it and passes (`tests/`, run 2026-11-02 after Sprint 1: 204 tests OK, including 32 Node tests) |
| **Browser-E2E-tested** | exercised in a real (headless) Chrome by a script in `tests/js/*_cdp.mjs`, with Chrome's fake camera and microphone where needed; PASS recorded 2026-11-02 |
| **Simulated** | runs on recorded data, synthetic speech or a simulated GPS position, not on live sensors |
| **Physically verified** | confirmed by a person on the real device in the real world. **Nothing on the iPhone and nothing in the street has been physically verified yet** |

| Objective | Status | Evidence |
|---|---|---|
| Re-run the original WOAD model faithfully | implemented, automated-tested | identical outputs (max abs. difference 0.0) to the original code, `tools/verify_equivalence.py`; `tests/test_model.py` |
| Measure WOAD accuracy | implemented; measured on the *published* dataset only | person AP@0.5 = 0.218 (val, 129 people) and 0.173 (train split), cross-dataset; the authors' 0.669 mAP could not be reproduced because their training data is not published (`docs/EVALUATION.md`) |
| Spoken obstacle alerts | implemented, automated- and browser-E2E-tested (simulated input) | `woad/alerts.py`, `tests/test_alerts.py`, `tests/js/ui_final_cdp.mjs` |
| Live phone-camera awareness | implemented; browser-E2E-tested with a fake camera video of recorded frames | `neurosonic/awareness.py`; **not** validated on real streets |
| Neural voice (Piper, Indian English) | implemented, automated-tested, browser-E2E-tested on the laptop | `neurosonic/tts.py`; **iPhone playback not yet confirmed** |
| Offline voice commands (Vosk) | implemented, automated-tested with synthetic speech, browser-E2E-tested via fake microphone | `neurosonic/voicecmd.py`; real human voices not tested |
| Offline Vellore map, search, A* walking routes | implemented, automated-tested (A* = Dijkstra), browser-E2E-tested with a simulated walk | `neurosonic/maps.py`, `web/js/mapview.js` |
| GPS route following and re-routing | implemented; unit-tested and simulated | `web/js/nav.js::followRoute`; **no real walk done** |
| Phone access over HTTPS | implemented, automated-tested (certificates, handshake, MIME types) | `neurosonic/tls.py`, `tests/test_mobile_access.py`; iPhone pending user confirmation |
| Offline operation | tested with internet access **blocked** (in-process and in Chrome) | `tests/_offline.py`; no test with the network physically unplugged |

## 1.4 The single most important architectural fact

NeuroSonic is a **client–server system on a local network**. The **laptop does all the heavy work**:

* WOAD and SSDLite inference;
* Piper speech synthesis;
* Vosk speech recognition;
* routing;
* the database.

The **phone is a thin browser client**. It provides the GPS, camera, microphone and speaker, and shows the
interface.

"Offline" therefore means **no internet is needed**. It does **not** mean the phone works alone. If the phone
cannot reach the laptop over Wi-Fi, NeuroSonic says so and can only fall back to the phone's built-in voice.
See `12_HTTPS_NETWORK_IPHONE.md`.

## 1.5 Safety position

NeuroSonic is an assistive **research prototype**. It is not a replacement for a cane, a guide dog or human
assistance, and it makes no claim of guaranteed obstacle avoidance or route safety. The WOAD model detects three
classes and misses many people on unfamiliar scenes (measured recall about 0.2–0.3). The RGB detector is a
general COCO model (box mAP 21.3) that cannot see steps, kerbs, holes or poles. Routes come from OpenStreetMap
streets only, without pavement or crossing data.
