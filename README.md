# NeuroSonic

**A voice-first, offline-capable walking-awareness prototype for blind and low-vision users.**

An iPhone acts as a thin client (camera, microphone, GPS, speaker). A laptop with an NVIDIA GPU runs object detection
(RF-DETR Nano, FP16), tracking that cancels out the phone's own motion, walking-path guidance, a neural voice, offline
speech commands and offline walking routes. The phone speaks only what matters:
*"Path appears clear"*, *"Caution. A person is moving into your path from the left."*, *"Stop."*

The project also contains a verified Windows re-implementation of the base paper's cross-modal (near-IR + depth)
detector, **WOAD** (Gao et al., *Nature Communications* 16, 2857, 2025).

> [!WARNING]
> **Research prototype, not a safety device.** It doesn't measure distance. It can't see steps, kerbs, potholes,
> poles or walls, and it only sees what is in front of the camera. It has **not** been tested on a physical iPhone
> while walking or with visually impaired users. Never use it in place of a cane, a guide dog or human assistance.

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Results](#results)
- [Quick start](#quick-start)
- [Repository structure](#repository-structure)
- [Tests](#tests)
- [Project submission documents](#project-submission-documents)
- [Documentation](#documentation)
- [Limitations](#limitations)
- [Licences and credits](#licences-and-credits)

## Features

| Feature | How it works | Needs internet? |
|---|---|---|
| Walking-path guidance | RF-DETR Nano on the GPU (SSDLite on the CPU as automatic fallback) → path region → 5 confirmed states | No |
| Moving-object events | ByteTrack-style tracker + optical-flow camera-motion compensation → "entering your path" / "crossing in front" | No |
| Neural voice | Piper (Indian English) on the laptop; priority speech queue on the phone; "Stop" interrupts | No |
| Voice commands | Push-to-talk → Vosk (Indian English) → intent ("navigate to …", "repeat", "stop") | No |
| Offline navigation | OpenStreetMap extract of Vellore, A* routing, spoken turn-by-turn from phone GPS | No |
| History | Spoken alerts saved as text in SQLite (no images stored) | No |
| Scene description (opt-in) | One photo, after consent → Google Gemini → filtered spoken answer | **Yes** |
| WOAD research mode | Replay recorded IR + depth frames through the base-paper model and its alert engine | No |

## Architecture

```text
 iPhone Safari (web/)                                           Laptop (neurosonic_app.py, Python stdlib HTTPS server)
 ───────────────────                                            ─────────────────────────────────────────────────────
 camera ── 320 px JPEG / 200 ms ── POST /api/awareness/frame ──► awareness.py
                                                                  ├ quality check (brightness / contrast)
                                                                  ├ detectors.py   RF-DETR Nano · CUDA · FP16  (SSDLite CPU fallback)
                                                                  ├ tracking.py    camera motion (LK + RANSAC) + ByteTrack-style tracker
                                                                  ├ pathguide.py   CLEAR / POSSIBLE / BLOCKED / UNCERTAIN / CAMERA_UNAVAILABLE
                                                                  └ events.py      entering path · crossing in front
                      ◄──────────── JSON (state, events, boxes) ─┘
 speaker ◄── WAV ──────────────── GET  /api/tts ──────────────── tts.py       Piper neural voice
 mic ── 16 kHz WAV ────────────── POST /api/voicecmd ──────────► voicecmd.py  Vosk → intent
 GPS ── from / to ─────────────── POST /api/route ─────────────► maps.py      A* on offline OSM graph
 history ◄─────────────────────── GET  /api/history ──────────── store.py     SQLite (text only)
```

## Results

All numbers were measured on an RTX 4050 Laptop GPU. Result files are in [`outputs/benchmarks/`](outputs/benchmarks)
and [`outputs/eval/`](outputs/eval).

| Detector (365 near-IR validation images) | Device | Median latency | Person AP@0.5 | Recall @ 0.40 | Licence |
|---|---|---|---|---|---|
| SSDLite320-MobileNetV3 | CPU | 43.7 ms | 0.542 | 0.574 | BSD-3 |
| **RF-DETR Nano (chosen)** | **GPU** | **20.6 ms** | **0.660** | **0.729** | Apache-2.0 |
| YOLO26n | GPU | 11.8 ms | 0.619 | 0.628 | AGPL-3.0 |

| System measurement | Result |
|---|---|
| RF-DETR FP16 vs FP32, paced at 5 fps | median **53.2 ms** vs 66.5 ms, same accuracy (AP 0.6600 vs 0.6597) |
| Camera capture → analysed answer (browser, fake camera) | median **67 ms** |
| 10-minute soak test at 5 fps | 2,980 frames, **0 errors**, flat memory |
| WOAD re-implementation vs original code | max output difference **0.0** |
| WOAD person AP@0.5 on the published dataset | **0.218** (authors report 0.669 mAP; not reproducible with published data) |

The accuracy figures come from near-infrared images, the only labelled data available. Accuracy on real
phone-camera video hasn't been measured.

## Quick start

**Requirements:** Windows 11, Python 3.12, an NVIDIA GPU (optional), `openssl` on `PATH` (for HTTPS), and an iPhone
on the same Wi-Fi.

```powershell
# 1. Environment. GPU (recommended):
python -m venv ..\.venv-gpu
..\.venv-gpu\Scripts\pip install torch==2.15.0+cu132 torchvision==0.29.1+cu132 --index-url https://download.pytorch.org/whl/cu132
..\.venv-gpu\Scripts\pip install rfdetr==1.11.2 numpy==2.5.4 opencv-python==5.0.0.93 piper-tts==1.8.0 `
    onnxruntime==1.31.1 vosk==0.3.45 google-genai==2.34.0
#    CPU only:
#    python -m venv ..\.venv ; ..\.venv\Scripts\pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# 2. Models: not stored in this repository (size and licences). Follow:
#    models/rgb/README.md (SSDLite) · models/tts/README.md (Piper voice) · models/asr/README.md (Vosk)
#    RF-DETR Nano: place rf-detr-nano.pth in models/rfdetr/ (or ~/.roboflow/models/)
#    WOAD checkpoint (research mode only): weights/best.pt from the original WOAD repository

# 3. Run
.\START_NEUROSONIC.ps1            # GPU, HTTPS, background process; -Cpu for the CPU environment
#   or in the foreground:
..\.venv-gpu\Scripts\python neurosonic_app.py --host 0.0.0.0 --https
```

On the iPhone:
1. **One time only:** open `http://<laptop-ip>:8766` and install the *NeuroSonic Local CA* certificate. Then trust it
   under Settings → General → About → Certificate Trust Settings.
2. Open `https://<laptop-ip>:8765` and tap **Start**.

Optional online description: set `GEMINI_API_KEY` on the laptop. The key never reaches the phone.

The full guide is in [`publication/INSTALLATION_AND_DEPLOYMENT.md`](publication/INSTALLATION_AND_DEPLOYMENT.md).

## Repository structure

```text
neurosonic_app.py          entry point: starts every engine and the HTTPS server
START_/STOP_NEUROSONIC.ps1 start / stop as a background process
neurosonic/                backend: server, camera awareness, detectors, tracking, path guidance, events,
                           Piper TTS, Vosk commands, offline maps, SQLite store, TLS, vision/ (Gemini)
web/                       frontend: index.html, style.css, js/ (app, speech queue, navigation, map, recorder)
woad/                      base-paper WOAD model: verified loader, architecture, preprocessing, quality gate, alerts
woad_detect.py             CLI: WOAD detection on IR + depth pairs
woad_replay.py             CLI: replay recorded frames through detector + alert engine
tools/                     benchmarks, evaluation, soak test, equivalence check, figure and map builders
tests/                     204 Python tests (+ Node.js and headless-Chrome browser tests)
maps/vellore/              offline map package (© OpenStreetMap contributors, ODbL)
models/                    download instructions only (weights are not committed)
outputs/                   benchmark and evaluation results
docs/                      technical documentation, evaluation, benchmarks, validation protocol
PROJECT_DOCUMENTATION/     module reference, API reference, data, HTTPS, testing, limitations
publication/               manuscript, slides, user guide, installation guide, testing report
submission/                university review documents (PDF, numbered) and their build sources
```

## Tests

```powershell
..\.venv-gpu\Scripts\python -m unittest discover -s tests -t .
```

Last full run (3 Nov 2026): **204 tests OK** in `.venv-gpu` (1 skipped: the opt-in live Gemini test) and in `.venv`
(3 skipped: GPU only). Browser tests: 7 of 7 passed. Tests that need the model files, the WOAD checkpoint or the
WOAD demo data will be skipped or will fail until those files are in place (see [Quick start](#quick-start)).

## Project submission documents

All deliverables are in [`submission/`](submission), numbered in the order of the submission list.
[`00_Submission_Checklist.pdf`](submission/00_Submission_Checklist.pdf) maps each requirement to its file.

| # | Requirement | File | Pages |
|---|---|---|---|
| 1 | Review 1 (DA1): survey and comparative analysis of publications, patents, products and technology trends (IEEE 2-column, ≥ 7 pages) | [`01_DA1_Review1_Survey_and_Comparative_Analysis.pdf`](submission/01_DA1_Review1_Survey_and_Comparative_Analysis.pdf) | 9 |
| 2 | Review 2 (DA2): base paper redone, gaps, proposed work (IEEE 2-column, ≥ 7 pages) | [`02_DA2_Review2_Base_Paper_Reimplementation_Gaps_and_Proposed_Work.pdf`](submission/02_DA2_Review2_Base_Paper_Reimplementation_Gaps_and_Proposed_Work.pdf) | 7 |
| 3 | Review 3 (DA3): implementation, architecture / methodology, results (IEEE 2-column, ≥ 7 pages) | [`03_DA3_Review3_Implementation_Architecture_and_Results.pdf`](submission/03_DA3_Review3_Implementation_Architecture_and_Results.pdf) | 8 |
| 4 | Project demo: existing implementation vs. proposed work | [`04_Project_Demo_Existing_vs_Proposed.pdf`](submission/04_Project_Demo_Existing_vs_Proposed.pdf) | 2 |
| 5 | Final consolidated project report (≥ 20 pages; one upload for DA1–DA3) | [`05_Final_Consolidated_Project_Report.pdf`](submission/05_Final_Consolidated_Project_Report.pdf) | 53 |
| 6 | IEEE 2-column paper draft (Lab 10, ≥ 14 pages) | [`06_Lab10_IEEE_Two_Column_Paper_Draft.pdf`](submission/06_Lab10_IEEE_Two_Column_Paper_Draft.pdf) | 20 |
| 7 | GitHub link (dataset, source code, other files) and demo video link | [`07_GitHub_Dataset_and_Video_Links.pdf`](submission/07_GitHub_Dataset_and_Video_Links.pdf) | 2 |
| 8 | Scopus-indexed venues (Q1–Q4), book chapter, IPR | [`08_Publication_Venue_Identification.pdf`](submission/08_Publication_Venue_Identification.pdf) | 3 |
| 9 | Lab 9: IPR invention disclosure form (IDF) Part B draft | [`09_Lab9_IPR_IDF_B_Draft.pdf`](submission/09_Lab9_IPR_IDF_B_Draft.pdf) | 7 |

The demonstration video hasn't been recorded yet. The PDFs are generated from the HTML sources in
`submission/_build/` (`python build.py`, headless Chrome).

## Documentation

| Start here | |
|---|---|
| [`docs/NEUROSONIC_FINAL_TECHNICAL_DOCUMENTATION.md`](docs/NEUROSONIC_FINAL_TECHNICAL_DOCUMENTATION.md) | full technical description |
| [`PROJECT_DOCUMENTATION/00_INDEX.md`](PROJECT_DOCUMENTATION/00_INDEX.md) | module, API, data and HTTPS references |
| [`docs/PHASE1_GPU_DETECTOR_BENCHMARK.md`](docs/PHASE1_GPU_DETECTOR_BENCHMARK.md) | detector selection benchmark |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | WOAD reproduction and evaluation |
| [`docs/IPHONE_VALIDATION_PROTOCOL.md`](docs/IPHONE_VALIDATION_PROTOCOL.md) | planned iPhone field validation |
| [`publication/USER_GUIDE.md`](publication/USER_GUIDE.md) | how to use the app |

## Limitations

1. No distance estimation (single RGB camera).
2. No steps, kerbs, potholes, poles or walls: COCO classes only.
3. Forward camera view only.
4. Thresholds are engineering defaults that haven't been validated with users.
5. No physical iPhone or street testing yet. Speech recognition of local place names is weak (10/24 correct).
6. The laptop must be on the same Wi-Fi network as the phone.

## Licences and credits

This repository is licensed under the **GNU Affero General Public License v3.0** ([`LICENSE`](LICENSE)), the same
licence as the original WOAD code it builds on. Third-party models and data keep their own licences:

- **Base paper:** Y. Gao *et al.*, "A wearable obstacle avoidance device for visually impaired individuals with
  cross-modal learning," *Nature Communications* 16, 2857 (2025), doi:10.1038/s41467-025-58085-x. Original code:
  [MMCNJUPT/WOAD](https://github.com/MMCNJUPT/WOAD) (AGPL-3.0). `woad/arch/` and `woad/metrics.py` are copied from
  that code, which is itself derived from Ultralytics YOLOv5 (GPL-3.0).
- **Models:** RF-DETR (Roboflow, Apache-2.0); SSDLite320-MobileNetV3 (torchvision, BSD-3); COCO annotations
  (CC BY 4.0).
- **Voice and speech:** Piper (`piper-tts`, GPL-3.0-or-later); en_IN-spicor voice (AGPL-3.0); Vosk and its model
  (Apache-2.0).
- **Map data:** © OpenStreetMap contributors, ODbL 1.0.
- Online description uses the Google Gemini API, subject to Google's terms.

The full list is in [`PROJECT_DOCUMENTATION/13_DEPENDENCIES_MODELS_LICENCES.md`](PROJECT_DOCUMENTATION/13_DEPENDENCIES_MODELS_LICENCES.md).

**Author:** Allwin Raj, Vellore Institute of Technology, Vellore.
