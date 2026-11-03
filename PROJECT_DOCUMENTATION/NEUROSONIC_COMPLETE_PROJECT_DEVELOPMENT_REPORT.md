# NEUROSONIC — COMPLETE PROJECT DEVELOPMENT REPORT

**Project:** NeuroSonic, an AI-assisted walking-awareness and navigation prototype for visually impaired people
**Base research paper:** WOAD (Wearable Obstacle Avoidance Device), cross-modal obstacle detection, Gao et al., *Nature Communications*, 2025
**Student:** Allwin Raj
**Development period covered:** 2 November 2026 to 3 November 2026 (two working sessions with an AI coding assistant, Claude Code)
**Project folder:** `F:\Projects\WOAD-Research\implementation`

> **Important honesty note.** This report only describes work that was actually done and evidence that was actually recorded. Every number here comes from a result file, a test run or a log in the project. NeuroSonic is a **research prototype, not a safety device**. It does **not** guarantee safe navigation, it does **not** measure distances, and it does **not** see in 360 degrees. Physical testing on the iPhone and outdoors has **not** been completed yet.

---

## 1. Project Introduction

### 1.1 What is NeuroSonic?

NeuroSonic is a software system that helps a visually impaired person understand what is in front of them while walking, and helps them reach a destination. It has two parts:

1. **The phone (iPhone):** the user opens the NeuroSonic web page in Safari. The phone's rear camera, microphone, GPS and speaker are used. The phone does very little computing itself. It is a "thin client".
2. **The laptop:** a Windows laptop with an NVIDIA RTX 4050 graphics card runs the NeuroSonic server. The laptop does all the heavy work: AI object detection, speech generation, speech recognition, map routing and storing history.

The phone sends small camera pictures to the laptop about five times per second. The laptop's AI model finds people, bicycles, vehicles and other objects. It decides whether the walking path looks clear, possibly blocked, or blocked, and whether something is moving into the path. It then sends a short message back, which the phone speaks aloud in a natural-sounding voice. For example:

- "The visible path appears clear. Continue carefully."
- "Caution. An object is detected in the walking path."
- "Stop. The walking path may be blocked."
- "Caution. A bicycle is moving into your path from the left."

The user can also speak commands such as "navigate to CMC Hospital". The laptop then plans a walking route on an **offline map of Vellore** and speaks turn-by-turn directions.

### 1.2 Why did we build it?

The project started from a published research paper called **WOAD**. WOAD is a wearable obstacle detector that uses a special camera (a Synexens CS30 sensor) giving **near-infrared (IR) images and depth images**. Our first goal was to reproduce that research. While doing so, we found that:

- the WOAD model **only works with that special sensor**, which we do not have;
- an ordinary phone camera **cannot** drive the WOAD model;
- on new scenes, the WOAD model missed most people (measured in this project).

So we kept the WOAD work as the research foundation (the "base paper" part). We then built **NeuroSonic**, a practical system that works with an **ordinary iPhone camera** and adds voice, navigation and modern GPU-based AI detection.

### 1.3 What problem does it address?

People who are blind or have low vision face daily difficulties when walking: other people, bicycles, vehicles and objects in their path, and finding their way to a place. The white cane only detects things it touches, at ground level. Guide dogs are expensive and scarce. Many existing apps need the internet, or only describe a scene when asked, rather than continuously watching the path.

NeuroSonic tries to give **continuous, spoken, walking-path awareness and offline navigation** using hardware a student already has: a phone and a laptop. The scale of the problem was documented in the assignment papers from WHO, the Lancet Global Health vision-loss study and India's National Blindness and Visual Impairment Survey (2015–19).

---

## 2. Project Objectives

1. **Reproduce the base paper (WOAD):** get the original trained model running correctly on our Windows laptop, and measure how good it really is.
2. **Build a working assistive app (NeuroSonic)** that runs on an iPhone through the browser, with a laptop doing the processing.
3. **Continuous camera awareness:** detect objects in the phone's live camera view and turn them into short, calm walking-path messages.
4. **Detect events, not only objects:** say when something is *moving into* the user's path or *crossing* in front, while ignoring the user's own walking motion.
5. **Voice-first use:** spoken output with a natural neural voice, and spoken commands, both working **offline**.
6. **Offline navigation:** search places and plan walking routes on an offline Vellore map, guided by the phone's GPS.
7. **Use the laptop's GPU** to make detection faster and more accurate than the first CPU version.
8. **Optional online scene description** (Google Gemini), strictly opt-in, which the walking guidance never depends on.
9. **Privacy:** never save camera images; history stores text only; never expose the API key.
10. **Honest evaluation:** keep laptop benchmarks, automated tests and physical iPhone tests clearly separate, and never invent results.
11. **Prepare academic deliverables:** documentation, viva material, review documents (DA1–DA3), an IEEE paper draft, an IPR disclosure draft and a consolidated report.

---

## 3. How We Started

### 3.1 Starting point

We started with the original WOAD research code (a copy of the authors' GitHub project) in:
`F:\Projects\WOAD-Research\original\Cross-Modal obstacle detection`

It contained the model code (based on YOLOv5), training scripts, and a trained checkpoint, `runs/train/exp72/weights/best.pt`. The dataset folder was empty, and the original dataset paths pointed to the authors' Linux server.

### 3.2 First step: a full read-only audit

The first instruction was to **audit the whole repository without changing anything**. The audit checked the model architecture, the checkpoint, the training/validation/detection scripts, the saved metrics, the dependencies and the dataset paths. Main findings:

- **The exp72 checkpoint works**, but the original scripts cannot run it:
  - the scripts pass one combined image, while the model needs **two separate inputs** (IR image and depth image);
  - `detect.py` is debugging code (hard-coded missing image, an `exit()` call, missing packages);
  - `utils/datasets.py` uses `np.int`, which no longer exists in NumPy 2.x;
  - `torch.load` fails on PyTorch 2.6+ without `weights_only=False`.
- **What the model really expects:** a near-infrared image plus a **colour-mapped depth image**, each 640×480, padded to 640×640. The two streams are fused inside the model by a transformer fusion block.
- **The model:** 7.52 million parameters and 3 classes (person, Ebike, Car).
- **The authors' reported accuracy**, from their training plot: mAP@0.5 = 0.669 (person 0.771, Ebike 0.839, Car 0.395). This is the authors' number, not ours.
- **Misleading files:**
  - a root `best.pt` is a different 5-class model;
  - `yolov5s.pt` is actually a 1-class "tank" detector;
  - the phone app's `.tflite` is an ordinary 80-class model, not WOAD.

### 3.3 Planning decisions approved by the student

- Build all new work in a **separate folder**, `F:\Projects\WOAD-Research\implementation`. Never modify the original repository.
- **Copy the checkpoint and never change the original.** Its SHA-256 fingerprint starts with `da043ff2e1edd393`, and this was re-checked at every stage.
- Write a new clean detection script, `woad_detect.py`, that reproduces the original training preprocessing exactly.
- **Ask before every download.** Report the size and the free disk space first.
- **Back up before every risky change.** The backups are in `implementation\backups\`, one folder per stage.

---

## 4. Development Journey (chronological)

### Stage 1 — Re-implementing the WOAD inference engine (2 Nov)

- **Copied only what was needed:** the 9 model classes the checkpoint needs (`woad/arch/`), the letterbox and NMS helpers (`woad/ops.py`), and a model loader that checks the checkpoint fingerprint (`woad/model_loader.py`).
- **Proved the copy is identical:** `tools/verify_equivalence.py` ran our code and the original code on the same input. The **maximum difference was 0.0**.
- **Built `woad_detect.py`** with exact preprocessing:
  - read both images with OpenCV;
  - 3-pixel median blur on the depth image only;
  - letterbox both images to 640×640;
  - convert the colour order and scale values to 0–1;
  - run `model(ir, depth)`;
  - apply the original NMS (removes duplicate boxes) and map the boxes back to the original image size.
- **Outputs:** annotated images, one JSON file per image pair and a summary `results.json`. Output folders auto-increment, so nothing is overwritten.
- **Rebuilt demo samples:** `tools/reconstruct_val_samples.py` cut 187 IR/depth pairs out of the authors' saved validation pictures and removed the boxes drawn on them.
- **Results:** all 187 pairs processed, 0 failures, about **100 ms per pair on the CPU**.
- **38 regression tests** were written with Python's built-in `unittest`. They cover loading, input shapes, preprocessing, pairing, the CLI and a golden set of expected detections.
- **The tests catch real bugs:** we deliberately broke the pipeline three ways (no median blur, no colour conversion, swapped inputs), and each break failed at least 2 tests.
- **Input-importance check:**
  - swapping the inputs kept only 8% of the normal confidence;
  - blanking the IR image kept 0%;
  - blanking the depth image kept 65%.
  - So IR matters most, and depth contributes about a third.
- **`requirements.txt`** pinned torch 2.15.0, torchvision 0.29.2, numpy 2.5.4 and opencv-python 5.0.0.93.

### Stage 2 — Downloading the dataset and measuring real accuracy (2 Nov)

- **Before downloading**, we read the size from Google Drive's headers: `VOCdetiv_data.rar`, 1,313,438,415 bytes (1.22 GiB), with 94 GB free on F:.
- **After the student approved:**
  - downloaded to `F:\Projects\WOAD-Research\datasets\download\`;
  - checked with `7z t` (no errors across 14,138 files) and recorded the SHA-256;
  - extracted to `datasets\VOCdetiv_data\`.
- **Discovery: this is not the data exp72 was trained on.**
  - Its classes are person, box, bike, doors, poles, signs and zebra crossings. There is no Ebike or Car.
  - None of exp72's 187 validation frames are in it.
- **Built `tools/evaluate.py`** using the original scoring code, copied into `woad/metrics.py`. A test proves it gives exactly the same numbers as the original.
- **Measured result (person class only):**
  - **AP@0.5 = 0.218** on 365 validation images;
  - **0.173** on 1,286 training images.
  - The model is precise but misses most people (37 of 126 found at the 0.25 threshold).
- **Checked all 9 other Drive links without downloading.** Archive indexes only were read. One link was dead, and none contained exp72's data. So **the authors' 0.669 cannot be verified** from published material.
- **Downloaded two more sets** (after approval):
  - `detec_test`: 600 unlabelled IR + depth pairs, 183 MB;
  - a CS30 sensor recording, `test1730450780`: 501 frames, 170 MB.
  - Both were integrity-checked.
- **Detector results on these sets:**
  - `detec_test`: detections in 313 of 600 frames (person 271, Ebike 160, Car 52), with some visible errors.
  - Sensor recording: only 3 detections, all false. Its IR images average a brightness of **59/255**, while the training-like data averages **135–142**.
- **Brightness experiment** (`experiments/ir_brightness_test.py`):
  - darkening good frames removed about 73% of detections;
  - histogram matching recovered 87% on the controlled test;
  - on the real dark recording it found the one real person once, but produced **56 false alarms**.
  - **Decision:** no brightness "fix" was adopted, because false "person" alarms are a safety problem in themselves.
- **`detec_test` became the official demo set** (`demo_data/detec_test/`, with hash manifest). Tests: 46 passing.

### Stage 3 — Replay, input-quality gate and alert engine (2 Nov)

- **`woad/sources.py`:** replays recorded frames as a timed stream.
- **`woad/quality.py` (quality gate):** grades every frame.
  - It rejects frames that are too **dark**, too **low in contrast**, or have mostly **invalid depth**.
  - **Warning level:** mean brightness below 100, or contrast below 40.
  - **Unusable level:** mean below 40, or contrast below 10. Unusable frames never reach the detector.
- **`woad/alerts.py` (alert engine):**
  - **Position:** left / ahead / right, by thirds of the image.
  - **Confidence:** only detections at 0.40 or above count.
  - **Confirmation:** an object must appear in **2 of the last 3 frames** before it is announced.
  - **Repetition control:** repeats only after 15 s or a change of position.
  - **Limits:** at most 2 messages per frame.
  - **System messages:** "Obstacle detection unavailable…" when input is unusable.
- **`woad_replay.py`** writes a text transcript of alerts. Two runs give **byte-identical** transcripts.
- **Results:**
  - `detec_test`: 46 alerts, e.g. "2 people detected ahead.";
  - dark recording: 0 object alerts and 18 "unavailable" system messages.
- Tests: **64 passing**.

### Stage 4 — First NeuroSonic app (2 Nov)

The project was renamed **NeuroSonic**, with a 3–4 hour sprint to make a working prototype.

- **`neurosonic_app.py` + the `neurosonic\` package:** the server (`server.py`), the WOAD service (`service.py`) and SQLite storage (`store.py`).
- **`web\`:** a mobile-first page (`index.html`, `style.css`, JavaScript files).
- **First features:**
  - WOAD live replay and image-pair upload;
  - voice alerts using the phone's built-in voices, plus left/centre/right beeps;
  - basic GPS "distance and compass direction" to a destination;
  - a webcam frame-differencing "event camera simulation", clearly labelled as not WOAD;
  - SQLite history.
- **Testing:** headless Chrome with a fake camera checked the page. Tests: **73 passing**.

### Stage 5 — Fixing iPhone access (2 Nov)

The app worked on the laptop but **stayed blank on the iPhone**. Three causes were found and fixed (details in Sections 9–10):

- the Windows firewall was blocking the phone;
- the server froze during HTTPS handshakes;
- iOS rejected the self-signed certificate.

We added `neurosonic/tls.py`, which creates a **local certificate authority (CA)**, and a **setup page on port 8766** for installing it on the iPhone. Tests: **84 passing**.

### Stage 6 — Voice-first, offline direction: Piper voice and offline Vellore map (2 Nov)

The project direction changed to a **voice-first, offline-capable** assistant.

- **Downloaded:**
  - `piper-tts` 1.8.0 with onnxruntime 1.31.1;
  - the Indian-English neural voice `en_IN-spicor` (63.5 MB, SHA-256 checked against Hugging Face);
  - OpenStreetMap data for Vellore (streets 4.16 MB; land use 0.55 MB; named places 0.17 MB).
  - The buildings download failed (Overpass server "HTTP 502 … at capacity") and was left out.
- **Built `tools/build_offline_map.py`.** The offline map package in `maps/vellore/` is about 2.8 MB. It covers about 15 × 15 km (12.86–13.00 °N, 79.07–79.21 °E), including Vellore city, the Fort, CMC, Katpadi, VIT, Sathuvachari and Bagayam, with **31,439 walkable path points and 813 searchable places**.
- **New modules:**
  - `neurosonic/maps.py`: A* routing (a shortest-path search);
  - `neurosonic/tts.py`: Piper speech with caching;
  - `web/js/nav.js`: route following;
  - `web/js/mapview.js`: map drawing.
- **Tested with the network blocked** (inside Python, and in Chrome with 0 external requests): voice, map, search and routing all worked offline. The routes matched an independent shortest-path check exactly.
- Tests: **99 passing**.

### Stage 7 — Final end-to-end integration (2 Nov)

- **Backup first:** `backups/20261102-123729-before-final-integration/`.
- **Speech priority queue (`web/js/speech.js`):** urgent warnings interrupt routine speech, and an interrupted navigation instruction is replayed once.
- **Offline voice commands:**
  - downloaded `vosk` 0.3.45 and the Indian-English model `vosk-model-small-en-in-0.4`, 37.6 MB;
  - built `neurosonic/voicecmd.py` and `web/js/recorder.js`;
  - the big 🎤 **Speak** button records until the user stops talking.
  - **Commands:** navigate to / search for a place, start or stop navigation, repeat instruction, start or stop awareness, status, help, test voice.
- **Live camera awareness:**
  - downloaded the **SSDLite320 COCO** weights (14.1 MB);
  - built `neurosonic/awareness.py`;
  - the phone sends small JPEG frames to the laptop, which detects general objects.
- **Carrying modes:** chest-mounted ("Person ahead") and handheld ("Person in camera view, left").
- Tests: **114 passing**.

### Stage 8 — Academic documentation (2 Nov)

21 documentation files in `PROJECT_DOCUMENTATION\`, about 34,000 words:

- module reference, API reference, architecture, and an **SYMBOL_INDEX** of every function with line numbers;
- a **60-question viva bank** and a code-demo guide;
- the final report and the "existing vs proposed" document.

A script checked all 263 code line references, and 10 wrong ones were fixed. Invented example numbers found in drafts were removed. **No application code was changed** in this stage.

### Stage 9 — Product refinement (2 Nov)

The student judged the user experience unacceptable: the camera kept repeating object names, and the iPhone layout was poor. Backup: `backups/20261102-134759-before-product-refinement/`.

- **Walking-path guidance (`neurosonic/pathguide.py`).** The lower-middle part of the image is treated as the walking path, and **only changes of state are spoken**. The five states:
  - **clear:** needs 3 good frames;
  - **caution:** confirmed in 2 of 3 frames;
  - **stop:** confirmed in 2 of 3 frames; interrupts directions and repeats every 8 s;
  - **cannot assess:** dark, covered or blurred image. A bad image can never count as "clear";
  - **camera unavailable**.
- **Object Description** became an optional mode, off by default.
- **Voice pacing:** separate cooldowns per message type, a short pause between messages, and warning audio fetched in advance.
- **GPS rules:**
  - fixes worse than 100 m accuracy, or older than 15 s, are ignored;
  - after 20 s without a usable fix, the app says "GPS signal lost. Guidance paused…";
  - re-routing at most once every 15 s.
- **Clearer turn instructions:** Katpadi → CMC now gives 6 instructions, and "the unnamed road" is never spoken.
- **New iPhone interface:**
  - a bottom bar with **Home, Navigate, Speak, History, Settings** and **How it works**;
  - support for the notch and home indicator;
  - **Permissions** and **Offline status** panels;
  - a **Research tools** screen for the WOAD features.
- **Testing:** Chrome emulating an iPhone 17 Pro Max screen. Tests: **141 passing**.

### Stage 10 — Sprint 1: optional online scene description with Gemini (2 Nov)

- **Audit first:** `google-genai` 2.34.0 was already installed, and `GEMINI_API_KEY` was set in Windows user settings. Only its existence was checked, never its value.
- **New package `neurosonic/vision/`:**
  - `base.py`: the provider interface and error types;
  - `gemini.py`: the Gemini provider;
  - `mock.py`: a fake provider for tests, with simulated 503 / timeout / bad output;
  - `assistant.py`: retries, a circuit breaker, rate limits, and a safety filter on the spoken text.
- **Phone side:**
  - a **Describe surroundings** button and a question box on Home;
  - a consent card in Settings, so **no photo is uploaded before the user taps Allow**.
- **New voice intents:** "describe surroundings", plus scene questions.
- **Command-line flags:** `--vision-provider gemini|mock|off` and `--vision-model` (default `gemini-3.8-flash`).
- **The one approved live Gemini test** (`test_street.jpg`) **timed out** after 25.9 s (`ReadTimeout`). It was not retried.
- Tests: **173 passing** (1 opt-in live test skipped).

### Stage 11 — Gemini deadline bug investigation and fix (2 Nov)

The student ran the app on the iPhone. **The app and camera worked**, as the student reported, but Gemini failed with:

- `504 DEADLINE_EXCEEDED`;
- `400 INVALID_ARGUMENT … Minimum allowed deadline is 10s`;
- failures after 2 attempts.

The cause was found in our own retry code (Section 10). After the student approved, the fix was applied:

- a 10-second minimum deadline;
- no retry after a timeout;
- 30 s per attempt and a 45 s total budget;
- a 60 s phone timeout, with the message "Still waiting…" at 15 s.

Tests: **182 passing**. The fix has **not** been confirmed against the real Gemini service, because no further live requests were approved.

### Stage 12 — Real-time perception investigation (2 Nov)

The student asked for a deep technical investigation of real-time awareness. The report `docs/REAL_TIME_VISION_TECHNICAL_INVESTIGATION.md` compared 19 technologies, including:

- detectors: YOLO26, RF-DETR, D-FINE, RT-DETR;
- open-vocabulary detectors and segmentation;
- Depth Anything V2;
- trackers: ByteTrack and BoT-SORT;
- vision-language models, event cameras and iPhone LiDAR.

**Conclusion:** Gemini is too slow (25–30 s or more) for live warnings, so live awareness must be local. The laptop's GPU was unused, because only CPU builds of PyTorch were installed.

### Stage 13 — Phase 1: enabling the GPU and benchmarking detectors (2–3 Nov)

- **Backed up** the production environment's package list (`backups/20261103-000843-env-before-gpu-phase1/`).
- **Created a separate GPU environment**, `F:\Projects\WOAD-Research\.venv-gpu` (4.2 GB):
  - PyTorch 2.15.0 for CUDA 13.2;
  - the download size (2.43 GB) was calculated first;
  - the original `.venv` was left untouched.
- **Downloaded:**
  - YOLO26n (5.5 MB) and YOLO26s (20.4 MB);
  - RF-DETR Nano (366 MB, stored at `C:\Users\Allwin\.roboflow\models\rf-detr-nano.pth`).
- **Benchmarked** SSDLite, RF-DETR Nano, YOLO26n and YOLO26s on the same images, on CPU and GPU (`tools/benchmark_detectors.py`). Results are in Section 11.
- **Decision (Option A, approved):**
  - **RF-DETR Nano** as the main detector on the GPU, because it was the most accurate and has the Apache-2.0 licence;
  - **SSDLite** kept as the automatic CPU fallback.
  - YOLO26 was rejected mainly because its AGPL-3.0 licence would force NeuroSonic's source to be published.

### Stage 14 — RF-DETR integration, tracking and event alerts (3 Nov)

- **Backup:** `backups/20261103-003605-before-rfdetr-integration/`.
- **`neurosonic/detectors.py`:**
  - RF-DETR Nano on the GPU;
  - automatic fallback to SSDLite if the GPU, the package or the weights are missing, or if RF-DETR fails mid-session (the same frame is then re-analysed).
- **`neurosonic/tracking.py`:**
  - follows objects from frame to frame, in the style of ByteTrack;
  - **camera-motion compensation**: the background's motion is measured, so the user's own walking does not look like objects moving.
- **`neurosonic/events.py`:** two event types.
  - **Entering:** "Caution. A person is moving into your path from the left."
  - **Crossing:** "A bicycle is crossing in front of you, from left to right."
  - Each is spoken once per object, and never while the camera shakes or the path state is already "Stop".
  - **"Approaching" alerts were deliberately not added**, to avoid false alarms.
- **Frame interval set by the server:** 200 ms on the GPU (5 frames/s), 400 ms on the CPU.
- **Fixed** PyTorch threads busy-waiting on the CPU (Section 10).
- Tests: **204 passing**, and all **7 browser tests** pass.
- A **usage-limit interruption** happened here. All work was saved, and `HANDOFF_STATUS.md` was written so work could resume.

### Stage 15 — Finalisation: soak test, FP16, figures and publication package (3 Nov)

- **10-minute soak test (`tools/soak_test.py`):** it found **memory growing about 2 MiB per second**. This was fixed by running all inference on one long-lived thread (Section 10).
- **FP16 (half precision) for RF-DETR:**
  - `tools/benchmark_precision.py` measured the same accuracy as FP32 and faster processing;
  - FP32 is used automatically if FP16 fails.
- **Other fixes:**
  - quiet handling of phone disconnects;
  - the status page now shows the correct weights and precision;
  - a detector chip on Home ("RF-DETR · GPU").
- **Figures:** `tools/make_publication_figures.py` regenerated 6 figures from the result files, and each was inspected.
- **Publication package (`publication\`):**
  - `NeuroSonic_Manuscript.pdf` (15 pages);
  - `NeuroSonic_Slides.pdf` (12 slides);
  - a testing report, an installation guide and a user guide.
- **Test protocol:** `docs/IPHONE_VALIDATION_PROTOCOL.md` describes 23 scenarios × 5 trials, with a CSV results template.

### Stage 16 — Release launch scripts (3 Nov)

- **Inspected the running processes:**
  - stopped only obsolete NeuroSonic servers, including the student's old server on port 8765 and two old test servers;
  - left the Blender MCP processes alone;
  - backed up the history database first (`backups/20261103-release-launch/neurosonic.sqlite3`, integrity OK, 1,926 alerts).
- **Created `START_NEUROSONIC.ps1` and `STOP_NEUROSONIC.ps1`** (explained in Section 12).
- **Launched the server as an independent background process**, verified it, and updated `HANDOFF_STATUS.md` and the `README.md`.

### Stage 17 — Assignment documents (3 Nov)

- **Created `Assignment_Submission\`** with 10 PDFs. They are built from HTML sources by `_build\build.py`, which prints them to PDF with headless Chrome.
- **The PDFs:**
  - DA1 (9 pages), DA2 (7 pages) and DA3 (8 pages), in IEEE two-column format;
  - the Final Consolidated Report (53 pages);
  - the Lab 9 IPR IDF-B draft (7 pages);
  - the Lab 10 IEEE paper draft (20 pages);
  - the Demo comparison;
  - the GitHub/dataset/video links document;
  - the publication venue identification;
  - a checklist.
- **Sources:** statistics, patents (9 US patents, each checked on Google Patents), products and papers were checked online. Measured numbers come only from project result files.

### Stage 18 — Final readiness test (3 Nov)

- **Full API walkthrough** on a separate test copy (port 8790, with a throwaway database), then stopped.
- **Read-only checks** on the live server (port 8765).
- Everything passed (Section 11.8).
- **Not yet done:** the formal physical iPhone tests.

---

## 5. Technologies Used

### 5.1 Hardware

| Hardware | Use |
|---|---|
| Windows 11 laptop with an **NVIDIA GeForce RTX 4050 Laptop GPU (6 GB)** and about 15 GB RAM | Runs the whole NeuroSonic server and all AI models. GPU driver version 592.82 |
| **iPhone** (Safari) | Camera, microphone, GPS, speaker and touch screen. The interface was tuned using an iPhone 17 Pro Max screen emulation |
| Home Wi-Fi router | Connects the iPhone and the laptop on the same local network (the laptop's address was 192.168.1.5) |
| Synexens CS30 IR + depth sensor | Used by the original WOAD research. **We did not have it.** We used only its recorded images |

### 5.2 Software and languages

| Item | Version | Why |
|---|---|---|
| Python | 3.12.10 | All server and AI code |
| JavaScript (plain, no framework) | — | Phone web interface. Older syntax was avoided for iOS compatibility |
| HTML / CSS | — | Mobile-first interface |
| Node.js | 24.21.0 | Runs JavaScript unit tests and drives headless Chrome for browser tests |
| Google Chrome (headless) | — | Automated browser tests with a fake camera and microphone; PDF printing of the documents |
| PowerShell | Windows PowerShell 5.1 | Start/stop scripts, firewall setup |
| OpenSSL (command line) | already on the laptop | Creates the local certificate authority and server certificate |
| 7-Zip | already installed | Tests and extracts the dataset archives |
| SQLite (Python built-in) | — | History storage (text only) |
| Python standard library `http.server` (`ThreadingHTTPServer`) | — | The web server. No web framework was needed |
| `unittest` (Python built-in) | — | All Python tests |

### 5.3 Python libraries

| Library | Version | Why |
|---|---|---|
| PyTorch (`torch`) | 2.15.0 (CPU build in `.venv`; `2.15.0+cu132` CUDA build in `.venv-gpu`) | Runs WOAD, SSDLite and RF-DETR |
| torchvision | 0.29.2 (CPU) / 0.29.1+cu132 (GPU) | SSDLite model and image operations |
| NumPy | 2.5.4 | Numerical arrays |
| OpenCV (`opencv-python`) | 5.0.0.93 | Image reading, resizing, blur, letterbox |
| `rfdetr` | 1.11.2 (GPU venv) | RF-DETR Nano detector |
| `ultralytics` | 8.4.198 (GPU venv) | Used **only for benchmarking** YOLO26; not used in the app |
| `piper-tts` | 1.8.0 | Offline neural text-to-speech |
| `onnxruntime` | 1.31.1 | Runs the Piper voice model |
| `vosk` | 0.3.45 | Offline speech recognition |
| `google-genai` | 2.34.0 | Optional Gemini cloud scene description |

### 5.4 AI models

| Model | Size | Licence | Role |
|---|---|---|---|
| WOAD exp72 `best.pt` (YOLOv5-based, IR + depth fusion, 7.52 M parameters) | — | authors' | Base paper re-implementation, replay and research tools |
| **RF-DETR Nano** | 366 MB weights file | Apache-2.0 | **Main live detector** on the GPU, FP16 |
| SSDLite320 MobileNetV3 (COCO) | 14.1 MB | BSD-3-Clause | CPU fallback detector |
| YOLO26n / YOLO26s | 5.5 / 20.4 MB | AGPL-3.0 | Benchmark comparison only |
| Piper voice `en_IN-spicor` | 63.5 MB | AGPL-3.0 (voice), GPL-3.0 (Piper) | Indian-English neural voice |
| Vosk `vosk-model-small-en-in-0.4` | 37.6 MB zip | Apache-2.0 | Indian-English speech recognition |
| Google Gemini `gemini-3.8-flash` | cloud | Google terms | Optional scene description (opt-in) |

### 5.5 Data

| Data | Use |
|---|---|
| OpenStreetMap data for Vellore (ODbL licence) | The offline map |
| `VOCdetiv_data` (published WOAD-related dataset) | Measuring real accuracy (person class) |
| `detec_test` | Demo set |
| CS30 sensor recording `test1730450780` | Brightness and domain-shift experiments |

---

## 6. System Architecture

### 6.1 Overall picture

```
 iPhone (Safari web page – thin client)                Laptop (Python server, neurosonic_app.py)
 ─────────────────────────────────────                ─────────────────────────────────────────────
 Rear camera ── small JPEG every 200 ms ──HTTPS──►  POST /api/awareness/frame
                                                      → detectors.py  (RF-DETR Nano on GPU, FP16;
                                                                        SSDLite on CPU as fallback)
                                                      → tracking.py   (follow objects, cancel camera motion)
                                                      → pathguide.py  (clear / caution / stop / cannot assess)
                                                      → events.py     (entering / crossing)
                                       ◄── JSON ──    → short messages + states
 Speaker  ◄── WAV audio ───────────────────────────  GET /api/tts  → tts.py (Piper neural voice, cached)
 Microphone ── 16 kHz WAV (push-to-talk) ─────────►  POST /api/voicecmd → voicecmd.py (Vosk) → intent
 GPS (stays on phone) ── start + destination ─────►  /api/route → maps.py (A* on offline Vellore map)
 History screen ◄────────────────────────────────── store.py (SQLite, text only)
 "Describe" (opt-in) ── one still photo ──────────►  vision/assistant.py → gemini.py (internet needed)
 Research tools ───────────────────────────────────► service.py → woad/ (WOAD replay, IR+depth upload)
```

### 6.2 Step-by-step flow of one camera frame

1. **Capture:** the phone's `app.js` opens the rear camera at 640×480. The server tells the phone how often to send frames (200 ms on the GPU).
2. **Compress and send:** the phone shrinks the frame and sends it as a small JPEG over HTTPS to `/api/awareness/frame`. No frame is sent while the page is hidden.
3. **Image check:** the laptop decodes the image and checks quality. Dark, covered or blurred images lead to "cannot assess", never "clear".
4. **AI detection:** RF-DETR Nano runs on the GPU in FP16 on a single dedicated inference thread. It returns boxes, class names and confidence scores.
5. **Tracking:** each box is matched to the same object in earlier frames. The background's motion is subtracted, so walking does not create fake movement.
6. **Path decision:** objects in the lower-middle "walking path" region are counted. The state changes only after confirmation, e.g. 2 of 3 frames for "Caution" or "Stop".
7. **Event decision:** if a tracked object moves sideways into the path, or crosses it, an event message is created once.
8. **Reply:** the server sends a JSON answer with the state, any messages and timing information.
9. **Speech:** the phone's `speech.js` puts the message in a priority queue (urgent > system > obstacle > navigation > information/description). It fetches the Piper audio from `/api/tts` and plays it. Urgent messages interrupt less important speech.
10. **History:** the message text (never the image) is saved in SQLite.

### 6.3 Important design decisions

- **The phone is a thin client.** All AI runs on the laptop, because the iPhone browser cannot run these models fast enough. The disadvantage is that the phone needs the laptop and the Wi-Fi.
- **Local first:** walking guidance, voice, voice commands and navigation work **without the internet**. Only the optional Gemini description needs it.
- **Server built on the standard library:** a thread per request, so a slow cloud request never blocks walking-guidance frames.
- **Fallback chain:** RF-DETR on the GPU in FP16 → FP32 → SSDLite on the CPU, chosen automatically.

---

## 7. AI Implementation

### 7.1 What is object detection?

Object detection means finding **what** objects are in an image and **where** they are. The model draws a rectangle ("bounding box") around each object and gives a class name (person, bicycle, car…) and a confidence score between 0 and 1.

### 7.2 RF-DETR Nano

- **RF-DETR** is a modern real-time object detector from Roboflow. It is a **transformer-based** detector (the "DETR" family: DEtection TRansformer). Instead of sliding many candidate boxes over the image like older detectors, it uses "attention" to predict a set of objects directly.
- **"Nano"** is its smallest and fastest version.
- It was trained on the **COCO dataset** (80 common object classes). NeuroSonic uses the classes relevant to walking: people, bicycles, motorcycles, cars, buses, trucks, animals and furniture.
- **Why it was chosen:** in our benchmark it was the most accurate model (person AP@0.5 0.660 vs SSDLite 0.542), it has the permissive **Apache-2.0 licence**, and it runs fast on the GPU.
- **Where it runs:** `neurosonic/detectors.py`, from the `.venv-gpu` environment. The weights are loaded from disk, and nothing is downloaded at start-up.

### 7.3 NVIDIA RTX 4050 GPU and CUDA

- A **GPU** (graphics processing unit) can do thousands of small calculations at the same time, which is what neural networks need. The RTX 4050 Laptop GPU has 6 GB of memory.
- **CUDA** is NVIDIA's software platform that lets programs like PyTorch use the GPU. We installed the CUDA 13.2 build of PyTorch 2.15.0 in a **separate environment** (`.venv-gpu`), so the working CPU environment (`.venv`) was never at risk.
- **Measured effect:** RF-DETR Nano took 121.9 ms per frame on the CPU but 21.3 ms on the GPU (benchmark, FP32).

### 7.4 FP16 (half precision)

- Normally, neural networks compute with 32-bit decimal numbers (**FP32**). **FP16** uses 16-bit numbers. This halves the memory needed and is faster on modern GPUs.
- **Our measurement:** FP16 gave the **same person accuracy** as FP32 (AP@0.5 0.660, recall 0.729), while the median detection time at the app's 5 frames/s dropped from **66.5 ms to 53.2 ms**.
- If FP16 fails, the app automatically uses FP32.

### 7.5 SSDLite fallback

SSDLite320 with a MobileNetV3 backbone is a small CPU-friendly detector. It was the first live detector in NeuroSonic, and it is now the automatic fallback when the GPU is unavailable. It then runs at 400 ms per frame.

### 7.6 Tracking and camera-motion compensation

- **Tracking** links the same object across frames and gives it an ID number. This is in the style of **ByteTrack**, which matches boxes by overlap and uses low-confidence boxes as a second chance.
- **Camera-motion compensation:** when the user walks, everything in the image moves. NeuroSonic estimates how the background moved and removes that motion. Only real object movement is left.

### 7.7 Path states and events (rules, not AI)

These are **engineering rules written by us**, not learned by the model. They decide what to say:

- the walking path is the lower-middle part of the image;
- an object is "in the path" or "at the side";
- the states clear / caution / stop / cannot assess / unavailable change only after confirmation over frames;
- the events "entering" and "crossing" come from the tracked sideways motion.

**The thresholds are our own choices.** They have not been validated with visually impaired users or on real streets.

### 7.8 The WOAD model (base paper)

WOAD fuses two images:

- a near-infrared image;
- a colour-mapped depth image.

They are combined through an 8-block transformer fusion layer inside a YOLOv5-style network with 3 classes. We re-implemented its inference exactly (difference 0.0), and it runs in the app's **Research tools** (replay and image-pair upload). It cannot use the phone camera, because it needs the CS30 sensor's IR + depth input.

---

## 8. Application Features

All features below are implemented and tested on the laptop (automated tests and headless browser tests). **None has been formally validated on the physical iPhone or outdoors.**

### 8.1 Home

- **Start / Stop** walking awareness (the camera stream to the laptop).
- **Detector chip:** shows the active detector, e.g. "RF-DETR · GPU", or SSDLite on the CPU.
- **The five walking-path states** with spoken messages (Section 4, Stage 9).
- **Event alerts:** "moving into your path" and "crossing in front".
- **Object Description switch** (off by default): adds "Person on the left." style messages at low priority.
- **Describe surroundings** button and a question box: the optional Gemini feature, only after consent.
- **Cloud status line**, plus status badges for connection, detection and voice.

### 8.2 Navigate

- An **offline Vellore map** drawn on the phone, centred on the user and following them during guidance.
- **Place search** (813 places/streets) and **saved places** such as "home".
- **Walking route** by A* search on the offline street network, with clear turn instructions.
- **Turn-by-turn spoken guidance** using GPS, with off-route detection and re-routing (at most every 15 s).
- **GPS quality handling:** poor (>100 m) or old (>15 s) fixes are ignored; "GPS signal lost / restored" messages.
- **Location panel:** position, accuracy and the age of the last fix.
- A simulated start and walk option, used for demonstrations and tests. It is clearly simulated.

### 8.3 Speak (central microphone button)

- **Push-to-talk:** records 16 kHz audio until the user stops speaking, then Vosk on the laptop recognises it offline.
- **Commands:** navigate to / search for a place, start / stop navigation, repeat instruction, start / stop awareness, status, help, test voice, describe surroundings, and scene questions.
- **Safety:** for spoken place names, NeuroSonic says which place it picked and plans the route, but **starts guidance only when the user says "start navigation"**.

### 8.4 History

A list of past messages and alerts stored in SQLite, **text only, with no images**, plus counts per type and source.

### 8.5 Settings

- **Test Voice:** plays "Hello. This is NeuroSonic. Your voice assistant is working correctly."
- **Carrying mode:** chest-mounted or handheld. Handheld wording says "camera view" instead of "walking path".
- **Object Description** switch.
- **Online scene description card:** consent (Allow / withdraw) and privacy notes.
- **Permissions panel** (camera, microphone, location) and **Offline status panel** (which engines are local and ready).
- **Research tools** (opened from Settings):
  - WOAD replay with spoken alerts;
  - WOAD IR + depth image-pair upload;
  - the webcam frame-differencing "event camera simulation", labelled as not WOAD.

### 8.6 How it works

An explanation screen with 11 topics and an architecture diagram. It states clearly that the phone depends on the laptop over a local network.

### 8.7 Background features

- **Speech priority queue** with interruption and replay of interrupted navigation instructions.
- **First tap enables sound**, which iOS requires.
- **Connection-loss messages:** "Connection to the laptop lost/restored".
- **Rate limits on Gemini:** one request per 5 s and 60 per hour, plus a circuit breaker (after 3 failures, a 60 s pause).
- **Phone setup page** (port 8766) for installing the NeuroSonic certificate.

---

## 9. Problems We Faced

| # | Problem | Where it appeared |
|---|---|---|
| P1 | The original WOAD scripts could not run the exp72 model: one combined input instead of two, `np.int` removed in NumPy 2, `torch.load` failing in PyTorch 2.6+, broken Windows paths, `detect.py` was debug code | Stage 1 audit |
| P2 | The dataset was missing; the published dataset turned out to be a different one, so the authors' 0.669 mAP could not be reproduced | Stage 2 |
| P3 | Misleading files (a different root `best.pt`, a "tank" `yolov5s.pt`, a non-WOAD `.tflite`) | Stage 1 |
| P4 | The model was "blind" on the dark sensor recording (IR brightness 59 vs 135–142) | Stage 2 |
| P5 | WOAD cannot use a phone camera at all (needs the CS30 sensor) | Stage 2 roadmap |
| P6 | The app loaded on the laptop but stayed blank on the iPhone | Stage 5 |
| P7 | The OpenStreetMap buildings download failed (Overpass "HTTP 502, server at capacity") | Stage 6 |
| P8 | On Windows a second copy of the server could silently share the same port, so an old copy answered requests | Stage 6 |
| P9 | UI bugs: the first tap's layout shift swallowed the Test Voice click; blurry map; unreadable search box; simulated walk stuck on long segments | Stage 6 |
| P10 | Spoken place names were unreliable with the small offline recogniser (correct first time in 10 of 24 tests; e.g. "navigate to Katpadi Junction" heard as "navigate took out body junction") | Stage 7 |
| P11 | The camera feature kept repeating object names, which was poor for a walking user; a big object beside the path wrongly triggered "Stop"; busy scenes caused repeated cautions | Stage 9 |
| P12 | Error replies sometimes never reached the client ("connection aborted") | Stage 10 |
| P13 | The Claude Code terminal could not see `GEMINI_API_KEY`, although it was set in Windows | Stage 10 |
| P14 | The only live Gemini test timed out (25.9 s); later the iPhone showed 504 / 400 deadline errors | Stages 10–11 |
| P15 | Live awareness was limited: SSDLite was weak (no detection on a real Vellore street photo), 2.5 frames/s, GPU unused (CPU-only PyTorch) | Stage 12 |
| P16 | The RF-DETR class import failed in the first benchmark run | Stage 13 |
| P17 | The GPU server used about 45% of all CPU cores, because idle PyTorch threads were busy-waiting | Stage 14 |
| P18 | Memory grew about 2 MiB per second during the soak test (about 7 GB per hour) and latency crept up | Stage 15 |
| P19 | Error tracebacks in the log when the phone closed the page or locked the screen | Stage 15 |
| P20 | The status page named the SSDLite weights even when RF-DETR was running | Stage 15 |
| P21 | Figure text overflowed its boxes; a footnote was cut off | Stage 15 |
| P22 | Documentation line-number updates went wrong twice (once shifted twice, once an encoding error) | Stages 9 and 15 |
| P23 | Old test servers kept running because a stop request was declined in the session; the student's old server held port 8765 | Stages 5–16 |
| P24 | The first `START_NEUROSONIC.ps1` allowed a second copy to start, because Windows' "Listen" port query returned nothing | Stage 16 |
| P25 | Windows `curl` reported "revocation status is unknown" for the local certificate | Stage 16 |
| P26 | The Claude usage limit was reached in the middle of the RF-DETR phase | Stage 14 |
| P27 | Document issues: DA2 was below 7 pages at first, figures were too large, and a wrong statement ("too bright") about the quality gate appeared in a draft | Stage 17 |

---

## 10. How We Solved Them

**P1 – Original scripts broken.**
- We did not edit the original. We wrote a new, clean pipeline in `implementation\woad\` with the two fixes (no `np.int`; `weights_only=False` when loading).
- The new `woad_detect.py` calls the model with two inputs.
- `tools/verify_equivalence.py` proved identical output (max difference 0.0).

```
python woad_detect.py --source demo_data/detec_test
```

**P2 – Missing or different dataset.**
- We downloaded the published dataset with a size check first, verified it (`7z t`, SHA-256), and wrote `tools/evaluate.py` with the original scoring code.
- We measured only what can honestly be measured: person AP@0.5 = 0.218.
- We checked all other Drive links by reading archive indexes only.
- The authors' 0.669 is reported as "not verifiable", not as our result.

**P3 – Misleading files.**
The model loader checks the checkpoint fingerprint and refuses the wrong `best.pt` with a clear error.

**P4 – Dark IR images.**
- We tested 5 brightness corrections. None was adopted, because the best one created 56 false alarms.
- Instead, the **quality gate** (`woad/quality.py`) refuses dark, low-contrast or invalid-depth frames and says "Obstacle detection unavailable".

**P5 – WOAD cannot use the phone.**
WOAD stays as the research base, with replay and upload. A general RGB detector (SSDLite, later RF-DETR) was added for the phone camera.

**P6 – iPhone blank page.** Three causes:
1. **Firewall.** The Wi-Fi was a "Public" network with no inbound rule. In an administrator PowerShell:
   ```powershell
   Set-NetConnectionProfile -InterfaceAlias "WiFi" -NetworkCategory Private
   New-NetFirewallRule -DisplayName "NeuroSonic LAN" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765,8766 -RemoteAddress LocalSubnet -Profile Private
   ```
   The app now checks for this at start-up and prints the fix.
2. **Server freeze.** Each HTTPS handshake now happens in its own thread with a 10 s timeout (`neurosonic/server.py`). With an idle connection open, requests now answer in 0.03 s instead of timing out.
3. **Certificate rejected by iOS.**
   - `neurosonic/tls.py` creates a "NeuroSonic Local CA" and a server certificate that meets Apple's rules (Subject Alternative Names for 192.168.1.5, 127.0.0.1, localhost and the laptop name, plus serverAuth usage).
   - The user installs the CA once from `http://192.168.1.5:8766`, then enables it in Settings → General → About → Certificate Trust Settings.

Also fixed in this stage:
- the first tap now unlocks audio on iOS;
- explicit file types for scripts and styles;
- newer JavaScript syntax removed for older iOS;
- a visible error if the scripts fail.

**P7 – Buildings download failed.** It was not retried endlessly. The map works without buildings, and this is documented.

**P8 – Shared port.** The server sets `SO_EXCLUSIVEADDRUSE`, so a second copy now refuses to start.

**P9 – UI bugs.** Each was fixed and covered by browser tests: the layout shift, the blurry map rendering, the search box styling and the long-segment stepping.

**P10 – Unreliable spoken place names.**
- Two-pass recognition plus sound-alike place matching (`neurosonic/voicecmd.py`).
- NeuroSonic says which place it picked, and **guidance starts only after "start navigation"**.
- Typed search and saved places remain the reliable way.

**P11 – Repetitive camera speech.**
- Replaced with walking-path **states**, so only changes are spoken.
- Object names became an optional mode.
- An object mostly beside the path now gives "Caution", not "Stop", and busy scenes no longer repeat cautions.

**P12 – Lost error replies.** When an upload was rejected before its body was read, Windows reset the connection. The server now reads the unread body (up to 4 MB) before sending the error. A regression test failed 2 of 4 times before the fix and passed 20 of 20 after.

**P13 – Key not visible.** The server reads `GEMINI_API_KEY` from the Windows user environment in the registry if it is not in its own environment. The key is never printed, stored or sent to the phone.

**P14 – Gemini deadline errors.** Root cause, in our `SceneAssistant` code:
- the retry got only the **leftover** time budget (15 s total, minus about 10 s used, minus the pause, leaves about 4 s);
- the Gemini library sends that timeout to Google as the server deadline (`X-Server-Timeout`);
- Google enforces it (504) and rejects anything under 10 s (400).

The fix (approved):
- `gemini.py`: a minimum 10 s deadline;
- `assistant.py`: every attempt gets the full time, there is **no retry after a timeout**, and one retry is allowed only for a quick 503 or network error when a full attempt still fits;
- defaults: 30 s per attempt and 45 s total, configurable with `NEUROSONIC_VISION_TIMEOUT_S` and `NEUROSONIC_VISION_BUDGET_S`;
- `app.js`: the phone waits up to 60 s and says "Still waiting for the online description. Local walking guidance continues." at 15 s.

Nine new mocked tests failed on the old code and pass on the new.

**P15 – Weak, slow live detection.**
- A separate GPU environment (`.venv-gpu`, PyTorch with CUDA 13.2), a controlled benchmark, and RF-DETR Nano chosen.
- The phone's frame rate is now set by the server: 5 frames/s on the GPU.

**P16 – RF-DETR import error.** The class import in the benchmark script was corrected and the benchmark rerun ("Fix RF-DETR class import and rerun benchmark").

**P17 – CPU busy-waiting.** PyTorch is limited to 2 CPU threads while the GPU does the work. Server CPU dropped from about 45% to about 8% in a direct measurement, with no slower frame times.

**P18 – Memory growth.**
- **Cause:** a new thread for every frame created per-thread GPU library state that was never released.
- **Fix:** all detection runs on **one long-lived inference thread** (`awareness.py`).
- **Result:** the 10-minute soak afterwards showed no upward memory trend, and request medians stayed between 70 and 78 ms (62–104 ms before).

**P19 – Disconnect tracebacks.** Client disconnects are now closed quietly. The disconnect was reproduced, and the server kept serving.

**P20 – Wrong status.** `/api/awareness/status` now reports the active weights and precision.

**P21 – Figures.** All 6 figures were regenerated from the result files and inspected one by one.

**P22 – Line-number errors.** The documentation folder was restored from a copy made just before, then the update was redone in a safe order. Every reference was rechecked.

**P23 – Old processes.**
- The release-launch stage identified every NeuroSonic process by its command line and environment path, and stopped only those.
- The history database was backed up first.
- Blender MCP processes were left alone.

**P24 – Duplicate start.** `START_NEUROSONIC.ps1` now:
- tries an actual TCP connection to the port;
- checks for any running `neurosonic_app.py` from the project's environments;
- waits for the log line `NeuroSonic running:`.

A second start is now refused and names the owning process.

**P25 – curl revocation warning.** This is not a server fault. Use `curl.exe --ssl-no-revoke …`. Python's own certificate verification against the CA succeeded.

**P26 – Usage limit.** Work was saved immediately, and `HANDOFF_STATUS.md` recorded what was done, what was running and the next steps. The next session resumed from it without repeating completed work.

**P27 – Document issues.**
- DA2 got an extra section (repository audit, procedure, threats to validity, parameters).
- Figure width was limited to 70%.
- The wrong statement was corrected to "dark / low contrast / invalid depth".

---

## 11. Testing and Results

### 11.1 Types of testing (kept separate on purpose)

1. **Automated tests:** Python `unittest` (with Node.js tests for the browser logic inside), run in both environments.
2. **Browser tests:** headless Chrome driven over the DevTools protocol, with a fake camera and microphone, at iPhone screen size, with network checks.
3. **Laptop benchmarks:** detector speed and accuracy, FP16, and the soak test.
4. **Physical iPhone and field tests:** **mostly not done yet.** Only the student's own informal report exists: the app and camera worked on the iPhone, while Gemini failed.

### 11.2 Growth of the automated test suite

| Stage | Tests passing |
|---|---|
| WOAD engine | 38 |
| Evaluation script | 44 |
| Demo set | 46 |
| Replay and alerts | 64 |
| First app | 73 |
| iPhone access fixes | 84 |
| Voice and map | 99 |
| Final integration | 114 |
| Product refinement | 141 (includes 29 JavaScript tests) |
| Online vision | 173 |
| Gemini deadline fix | 182 |
| **RF-DETR, tracking, events (final)** | **204** — `.venv-gpu`: 1 skipped (opt-in live Gemini test); `.venv`: 3 skipped (GPU-only tests) |
| Browser tests (final) | **7 of 7 pass** |

Command to run the tests:
```
cd F:\Projects\WOAD-Research\implementation
..\.venv-gpu\Scripts\python -m unittest discover -s tests -t .
```

### 11.3 WOAD (base paper) results

| Measure | Result |
|---|---|
| Our code vs original code | identical output (max difference 0.0) |
| Rebuilt validation pairs | 187 processed, 0 failures, ~100 ms per pair (CPU) |
| Authors' reported mAP@0.5 (training plot) | 0.669 (person 0.771, Ebike 0.839, Car 0.395): **not verifiable** |
| **Our measured person AP@0.5** on the published dataset | **0.218** (val, 365 images) / 0.173 (train, 1,286 images) |
| `detec_test` (600 unlabelled pairs) | detections in 313 frames (person 271, Ebike 160, Car 52); ~74 s total on CPU |
| Dark sensor recording | 3 detections, all false; with the quality gate: 0 object alerts, 18 "unavailable" messages |
| Replay transcript | 46 alerts on `detec_test`; byte-identical across runs |

### 11.4 Detector benchmark (Phase 1, same 640×480 frames, FP32)

| Detector | CPU time | GPU time | Person AP@0.5 | AP@0.5:0.95 | Recall at 0.40 |
|---|---|---|---|---|---|
| SSDLite (old) | 43.7 ms | 42.3 ms (no gain) | 0.542 | 0.208 | 0.57 |
| **RF-DETR Nano** | 121.9 ms | **21.3 ms** | **0.660** | **0.304** | **0.73** |
| YOLO26n | 27.8 ms | 12.4 ms | 0.619 | 0.268 | 0.63 |
| YOLO26s | 57.5 ms | 11.8 ms | 0.628 | 0.292 | 0.65 |

- **Accuracy data:** scored on 365 labelled near-infrared images with 129 people. These are not phone colour photos.
- **Real Vellore street photo:** SSDLite found nothing; RF-DETR Nano found both motorcycles and the rider.
- **GPU memory:** RF-DETR used about 144 MiB.

### 11.5 FP16 vs FP32 (RF-DETR Nano)

| | FP32 | FP16 |
|---|---|---|
| Person AP@0.5 | 0.660 | 0.660 |
| Recall | 0.729 | 0.729 |
| Median detection time at 5 frames/s | 66.5 ms | 53.2 ms |

At 5 frames/s the GPU drops to a low power state between frames, so live times are slower than the benchmark. Mains power and performance mode are recommended for demos.

### 11.6 End-to-end measurements (laptop browser with fake camera; Wi-Fi and iPhone not included)

| Measure | Result |
|---|---|
| Frame rate | 4.91–4.95 frames/s (before: 2.5) |
| Camera capture → analysed answer | median 67 ms, p90 73 ms (final code); earlier 85 ms |
| Event received → speech starts (neural voice) | about 257–260 ms |
| Entering alert on the demo clip | about 1 s after the rider first appears |
| Server CPU while streaming | about 12% of one core (after the thread fix) |

The demo clip is a real recorded person **riding a bicycle**, composited over a real recorded empty corridor. It is not field footage.

### 11.7 Soak test (10 minutes, final code)

- 2,980 frames, **0 errors**, 4.97 frames/s.
- Request medians 70–78 ms throughout, with no memory growth trend.
- 7 of 7 slow (20 s, mock) cloud requests answered while walking guidance continued.
- **Limit:** ten minutes cannot rule out a slow leak over hours.

### 11.8 Final readiness test (3 Nov)

| Check | Result |
|---|---|
| Detector | RF-DETR Nano, cuda, FP16, 200 ms frame interval |
| 30 frames from the demo clip | median 75.6 ms per frame |
| Spoken messages produced | "The visible path appears clear. Continue carefully.", "Caution. An object is detected in the walking path.", "Stop. The walking path may be blocked.", "Caution. A bicycle is moving into your path from the left." |
| Neural voice | WAV audio returned (104,492 bytes) |
| Place search / route | "CMC Hospital" found; 1,330 m route, 10 steps |
| Voice command | Vosk model available; intent "navigate" recognised |
| History | text only, no image fields |
| Live server on port 8765 | page, script and all status endpoints return 200 over HTTPS at 192.168.1.5 with certificate verification; setup page on 8766 returns 200; 0 errors in the log |

### 11.9 Other verified results

- **Offline:** with network access blocked in software, voice, map, search, routing, detection and history worked, with 0 external requests from Chrome.
- **Voice commands:** the fixed commands were recognised 8 of 8 times from synthetic speech. Place names were right first time in 10 of 24 tests.
- **Gemini:**
  - the one live request timed out (`ReadTimeout` after 25.9 s);
  - the student's iPhone session showed 504 and 400 errors before the fix;
  - **no successful live Gemini description has been recorded.**
- **Privacy:** the API key appears in no project file, endpoint or log, and history stores text only.

---

## 12. Remote Access and Demonstration

### 12.1 Cloudflare Tunnel — not used

**Cloudflare Tunnel was not used in this project.** There is no Cloudflare configuration, command or file anywhere in the project or our conversation history. The iPhone was never connected through the internet. Remote access from outside the home network is therefore **not implemented**. It could be future work, but it would need extra security, because the local API has no login.

### 12.2 How the iPhone actually connects: local Wi-Fi + HTTPS

1. The laptop and iPhone join the **same Wi-Fi network**. The laptop's address was 192.168.1.5, checked with `ipconfig`.
2. The server listens on all network interfaces (`--host 0.0.0.0`) on **port 8765** over **HTTPS**. HTTPS is required because iPhone browsers only allow the camera, microphone and GPS on secure pages.
3. **One-time certificate setup:**
   - NeuroSonic creates its own small certificate authority, "NeuroSonic Local CA", using OpenSSL;
   - the user opens `http://192.168.1.5:8766` in Safari, downloads the certificate, and installs it under Settings → General → VPN & Device Management;
   - then the user trusts it under Settings → General → About → Certificate Trust Settings.
4. **One-time Windows firewall rule** for ports 8765 and 8766 on the Private network (commands in Section 10, P6).
5. The user opens `https://192.168.1.5:8765` and taps once to enable sound.

### 12.3 How local GPU processing works during the demo

- The phone only captures, sends, displays and speaks. **All AI runs on the laptop's RTX 4050**, through CUDA, in the `.venv-gpu` environment.
- Frames travel phone → Wi-Fi router → laptop and back, and are never stored.
- Without internet, everything except Gemini keeps working, because the map, voice, recognition and detection models are all on the laptop.

### 12.4 Starting and stopping the application

**Recommended:** use the two scripts. They run the server as an independent background process, so it keeps running when the terminal closes.

```powershell
cd F:\Projects\WOAD-Research\implementation
powershell -ExecutionPolicy Bypass -File .\START_NEUROSONIC.ps1     # RF-DETR on GPU
powershell -ExecutionPolicy Bypass -File .\STOP_NEUROSONIC.ps1      # stop NeuroSonic only
```

**What `START_NEUROSONIC.ps1` does:**
- **Command:** runs `..\.venv-gpu\Scripts\python.exe neurosonic_app.py --host 0.0.0.0 --https` as a detached process, through Windows' WMI process creation.
- **Safety checks:** refuses to start if port 8765 or 8766 is busy, or if another NeuroSonic is running.
- **Start-up:** waits until the server says it is running, then prints the detector, device, precision, the current Wi-Fi IP and the iPhone URL.
- **Files:** writes a log to `logs\neurosonic_<time>.log` and the process number to `data\neurosonic.pid`.
- **Options:**
  - `-Cpu`: SSDLite on the CPU from `.venv`;
  - `-Port N`;
  - `-VisionProvider off|mock|gemini`.

**What `STOP_NEUROSONIC.ps1` does:** stops only processes running `neurosonic_app.py` from this project's environments. It never stops other Python programs and keeps the history. `-WhatIf` only lists what it would stop.

**Manual (foreground) launch:**
```
cd F:\Projects\WOAD-Research\implementation
..\.venv-gpu\Scripts\python neurosonic_app.py --host 0.0.0.0 --https
```

**Survival after Claude Code closes:** the server's parent chain does not include Claude Code, and a controlled test supported this. It has **not been directly observed** after closing Claude Code.

### 12.5 Suggested demonstration sequence

1. Run `START_NEUROSONIC.ps1` and point out "RF-DETR … cuda, fp16, 200 ms" and the iPhone URL.
2. On the iPhone: Settings → Test Voice.
3. Home → Start: show "appears clear". A person or bicycle enters from the side and triggers the event alert. Cover the lens to get "cannot clearly assess".
4. Speak "navigate to CMC Hospital", confirm, and show the offline route and spoken turns. Say clearly if the walk is simulated.
5. Research tools: WOAD replay (the base paper).
6. Show the benchmark table, the FP16 result, the soak test and the test suite.
7. State the limitations and pending tests.

---

## 13. Current Project Status

### 13.1 Completed (with evidence)

- WOAD re-implementation, equivalence proof, evaluation, replay, quality gate and alert engine.
- The NeuroSonic app:
  - RF-DETR Nano FP16 on the GPU with SSDLite fallback;
  - tracking with camera-motion compensation;
  - walking-path states;
  - entering and crossing events;
  - object description;
  - Piper voice and Vosk commands;
  - offline Vellore map with A* routing and GPS guidance;
  - history;
  - iPhone interface;
  - HTTPS with a local CA;
  - optional Gemini (code complete, with the deadline fix).
- 204 automated tests and 7 browser tests passing, soak test passed, final readiness test passed.
- The start/stop scripts. The live server is running on the laptop.
- Documentation:
  - `PROJECT_DOCUMENTATION\` (21+ files);
  - `docs\` (technical documentation, benchmark, investigation, validation protocol);
  - `publication\` (manuscript and slides);
  - `Assignment_Submission\` (10 PDFs).

### 13.2 Partially completed

- **iPhone use:** the student reported that the app and camera worked on the iPhone during the Gemini test. No formal measurements from the iPhone have been recorded.
- **Gemini:** implemented and tested with mocks. The real service has only timed out or errored, and the fix has not been tried live.
- **Survival after Claude Code exits:** supported by a controlled test, but not directly observed.
- **Assignment documents:**
  - they have highlighted blanks to fill (register number, guide, school, dates, contributions);
  - the author line must be confirmed;
  - only some venue quartiles were confirmed (IEEE Sensors Journal Q1, Springer LNNS Q4);
  - the patent search covers US documents only.

### 13.3 Pending (not done)

From `docs\IPHONE_VALIDATION_PROTOCOL.md`:

1. RF-DETR on real iPhone frames: check `/api/awareness/status → clients`.
2. Camera-to-answer latency over Wi-Fi.
3. iPhone voice output and microphone commands.
4. Real scenes (chest-mounted phone, cane, sighted companion, low light, crowds).
5. A real GPS route walk in Vellore.
6. Running with the internet physically disconnected.
7. A live Gemini description (needs approval).
8. A run of 1 hour or longer over Wi-Fi.

Also pending:
- creating the GitHub repository and the demo video (both still blank links; keep them private until IPR advice if a patent is planned);
- user testing with visually impaired people.

---

## 14. Limitations

1. **Not a safety device.** No guarantee of obstacle avoidance or safe navigation.
2. **No distance.** The camera gives no metres. "Ahead" means "in the middle of the view".
3. **Limited field of view.** Only what the rear camera sees: no 360-degree vision, nothing behind or above.
4. **Object types:** about 23 relevant COCO classes. It cannot recognise steps, kerbs, potholes, holes, poles, wet floors or drop-offs.
5. **Accuracy measured on the wrong kind of images:** the person AP was measured on near-infrared images, not phone colour photos. The real street result is a single image.
6. **Rules not validated with users:** path regions, thresholds, timings and wording are engineering guesses.
7. **No "approaching" alerts**, by design, to avoid false alarms while walking.
8. **Phone depends on the laptop and Wi-Fi.** It is not a standalone app, it does not work outdoors without a portable network, and the laptop must stay on.
9. **No login on the local API:** anyone on the same Wi-Fi can reach it.
10. **Offline speech recognition is weak for place names** (10 of 24).
11. **The OpenStreetMap data for Vellore is sparse:** few street names, no pavement or crossing data, no buildings, and Fort paths are not connected to the street network.
12. **Gemini:** slow and unreliable in our tests. When used, it sends images of bystanders to Google, so the user must consent.
13. **WOAD:** needs the CS30 sensor, misses most people in new scenes (AP 0.218), and the authors' accuracy cannot be verified.
14. **Short tests:** the soak test lasted 10 minutes; longer leaks are not ruled out. Live tests used a fake camera and a composited clip.
15. **Licences:** the Piper voice is AGPL-3.0 and Piper is GPL-3.0, which brings obligations if the system is offered as a network service.

---

## 15. Future Improvements

1. **Complete the iPhone and field validation protocol** (23 scenarios × 5 trials), then a study with visually impaired users and orientation-and-mobility experts.
2. **Depth estimation** (e.g. Depth Anything V2 Small, Apache-2.0) to tell which object is closer, plus possible step or drop warnings. Note that this gives relative depth, not metres.
3. **Ground and surface segmentation** (sidewalk, road, stairs, door, pole, railing), after checking the licences.
4. **Safe "approaching" alerts** using tracking, box growth, depth and time-to-contact, tested carefully against false alarms.
5. **Custom training** for potholes, kerbs and Indian street scenes, using public CC BY 4.0 datasets and consented local recordings.
6. **A native iOS app** using the iPhone's LiDAR for real distances, with on-device detection (Core ML), so no laptop is needed.
7. **A portable compute option** (for example a small GPU board) if the phone cannot do it alone.
8. **A local vision-language model** (for example SmolVLM) for offline "describe my surroundings", with Gemini as an optional extra.
9. **Better speech recognition** for place names (a larger model, or on-device recognition).
10. **Security:** pairing or login for the local API. If remote access (for example a Cloudflare Tunnel) is ever added, it needs authentication first.
11. **Live Gemini tuning** (a few approved requests to set realistic time limits; possibly limiting the model's "thinking" time).
12. **Haptic (vibration) feedback** and Tamil language support.
13. **Long soak tests** (hours) and battery and heat measurements.

---

## 16. Conclusion

NeuroSonic began as a reproduction of the WOAD research paper on cross-modal obstacle detection.

**What the base-paper work achieved:**
- We re-implemented the WOAD inference exactly (zero difference from the original code) and evaluated it honestly (person AP@0.5 = 0.218 on the published data).
- We discovered that it depends on a special sensor and on specific image brightness.

**What we then built:** a practical, voice-first assistive prototype that works with an ordinary iPhone and a laptop:
- the iPhone's camera stream is analysed by **RF-DETR Nano running in FP16 on an RTX 4050 GPU**, at about 5 frames per second;
- objects are tracked with camera-motion compensation;
- the results become calm spoken walking-path messages and "moving into your path" / "crossing" alerts;
- the system also offers offline neural speech (Piper), offline voice commands (Vosk), offline Vellore maps with A* routing and GPS guidance, text-only history, and an optional, consent-based Gemini scene description.

**The evidence:**
- 204 automated tests and 7 browser tests;
- a controlled detector benchmark and an FP16 study;
- a 10-minute soak test with 0 errors;
- a final readiness check of every major function.

Along the way we solved real engineering problems: iPhone HTTPS and firewall issues, a server freeze, Gemini deadline bugs, CPU busy-waiting and a memory leak.

The project's main value is that it shows a **complete, honest and reproducible path** from a research paper to a working assistive prototype. It clearly separates what is measured from what is only planned. Its most important next step is real-world testing on the iPhone and outdoors, followed by testing with visually impaired users. Until then, NeuroSonic remains a research prototype, not a safety device.
