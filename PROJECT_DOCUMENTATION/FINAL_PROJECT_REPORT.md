# NeuroSonic: A Voice-First, Offline-Capable Assistive Navigation and Environmental-Awareness Prototype Built on Cross-Modal Obstacle Detection

**Final Project Report (consolidated)**

Project location: `F:\Projects\WOAD-Research\implementation` · Report date: 2 November 2026

---

## Abstract

People with visual impairments need timely information about obstacles around them and reliable directions to
their destination, delivered without having to look at a screen. This report presents **NeuroSonic**, a research
prototype that combines:

* camera-based obstacle awareness;
* spoken alerts and voice commands;
* an offline map with walking-route guidance.

All of it runs without an internet connection. The work builds on WOAD, an existing research model for wearable
obstacle avoidance. WOAD fuses near-infrared and colour-mapped depth images with a transformer inside a YOLOv5s
detector, and recognises persons, e-bikes and cars.

**Re-implementation and evaluation:**

* The original WOAD code no longer ran with current libraries. We re-implemented its inference path and proved it
  equivalent to the original: the maximum output difference was zero.
* We evaluated it honestly. The authors' reported mAP@0.5 of 0.669 could not be reproduced because their data is
  unpublished. On the published dataset, the model reached a cross-dataset person AP@0.5 of 0.218.

**The NeuroSonic application** is built around this foundation. A laptop runs a Python HTTPS server that hosts:

* the WOAD detector;
* a lightweight RGB object detector (SSDLite320-MobileNetV3) for ordinary phone cameras;
* neural text-to-speech (Piper, Indian English);
* offline speech recognition (Vosk);
* an offline OpenStreetMap extract of Vellore with A* walking-route search.

A smartphone opens an accessible web interface that uses its GPS, camera, microphone and speaker.

**Evaluation:** 204 automated tests pass (including 32 JavaScript unit tests), and seven browser end-to-end tests pass in a
real browser engine with internet access blocked. The report distinguishes carefully between functionality that
is implemented, tested automatically, simulated, and physically verified. **No feature has yet been physically
verified on the user's iPhone or in the street.** The limitations, especially the dependence of the phone on
the laptop, are discussed openly.

**Keywords:** assistive technology, visual impairment, obstacle detection, cross-modal fusion, YOLO, SSD,
text-to-speech, speech recognition, OpenStreetMap, A* search, offline-first, accessibility.

---

## Table of contents

1. Introduction
2. Background and related concepts
3. Requirements and system design
4. The research foundation: WOAD
5. Implementation
6. Testing and evaluation
7. Discussion
8. Limitations and future work
9. Conclusion
- References
- Appendix A: API summary · Appendix B: Source inventory · Appendix C: Running the system

---

## 1. Introduction

### 1.1 Motivation

Independent mobility is one of the most important and most difficult everyday tasks for a person with a visual
impairment. The long cane detects obstacles within about a metre of the user and on the ground; a guide dog
extends this but is expensive and not available to everyone. Streets in Indian cities such as Vellore add
specific difficulties:

* mixed traffic of pedestrians, two-wheelers, cars, buses and animals;
* frequently missing or obstructed pavements;
* irregular street furniture.

Smartphones are widely owned and carry cameras, GPS receivers, microphones and speakers. They are therefore an
attractive platform for assistive tools. However, common navigation apps:

* are designed for sighted users who read a screen;
* depend on an internet connection;
* say nothing about obstacles directly in the user's path.

### 1.2 Problem statement

The problem addressed is to build a system that:

* **(i)** detects potential obstacles from a camera and announces them by voice;
* **(ii)** lets the user choose a destination and guides them along a walking route with spoken turn-by-turn
  instructions;
* **(iii)** can be operated by voice;
* **(iv)** does not require an internet connection at run time.

The system must also be honest about what it can and cannot do. It is an assistive research prototype, not a
replacement for a cane, a guide dog or human assistance.

### 1.3 Starting point

The project began from the published code and checkpoint of **WOAD**, "A Wearable Obstacle Avoidance Device for
Visually Impaired Individuals with Cross-Modal Learning". WOAD's detector uses two inputs from a Synexens CS30
RGB-ToF sensor: a near-infrared (IR) image and a depth image colour-mapped by the sensor's SDK. It detects three
classes: person, Ebike and Car.

**Initial audit findings:**

* the training, validation and detection scripts were broken against the current model code and library
  versions;
* the only accuracy figure was a value read from a training plot;
* the published dataset turned out not to be the one the checkpoint was trained on.

### 1.4 Objectives

1. Make the WOAD model run faithfully and verifiably, without modifying the original repository or checkpoint.
2. Measure its accuracy honestly on available data.
3. Turn obstacle detections into a small number of reliable spoken alerts.
4. Provide a mobile, accessible, voice-first application that works without internet.
5. Add a local neural voice, offline voice commands, an offline map of Vellore with walking routes, and live
   camera awareness for ordinary phone cameras.
6. Test every component and report its verification level transparently.

### 1.5 Contributions

* **A verified, standalone inference package for WOAD** (`woad/`): its outputs are identical to the original
  code, and it is guarded by checkpoint hash and architecture checks.
* **An evaluation of WOAD:**
  * on the published dataset, using the original metric code;
  * an analysis showing that the published dataset differs from the training data;
  * an experiment on the model's sensitivity to IR brightness.
* **The NeuroSonic application:**
  * a standard-library HTTPS server with a REST API;
  * a mobile-first web client;
  * an alert engine with temporal confirmation;
  * Piper text-to-speech with an iOS-aware playback and priority/interruption scheme;
  * Vosk voice commands with two-pass recognition and sound-alike place matching;
  * an offline OpenStreetMap package for Vellore with A* routing and route following;
  * an RGB camera detector with chest and handheld wording.
* **A local-network connectivity solution for iPhones:** a local certificate authority issuing iOS-compliant
  certificates, a TLS server design that cannot be blocked by stalled clients, and a firewall diagnostic.
* **A test suite** of 204 automated tests (including 32 JavaScript unit tests) and seven browser end-to-end scripts, including
  a mechanism that proves components work with internet access blocked.

### 1.6 Organisation of the report

* Section 2 introduces the concepts used: object detection, cross-modal fusion, speech technologies,
  OpenStreetMap and A*.
* Section 3 states the requirements and the system design.
* Section 4 describes the WOAD foundation and its verification.
* Section 5 explains the implementation of each subsystem, with references to source files.
* Section 6 reports the testing methodology and actual results.
* Sections 7–9 discuss the results, limitations, future work and conclusions.

---

## 2. Background and related concepts

### 2.1 Object detection with convolutional neural networks

* **CNNs:** a convolutional neural network applies learned filters across an image. Stacked layers turn
  low-level patterns (edges) into high-level ones (object parts), producing feature maps at several scales.
* **Two-stage vs single-stage:** object detectors add *heads* that predict object classes and bounding boxes from
  these feature maps.
  * **Two-stage** detectors first propose candidate regions and then classify them.
  * **Single-stage** detectors predict classes and boxes for a dense set of predefined *anchor* boxes in one
    forward pass. They are faster and suit real-time and embedded use.
  * Two well-known single-stage families are **YOLO** (You Only Look Once) [1] and **SSD** (Single Shot MultiBox
    Detector) [2].
* **Post-processing:** both produce many overlapping candidate boxes, which **non-maximum suppression (NMS)**
  reduces. NMS keeps the highest-scoring box and removes boxes of the same class whose Intersection over Union
  (IoU) with it exceeds a threshold.
* **Evaluation:** detectors are evaluated with **mean Average Precision (mAP)**. For each class, detections are
  sorted by confidence, a precision–recall curve is computed, and its area is the Average Precision (AP).
  * A detection counts as correct if its IoU with an unmatched ground-truth box is at least 0.5 (AP@0.5).
  * Stricter variants average over IoU thresholds from 0.5 to 0.95.
* **Efficient backbones:** **MobileNetV3** [3] is a backbone designed for mobile devices. Its main elements are
  depthwise-separable convolutions, inverted residual blocks, squeeze-and-excitation attention and the
  hard-swish activation. SSDLite combines a MobileNet backbone with lightweight, depthwise-separable SSD
  prediction heads.

### 2.2 Cross-modal fusion and transformers

* **Modalities:** a *modality* is a type of sensor input. Near-infrared images show texture and shape
  independently of visible light. Depth images encode the distance of surfaces.
* **Fusion:** cross-modal fusion combines such inputs so that each compensates for the other's weaknesses.
* **Transformers** use **self-attention**: every token (a feature vector representing an image region) computes
  a weighted combination of all other tokens. The weights come from scaled dot products between learned query
  and key projections.
* **In WOAD:** placing tokens from both modalities into one sequence lets the network learn which IR regions are
  related to which depth regions.

### 2.3 Speech technologies

* **Automatic speech recognition (ASR)** converts audio into text.
  * The **Kaldi** toolkit [4], on which **Vosk** is based, uses an acoustic model and a decoding graph
    (a weighted finite-state transducer). The graph combines phonetic context, a pronunciation lexicon and a
    language model, and a beam search finds the most likely word sequence.
  * Restricting the language model to a small grammar makes command recognition far more robust.
* **Text-to-speech (TTS)** converts text into audio.
  * **VITS** [5] is an end-to-end neural TTS model. It maps phonemes directly to a waveform using a text encoder,
    a stochastic duration predictor, normalising flows and a GAN-trained decoder.
  * **Piper** packages VITS voices as ONNX models with espeak-ng phonemisation for fast CPU inference.

### 2.4 OpenStreetMap and shortest paths

* **OpenStreetMap (OSM)** [6] is a collaboratively edited world map released under the Open Database License.
  * Its data consists of *nodes* (points with coordinates), *ways* (ordered node lists such as streets) and
    *relations*, annotated with key=value *tags*.
  * The **Overpass API** returns OSM data for a query region.
* **Shortest paths:** a road network can be modelled as a weighted graph, and routing becomes a shortest-path
  problem.
  * **Dijkstra's algorithm** [7] expands nodes in order of their distance from the start.
  * **A\*** [8] adds a heuristic estimate of the remaining distance. If the heuristic never over-estimates
    (it is *admissible*), A* still finds the optimal path while exploring fewer nodes. The straight-line distance
    is the classical admissible heuristic for road networks.

### 2.5 Web platform constraints

* **Secure contexts:** browsers expose the camera, microphone and geolocation only to *secure contexts* (HTTPS
  pages or `localhost`).
* **iOS audio:** iOS requires the first audio playback to be started inside a user gesture.
* **iOS certificates:** since iOS 13, TLS server certificates must list the host in the subjectAltName
  extension and carry the serverAuth extended key usage.

These platform rules shaped several design decisions in NeuroSonic.

---

## 3. Requirements and system design

### 3.1 Functional requirements

| ID | Requirement |
|---|---|
| F1 | Detect potential obstacles from camera input and announce them by voice, including their approximate direction |
| F2 | Report clearly when detection is unavailable (no input, dark image, server unreachable) |
| F3 | Speak navigation instructions, obstacle warnings and system status; prioritise urgent warnings; avoid overlapping and stale messages |
| F4 | Provide a working "Test Voice" control that speaks "Hello. This is NeuroSonic. Your voice assistant is working correctly." |
| F5 | Search for destinations by name; select saved places |
| F6 | Compute walking routes offline in Vellore; display them; give spoken turn-by-turn guidance; detect off-route and re-route; announce arrival |
| F7 | Accept voice commands: navigate to / search for a place, start/stop navigation, repeat instruction, start/stop awareness, status, help |
| F8 | Support a chest-mounted and a handheld carrying mode |
| F9 | Keep a local history of alerts and saved places (SQLite) |

### 3.2 Non-functional requirements

* **Offline:** no internet at run time.
* **Accessibility:** large controls, high contrast, screen-reader announcements, operation without looking.
* **Integrity:**
  * never invent detections, locations or directions;
  * never claim distances that cannot be measured;
  * preserve the original research code and checkpoint.
* **Verifiability:** every major feature is covered by tests and documented with its verification level.

### 3.3 Architecture

NeuroSonic is a **client–server system on a local network** (Figure 1; Mermaid source in
`02_SYSTEM_ARCHITECTURE.md`).

* **The laptop** runs `neurosonic_app.py`. This starts a Python HTTP(S) server (`neurosonic/server.py`) and all
  engines:
  * the WOAD detector (`woad/`);
  * the RGB detector (`neurosonic/awareness.py`);
  * Piper (`neurosonic/tts.py`);
  * Vosk (`neurosonic/voicecmd.py`);
  * the offline map and router (`neurosonic/maps.py`);
  * the SQLite store (`neurosonic/store.py`).
* **The phone** loads a web page (`web/`) and acts as a thin client. It provides GPS, camera, microphone, speaker
  and the user interface. It exchanges JSON, WAV audio and JPEG frames with the laptop over HTTPS.

```
 Phone browser (web/)                                Laptop (neurosonic_app.py)
 ┌───────────────────────────────┐   HTTPS (LAN)    ┌──────────────────────────────────────────┐
 │ app.js  speech.js  nav.js     │ ───────────────► │ server.py ─► service.py ─► woad/ (WOAD)  │
 │ mapview.js recorder.js        │  JSON/WAV/JPEG   │           ─► awareness.py (SSDLite)      │
 │ eventsim.js  · GPS · camera · │ ◄─────────────── │           ─► tts.py (Piper) voicecmd.py  │
 │ microphone · speaker          │                  │           ─► maps.py (A*)   store.py     │
 └───────────────────────────────┘                  └──────────────────────────────────────────┘
                     Figure 1: deployment architecture (no internet required)
```

**Why the heavy work runs on the laptop:**

* the WOAD model, Piper, Vosk and SSDLite all run in Python/PyTorch/ONNX on a laptop CPU without conversion;
* one code base serves iPhone, Android and laptop browsers without an app-store build.

**The cost is dependence:** the phone works only while it can reach the laptop over local Wi-Fi. "Offline" in
this report therefore means *no internet required*, not *standalone phone*.

### 3.4 User journey (as implemented)

This walkthrough follows a session and names the code that acts at each step. It describes the implemented
behaviour; steps that depend on the physical phone have not yet been verified on the iPhone.

1. **Opening the application.** The user opens `https://<laptop-ip>:8765` on the phone.
   * The page loads from the laptop and checks the status of the voice engine, voice commands, camera detector
     and offline map (`app.js::init`, `checkVoiceEngine`, `checkVoiceCommands`, `loadMap`).
   * The header badges show whether the internet is available (not required), whether detection is running,
     and the voice state.
   * The first tap anywhere unlocks audio on iOS, and the application says "NeuroSonic ready. Sound is on.
     Offline map of vellore available."
2. **Checking the voice.** In Settings, *Test Voice* speaks the acceptance sentence.
   * The speaking indicator shows "Speaking (neural voice): …".
   * The laptop console prints `[voice] <ip> <device>/<browser>: neural voice PLAYED`. This is how a helper can
     confirm, from the laptop, that the phone actually played the audio.
3. **Choosing a destination.** The user presses the *Speak* button and says, for example, "navigate to Katpadi
   Junction".
   * The phone records until the user stops speaking and sends the audio to the laptop.
   * The laptop recognises the command offline and proposes the most likely place.
   * The phone says "Destination: Katpadi Junction … Route to Katpadi Junction: <distance>, about <minutes>
     minutes. Say start navigation to begin."

   Alternatively, the user can type a name in the Navigate tab's search box or choose a saved place.
4. **Walking.** After "start navigation", the phone follows GPS positions.
   * It announces each turn in advance and again when it is near.
   * It warns about major roads.
   * It recalculates after leaving the route and announces arrival.
   * "repeat instruction" repeats the last navigation message; "status" summarises location, map coverage,
     route progress, camera and voice state.
5. **Environmental awareness.** "start awareness" opens the rear camera. The phone sends frames to the laptop,
   and the walking path is assessed (Walking Guidance, the default): only changes are spoken, such as "Caution.
   An object is detected in the walking path." or "Stop. The walking path may be blocked.". With Object
   Description switched on, object names are added ("Person ahead.", "Car on the left."). A "Stop" warning
   interrupts a navigation instruction, which is replayed afterwards (section 5.12).
6. **Failures.**
   * Darkness: "Camera image is dark…" or "Obstacle detection unavailable…".
   * A denied permission: "Camera permission denied…" or "Location permission denied…".
   * An unreachable laptop: "Obstacle detection unavailable: app server not reachable".

   All are spoken, never silent.

### 3.5 Principles for spoken messages

The wording of every message follows a few rules, visible in the source code:

* **Short, fixed templates filled only with measured facts.**
  * Object alerts contain the class name, the count and the position ("2 people detected ahead"), and nothing
    else (`woad/alerts.py`).
  * Navigation messages contain the turn, the street name from OpenStreetMap, the distance along the route and,
    where the data says so, "This is a major road; take care." (`neurosonic/maps.py::_steps`).
* **No invented quantities.** No distance to obstacles is ever spoken; "ahead" means the middle of the camera
  view. Distances in navigation are path lengths computed from the map, and are rounded (to 10 m, or 0.1 km).
* **Uncertainty is spoken.**
  * A poor GPS fix adds "GPS accuracy is low, about N metres".
  * A sound-alike destination match adds "This was a best guess from your speech".
  * A route that starts from a disconnected part of the map says so.
* **Stale information is never spoken.** Old warnings are dropped, a position older than 30 s is not used, and
  a step that has already been passed is not announced.
* **Order by urgency, not by arrival.** Urgent and obstacle warnings are spoken first and may interrupt routine
  messages.

### 3.6 Key design decisions

| Decision | Rationale |
|---|---|
| Standard-library `http.server` | no framework dependency; low-level control was needed for per-connection TLS handshakes and HTTP byte ranges |
| Plain JavaScript modules, no CDN | works offline; nothing to download; small and readable |
| A single alert engine for all detectors | one tested implementation of confirmation, positioning and repetition control |
| Own A* router and canvas map renderer | no external routing engine or tile server; the whole algorithm is visible and testable |
| Piper and Vosk | both are offline, CPU-capable, and have Indian-English models |
| SSDLite320 for RGB | already included in the installed torchvision; small and fast; its limitations are documented |

---

## 4. The research foundation: WOAD

### 4.1 Architecture

The exp72 checkpoint (`weights/best.pt`) contains a YOLOv5s detector extended with a second input stream and
transformer fusion. The model has 7,521,992 parameters. Its forward pass is implemented in
`woad/arch/yolo.py::Model._forward_once`.

1. **Two streams.** The IR image passes through the first three YOLOv5s layers (Conv, Conv, C3). The depth image
   passes through a separate stem with the same structure. Each produces 64×160×160 feature maps for a
   640×640 input.
2. **Fusion at layer 2.**
   * Both maps are scaled by a fixed gate of 0.5 and average-pooled to 8×8.
   * This gives 64 tokens per modality: 128 tokens of 64 dimensions. A learned positional embedding of shape
     (1, 128, 64) is added.
   * The tokens pass through **eight transformer blocks**. Each block has layer normalisation, multi-head
     self-attention with eight heads, and an MLP with GELU, with residual connections.
   * After a final layer normalisation, the tokens are split back into the two modalities, reshaped to 8×8 and
     upsampled bilinearly. They then multiply (re-weight) each stream's convolved features.
   * The two streams are concatenated and reduced by a convolution.
3. **Detector.** The fused features continue through the YOLOv5s backbone and PAN neck. A detection head
   predicts boxes at three scales with three anchors each: 25,200 candidates per image, each with four box
   coordinates, an objectness score and three class scores.

These dimensions were verified on the loaded checkpoint (`09_WOAD_MODEL.md`).

### 4.2 Inputs and preprocessing

* **The inputs are specific:** an 8-bit near-infrared frame and a depth image colour-mapped by the Synexens SDK
  (`apply_colormap`, a vendor lookup table, not OpenCV's JET).
* **Preprocessing** (`woad/preprocess.py`) reproduces the original validation pipeline exactly:
  * **IR:** resize the long side to 640 (area interpolation when shrinking), then letterbox to 640×640 with grey
    padding;
  * **depth:** a 3×3 median filter, then letterbox;
  * **both:** BGR→RGB, channel-first, scaled to [0, 1].
* The input size is fixed at 640, because the depth branch was letterboxed to a hard-coded 640 during training.

### 4.3 Making the model run again, faithfully

The original scripts called the model with one concatenated input, while the model's forward function expects
two. They also used APIs removed from NumPy and changed in PyTorch. Rather than modifying the original
repository, a standalone package was created:

* **`woad/model_loader.py`** loads the pickled checkpoint by temporarily aliasing the original module names to
  vendored copies of the nine classes it needs. It verifies the SHA-256 of the file and the module tree, and
  rejects the incompatible 5-class checkpoint at the repository root.
* **`woad/ops.py`** contains the original letterbox, NMS and coordinate-scaling functions.
* **`woad/detector.py`** provides `WOADDetector`. It returns detections in original image coordinates.

**Equivalence:** `tools/verify_equivalence.py` runs the original model code in a separate process and the
re-implementation on the same seeded inputs. The **maximum absolute difference of the outputs is 0.0**.

**Test-based checks:**

* swapping the two inputs reduces the detection confidence mass to 8 %;
* blanking the IR input removes all detections;
* blanking depth leaves 65 %.

So both modalities are used, with IR dominant. Deliberately breaking the preprocessing makes the tests fail.

### 4.4 Accuracy evaluation

* **The authors' figure:** mAP@0.5 = 0.669 (person 0.771, Ebike 0.839, Car 0.395), read from a training plot.
* **The published dataset** (`VOCdetiv_data.rar`, 1.31 GB, integrity-checked) was downloaded and inspected. It
  is not the training data of this checkpoint:
  * its classes are person, box, bike, doors, poles and signs;
  * it has no Ebike or Car labels;
  * none of exp72's 187 validation frames appear in it (image-similarity matching against all 1,651 images).
* **Our measurement:** an evaluation tool (`tools/evaluate.py`) reproduces the original validation settings:
  confidence 0.001, NMS IoU 0.6, the original matching and the original AP computation. The AP code was verified
  to be numerically identical to the original. Results for the only shared class, person:

| Split | Images | Person instances | Precision | Recall | AP@0.5 | AP@0.5:0.95 |
|---|---|---|---|---|---|---|
| val | 365 | 129 | 0.345 | 0.310 | **0.218** | 0.073 |
| train | 1,286 | 458 | 0.361 | 0.199 | **0.173** | 0.050 |

* **Interpretation:** the model is precise but misses many people on these unfamiliar scenes, especially
  cyclists and distant people. The authors' figure therefore remains **unverified**.
* **Brightness experiment:** a raw CS30 recording was found to be much darker than the training data (mean IR
  brightness 59 vs about 140). Darkening training-like frames to that level removed about 73 % of detections.
  Histogram correction of the real dark recording produced one correct detection and 56 false alarms. This led
  to the input-quality gate described in Section 5.4.

---

## 5. Implementation

This section describes each subsystem: its purpose, algorithm and code location. Line numbers refer to
`SYMBOL_INDEX.md`.

### 5.1 Server and API (`neurosonic/server.py`)

* **Routing:** the server uses Python's `ThreadingHTTPServer`. Two dictionaries map URL paths to handler
  methods for GET and POST (L392–402).
* **Responses:** handlers return JSON, WAV audio or JPEG images. `_dispatch` (L133–155) converts exceptions into
  HTTP status codes (400, 404, 413, 415, 416, 503, 500), each with a JSON error message.
* **Static files:** served from `web/` with explicit MIME types. Path traversal outside `web/` is rejected.
* **Two problems found during phone testing shaped the server class `NeuroSonicHTTPServer` (L421–459):**
  1. *TLS handshakes.* Originally the listening socket itself was wrapped in TLS, so every handshake ran inside
     `accept()` on the main thread. A single phone connection that did not complete its handshake blocked every
     other client; this was reproduced, with requests hanging for 8 s. The handshake now runs in each
     connection's worker thread, with a 10-second timeout (`finish_request`).
  2. *Port sharing on Windows.* `SO_REUSEADDR` allowed a second instance to bind the same port silently, so an
     outdated instance answered requests. The server now binds exclusively.
* **Range requests:** `_send_media` (L255–272) implements HTTP byte ranges (status 206/416), which iOS uses to
  fetch audio.
* **The API** has 26 endpoint/method combinations (15 GET, 11 POST; HEAD mirrors GET). They cover WOAD replay and upload detection, camera
  awareness, text-to-speech, voice commands, the offline map and routing, alert history, statistics and saved
  places. Appendix A summarises them; `10_API_REFERENCE.md` lists each with real captured responses.

### 5.2 Data storage (`neurosonic/store.py`)

* **Tables:** an SQLite database `data/neurosonic.sqlite3` holds two tables:
  * `alerts`: time, source, kind, text, class, position, confidence, frame;
  * `places`: name, latitude, longitude, with CHECK constraints on the coordinate ranges.
* **Safety:** all statements use parameter placeholders, which prevents SQL injection. A lock serialises access
  from the server's threads.
* **Audio cache:** generated speech is cached on disk by a SHA-256 hash of voice and text.
* **What is not stored:** camera frames, voice recordings and GPS tracks.

### 5.3 Alert engine (`woad/alerts.py`)

Object detectors emit many boxes per second, and individual frames flicker. Speaking every detection would
overwhelm the user. `AlertEngine.process` (L140–249) therefore:

1. Discards detections below a confidence of 0.40.
2. Associates detections with *tracks* across frames by IoU (≥ 0.30, per class).
3. **Confirms** a track only when it has been seen in at least 2 of the last 3 frames.
4. Assigns a position from the horizontal centre of the box: left, middle or right third.
5. Announces a confirmed track once. It repeats only if the position changes, or after 15 s, and treats
   messages for the same class and position within 5 s as already given.
6. Merges groups ("2 people detected ahead"), orders them by class priority and size, and limits the output to
   two messages per frame.

**Availability:** if the input is unusable or missing for one second, the engine announces "Obstacle detection
unavailable: <reason>", and after recovery "Obstacle detection resumed". A watchdog detects a stalled stream.

**Wording and per-detector configuration:** set through `AlertConfig`, which lets the RGB detector reuse the
engine with its own class names and carrying-mode phrasing.

### 5.4 Input quality (`woad/quality.py`)

Motivated by the brightness experiment, `InputQualityChecker.check` classifies each IR frame:

| Status | IR mean / std | Other conditions |
|---|---|---|
| UNUSABLE | mean < 40 or std < 10 | or more than 95 % of depth pixels invalid |
| WARN | mean < 100 or std < 40 | — |
| OK | otherwise | — |

Unusable frames are never passed to the detector. The thresholds were calibrated so that all training-like
frames pass and 99 % of the dark recording is flagged.

### 5.5 Neural text-to-speech (`neurosonic/tts.py`, `web/js/speech.js`)

* **Voice:** the Indian-English Piper voice `en_IN-spicor` (63.5 MB ONNX, AGPL-3.0) is loaded at start-up.
* **`PiperTTS.synthesize`:**
  * validates the text (non-empty, at most 400 characters);
  * looks it up in a memory cache and then a disk cache;
  * otherwise synthesises a 22,050 Hz WAV under a lock.
* **Speed:** the acceptance sentence takes **0.20 s** to synthesise for 5.34 s of audio (real-time factor 0.04).
* **Intelligibility proxy:** the offline Windows speech recogniser transcribed the generated audio with the
  correct sentence structure.

**On the phone:** the `Announcer` class implements a voice-first output policy.

* **Priority queue:** urgent warnings, then system messages, then obstacle warnings, then navigation and motion,
  then information.
* **Repetition and staleness:** a message identical to one spoken in the last 4 s is dropped. A message is
  discarded if it waits longer than its maximum age; an obstacle warning, for example, after 4 s.
* **Interruption:** an urgent, system or obstacle message arriving while a lower-priority message plays
  **interrupts** it. The interrupted navigation instruction is replayed once afterwards.
* **Playback path:** neural audio is fetched as a blob and played through one reusable `<audio>` element.
* **iOS unlock:** inside the user's first tap, the page plays a short silent WAV on that element, resumes the
  audio context and primes the browser's speech engine.
* **Fallback:** if neural playback fails, the same sentence is spoken with the browser's built-in speech, and
  the failure is reported to the laptop console.

### 5.6 Offline voice commands (`neurosonic/voicecmd.py`, `web/js/recorder.js`)

* **Recording on the phone:** the microphone is captured with a `ScriptProcessorNode`, which is compatible with
  iOS. An end-of-speech detector learns the background level and stops after one second of quiet following at
  least 250 ms of speech (or at six seconds). The audio is downsampled to 16 kHz and sent as a 16-bit WAV.
* **Recognition on the laptop** uses the Vosk model `vosk-model-small-en-in-0.4` with **two recognisers on the
  same audio**:
  * a grammar-restricted recogniser that can only output command words;
  * a free-dictation recogniser.

  The first reliably identifies *which command* was spoken; the second provides the words needed for
  destination names. `parse_intent` combines them into one of eleven intents.
* **Place names:** most Vellore place names are not in the recogniser's vocabulary, so destinations are resolved
  in three stages: the user's saved places, then the map's text search, then a **sound-alike** score.
  * The score uses a phonetic key that maps spelled-out letters to letters, merges similar consonants and drops
    vowels. "Katpadi" and the misrecognised "cut body" both produce `ktpt`.
  * Several variants of the query with leading words removed are tried, with a penalty per removed word.

**Measured on synthetic speech** (the Piper voice):

* all eight fixed commands were recognised;
* the correct destination ranked first in 10 of 24 spoken destination commands.

Because destination recognition is unreliable, the application **speaks the chosen place and alternatives** and
starts guidance only after the user says "start navigation". A misrecognition is heard and corrected, never
followed silently.

### 5.7 Live camera awareness (`neurosonic/awareness.py`)

* **Model:** because WOAD cannot use an ordinary camera, the phone camera is served by torchvision's
  **SSDLite320-MobileNetV3-Large** with COCO weights (14 MB; COCO box mAP 21.3 per torchvision).
* **Frame loop:** the phone sends a 320-pixel JPEG about every 400 ms. The server checks brightness, runs the
  detector (about 40–55 ms on the laptop CPU), keeps only 23 obstacle-relevant COCO classes (people, vehicles,
  bicycles, animals including cows, furniture and street objects) with confidence of at least 0.40, and feeds
  them into a per-phone alert engine.
* **Carrying mode:** in **chest mode** the alerts say "ahead / on the left / on the right". In **handheld mode**
  they say "in camera view, left / centre / right" and never "ahead", because a handheld camera need not point
  in the walking direction.
* **Urgency:** an object in the centre third covering at least a quarter of the image is announced with
  "Caution." and the highest priority. This is an unvalidated heuristic for "large in view", **not a distance**.
  A single RGB camera cannot measure distance, and the system never claims one.

### 5.8 Offline map and A* routing (`tools/build_offline_map.py`, `neurosonic/maps.py`)

* **Data:** OSM data for a 15 × 15 km box around Vellore (12.86–13.00 °N, 79.07–79.21 °E) was downloaded through
  the Overpass API: streets, background features and named places. Buildings could not be downloaded because the
  server was at capacity.
* **Package:** a builder converts the data into a 1 MB display file, a walking graph and a search index:
  * walkable ways exclude motorways, construction, and private or foot-prohibited ways;
  * the graph has 31,439 nodes and 34,939 edges, 99.2 % of the nodes in one connected component;
  * the index has 813 searchable names.
* **Search** ranks exact, prefix, substring and all-word matches, and breaks ties by distance.
* **Routing** (`OfflineMap.route`):
  1. Snaps the start and destination to the nearest graph nodes. Disconnected islands, such as the paths inside
     Vellore Fort, are handled by snapping to the main network and adding a spoken note.
  2. Runs **A\*** with the haversine straight-line distance as heuristic (`_astar`, 22 lines, using a binary
     heap). The heuristic is admissible and consistent, so the route is optimal. A test compares A* with an
     independent Dijkstra and finds identical lengths; on 40 random pairs, A* averaged 9.5 ms against 13.0 ms.
  3. Groups the path into steps by street and turn angle, producing instructions such as "Turn right onto
     Krishnagiri - Ranipet Road (Old NH46), then continue for 610 metres. This is a major road; take care."
* **Display:** the map is drawn on a canvas by `web/js/mapview.js`, without tiles or internet. It shows the
  coverage box and the OpenStreetMap attribution.

### 5.9 GPS and route following (`web/js/app.js`, `web/js/nav.js`)

* **Position source:** the browser's `watchPosition` with high accuracy. Permission, signal and timeout errors
  are spoken, and a position older than 30 s is never treated as current.
* **Following the route:**
  * Each position is projected onto the route polyline in local metric coordinates, giving the distance from
    the route and the distance travelled along it.
  * Each instruction is pre-announced about 70 m before its location and spoken at 25 m. Passed instructions are
    skipped.
  * **Off-route** is declared when the user is farther than max(35 m, 1.5 × GPS accuracy) from the route on two
    consecutive fixes. The application then requests a new route from the current position.
  * **Arrival** is announced within max(15 m, the accuracy capped at 40 m) of the destination.
* **Testing without walking:** a clearly labelled simulated position can be advanced along the route for
  laptop demonstrations.

### 5.10 Phone connectivity (`neurosonic/tls.py`, `neurosonic/netcheck.py`)

* **Local certificate authority:** to give the phone a secure context on a private IP address, the server creates
  a local certificate authority and a server certificate. The certificate carries all LAN IP addresses,
  `localhost` and the host name in subjectAltName, has the serverAuth extended key usage, and is valid for 397
  days, as iOS requires.
* **Phone setup:** the CA certificate is installed once on the phone through a separate plain-HTTP setup page
  that serves only the certificate and its fingerprint.
* **Firewall diagnosis:** the original "iPhone stays loading" problem was diagnosed as three causes:
  * the Windows firewall blocking inbound connections on a Public network;
  * a certificate without the required extensions;
  * the blocking TLS handshake.

  A diagnostic module detects the firewall condition and prints the exact administrator commands without
  changing the system.

### 5.11 User interface and accessibility (`web/`)

* **Layout:** a single page with a bottom bar (Home, Navigate, central Speak button, History, Settings, How it
  works); the research tools (WOAD replay, image pair, event-camera simulation) open from Settings. Large touch
  targets, safe-area insets for the iPhone, high contrast, and badges for GPS, voice, laptop and internet state.
* **Accessibility:**
  * an `aria-live` alert banner repeats every spoken message for screen readers;
  * a large **Speak** button is always reachable above the tab bar.
* **No layout shift during a tap:** heights are fixed where text changes during a tap. A layout shift between
  press and release had swallowed the first Test Voice tap in testing.
* **Event-camera simulation:** a frame-differencing demonstration of the event-camera idea, labelled as such. It
  is not obstacle detection.

---

### 5.12 Walking guidance and product refinement (`neurosonic/pathguide.py`)

In the final stage the camera output was redesigned around the user's question "can I keep walking?". The full
description is in `16_PRODUCT_REFINEMENT.md`.

* **Walking-path region.** The lower-central trapezoid of the image stands for the walking path. For each detected
  object, the fraction of the region it covers and the fraction of the object inside the region are computed. Large
  or centred overlaps mean *blocked*, smaller overlaps *possible obstacle*, and other objects are *at the side*.
* **Five states, confirmed over time.**
  * CLEAR_VIEW needs 3 good frames.
  * POSSIBLE_OBSTACLE and BLOCKED_VIEW need 2 of the last 3 frames.
  * UNCERTAIN (dark, covered or blurred image) needs 2 consecutive frames.
  * CAMERA_UNAVAILABLE is reported by the phone.

  Only changes are spoken; a blocked path gets a reminder every 8 s. "Prefer uncertain to a false clear" is the
  design rule.
* **Object Description** (optional) adds object names with left / centre / right; it never interrupts.
* **Voice pacing.**
  * Per-category cooldowns; for example, "clear" is not repeated for 20 s.
  * The newest path state replaces an outdated queued one.
  * A short pause separates messages.
  * Warning audio is prefetched, so a "Stop" is not delayed by synthesis.
* **GPS.**
  * Fixes older than 15 s or less accurate than 100 m are not used.
  * GPS loss during guidance is announced, and re-routing is limited to once per 15 s.
  * Turn instructions measure the angle over 20 m on either side of a junction and merge micro-steps.
* **Interface.** A compact iPhone layout (Home, Navigate, Speak, History, Settings, How it works) with safe-area
  handling, permissions and offline-status panels, and a How It Works screen that states the laptop dependence.

The thresholds are engineering defaults. They were tested on recorded frames, synthetic cases and in desktop Chrome
emulating an iPhone, not with users or outdoors.

### 5.13 Online scene description (Sprint 1)

The direction was changed to online-first AI environmental intelligence. On request, and only after the user
has allowed it, one camera photo goes from the laptop to a cloud vision model (Gemini by default, behind a
provider-independent interface) and the answer is spoken as "AI description: …". Local walking guidance does
not depend on it. The only approved live request timed out after 25.9 s, so no real description quality has been
measured yet. Details: `17_ONLINE_VISION.md` and `docs/ONLINE_VISION.md`.

## 6. Testing and evaluation

### 6.1 Methodology

Testing used five complementary levels:

1. **Python unit and integration tests** (`unittest`, 204 tests after Sprint 1). They use the real models and real demo data
   rather than mocks wherever feasible.
2. **JavaScript unit tests** (Node's built-in runner, 17 tests) for the pure browser logic.
3. **Browser end-to-end scripts** that drive a real headless Chrome through the DevTools protocol:
   * clicks are genuine input events;
   * Chrome's fake camera and microphone play recorded frames and synthetic speech;
   * all internet name resolution is blocked;
   * every network request is logged.
4. **An in-process "no internet" guard** (`tests/_offline.py`) that makes any non-local connection attempt fail
   a test. The guard itself is tested.
5. **An equivalence check** against the original model, plus mutation checks on preprocessing and the server.

### 6.2 Results

On 2 November 2026, after Sprint 1, the full suite ran 204 tests in 83.5 s, all passing; the Node runner passed
32 of 32. (After the product refinement: 141 tests, Node 29 of 29.) (Before the refinement: 114 tests, Node 17 of 17.) The added modules are
`test_pathguide` (20) and `test_refinement_ui_nav` (7).

| Module | Tests | Focus |
|---|---|---|
| test_model | 13 | checkpoint integrity, architecture, forward pass |
| test_preprocess_pairing | 10 | training-faithful preprocessing, input validation, pairing |
| test_detection | 9 | golden detections, box mapping, modality ablations |
| test_cli | 6 | command-line outputs |
| test_evaluate | 6 | metric equivalence with the original, evaluation pipeline |
| test_demo_detec_test | 2 | demo data |
| test_alerts | 18 | alert engine, quality gate, replay |
| test_app | 8 | HTTP API |
| test_mobile_access | 12 | TLS robustness, iOS certificates, MIME types, LAN binding, firewall check |
| test_voice_and_map | 14 | Piper audio, A* = Dijkstra, offline operation, API |
| test_final_integration | 15 | voice commands, camera awareness, offline operation, API |
| test_vision | 40 | online scene description with mock provider and fake Gemini client |
| test_web_js | 1 (32 Node tests) | speech queue, interruption, navigation, GPS quality, map renderer, recorder |
| test_pathguide | 20 | walking-path states, temporal confirmation, Object Description on/off |
| test_refinement_ui_nav | 7 | route steps on real routes, interface structure, How It Works |

**Browser end-to-end results:**

* A real tap on Test Voice played the neural voice to completion (5.24 s) and the server received the playback
  report.
* A simulated walk from Katpadi to CMC Hospital produced spoken turn-by-turn instructions and an arrival
  announcement.
* An urgent warning interrupted a navigation message, which was then replayed.
* The spoken command "navigate to Katpadi Junction", recognised as "navigate took out body junction", selected
  the correct destination and planned a route, and guidance waited for "start navigation".
* Camera frames containing people produced a spoken person alert.
* In every case, no request left the local machine and no JavaScript error occurred.

### 6.3 How individual tests are constructed: examples

**Shortest-path correctness** (`tests/test_voice_and_map.py::test_route_is_shortest_path`):

1. Pick random pairs of nodes from the main connected component of the Vellore graph.
2. For each pair, reconstruct the A* path from its predecessor table and sum the edge lengths.
3. Compute the shortest distance independently with a plain Dijkstra search, written inside the test.
4. Assert that the two lengths are equal to six decimal places.

This checks optimality, not just that a route is returned.

**Real audio, not just an HTTP 200**
(`tests/test_voice_and_map.py::test_acceptance_sentence_is_real_speech_audio`):

1. Synthesise the acceptance sentence with the real Piper voice.
2. Parse the WAV header.
3. Assert the sample rate (22,050 Hz), mono 16-bit format, a duration between 3 and 9 seconds, and a
   root-mean-square level above 500, so silence or noise-free output would fail.

**Spoken commands from speech audio**
(`tests/test_final_integration.py::test_fixed_commands_from_speech`):

1. Generate eight commands with Piper, with random variation switched off so the audio is deterministic.
2. Resample them to 16 kHz.
3. Pass them through the complete recognition pipeline (`VoiceCommands.handle`).
4. Require at least 7 of 8 correct intents (8 of 8 was measured).

**Offline operation** (`tests/_offline.py`):

1. Temporarily replace `socket.connect`, `socket.create_connection` and `socket.getaddrinfo` with versions that
   raise an error for any non-loopback address, and record the attempt.
2. Run components inside this guard: loading the Piper voice, recognising speech with Vosk, detecting objects
   with SSDLite, routing on the map, and serving these through the HTTP API.
3. Assert that the attempt list is empty.

A dedicated test checks that the guard really blocks a connection to an internet host.

**Server robustness**
(`tests/test_mobile_access.py::test_idle_connection_does_not_block_other_clients`):

1. Open three raw TCP connections to the HTTPS server and send nothing (as a stalled phone would).
2. Make a normal HTTPS request with full certificate verification.
3. Assert that it succeeds within two seconds.

When the test was run against the earlier server design, it failed, confirming that it detects the original
defect.

**Browser end-to-end** (`tests/js/ui_final_cdp.mjs`):

1. Launch Chrome with a fake camera playing a video of recorded frames with people, and a fake microphone
   playing a synthetic recording of "navigate to Katpadi Junction".
2. Block all internet name resolution.
3. Through the DevTools protocol, send real mouse events to the buttons.
4. Observe the application's internal trace of every audio clip played.
5. Assert that:
   * the urgent warning interrupted the navigation message, which played again afterwards;
   * the destination was announced and the route planned;
   * guidance did not start by itself;
   * a person alert was spoken;
   * there were no external requests and no JavaScript errors.

### 6.4 Summary of measured performance

| Quantity | Value |
|---|---|
| WOAD forward pass (laptop CPU) | about 100–190 ms |
| SSDLite inference per 320 px frame | about 40–55 ms (observed up to 77 ms) |
| Piper synthesis | 0.20 s for 5.34 s of audio |
| Vosk two-pass recognition | about 0.6 s per command (one measurement) |
| A* routing | mean 9.5 ms (40 random pairs) |
| WOAD person AP@0.5 (cross-dataset) | 0.218 (val), 0.173 (train) |
| Fixed voice commands (synthetic speech) | 8/8 |
| Spoken destinations (synthetic speech) | 10/24 correct first, 11/24 in top 3 |

### 6.5 Defects found through testing

Testing exposed and led to fixes for:

* the server-blocking TLS handshake;
* the iOS-incompatible certificate;
* a stale server instance answering on a shared port;
* a swallowed first tap caused by a layout shift;
* a blurred map canvas;
* a simulated walk that stalled on long segments;
* a missing route because of a disconnected island in the map data;
* a wrong voice destination due to over-aggressive matching.

Each fix is covered by a regression test or an end-to-end check.

### 6.6 Verification levels

| Feature | Implemented | Automated test | Browser E2E | Physically verified |
|---|---|---|---|---|
| WOAD detection (recorded data) | yes | yes | yes | — (no sensor) |
| Spoken alerts and interruption | yes | yes | yes | no |
| Neural voice | yes | yes | yes (laptop) | **no (iPhone pending)** |
| Voice commands | yes | yes (synthetic) | yes (fake mic) | no |
| Offline map and routing | yes | yes | yes (simulated walk) | no |
| GPS route following | yes | yes (logic) | simulated | **no real walk** |
| Live camera awareness | yes | yes (recorded frames) | yes (fake camera) | no |
| Offline operation | yes | blocked network | blocked DNS | no physical disconnect |

---

## 7. Discussion

### 7.1 What the results mean

* **Foundation:** the WOAD foundation is now reproducible, and its behaviour is understood. The model's
  architecture works as described, and both modalities contribute. Its accuracy on the available data is far
  below the authors' reported figure, but the comparison is not like-for-like: the authors evaluated on their
  own unpublished data. The honest conclusion is that the model's generalisation to new scenes is weak, and that
  its published performance remains unverified.
* **The NeuroSonic application** demonstrates that a complete voice-first assistive loop can run on a laptop CPU
  without internet: perception, speech output, speech input, mapping, routing and guidance. Each component is
  fast enough for interactive use: synthesis is 25 times faster than real time, routing takes milliseconds, and
  detection takes tens of milliseconds per frame.
* **The weakest links are perception quality and speech input for local names, not engineering:**
  * the general RGB detector has modest accuracy and cannot perceive ground hazards;
  * the small recogniser does not know Tamil place names.

  In both cases the design compensates by being explicit. The system never claims distances, it confirms
  destinations, and it reports unavailability rather than guessing.

### 7.2 On the offline claim

* **What holds:** NeuroSonic does not need the internet. Tests prove it with network access blocked, in-process
  and in the browser.
* **What does not:** it does need a local network between phone and laptop.

This is a deliberate trade-off. It allowed the research model and the neural speech models to run unchanged,
and one web client to serve all phones. It is also the main obstacle to everyday use, and moving inference onto
the phone is the most important engineering step ahead.

### 7.3 Safety and ethics

The system is an assistive prototype. Missed obstacles are possible: the measured recall of WOAD for people on
new scenes was 0.2–0.3, and the RGB detector is unvalidated. Over-trust is a real risk. The application states
its limits in its settings and documentation. It never uses an old GPS position as current. It never speaks
stale warnings. It says only that the visible path *appears* clear ("Continue carefully"), meaning that no
recognised object is in the path region, after more evidence than a warning needs, and never that it is safe. Real-world use must be preceded by supervised field
tests and a user study.

### 7.4 Existing implementation versus proposed work

For assessment it matters to separate the inherited research, this project's implementation, and what is only
proposed. The full table is in `PROJECT_DEMO_EXISTING_VS_PROPOSED.md`; in summary:

* **Inherited (not our contribution):**
  * the WOAD network design and trained checkpoint;
  * the original training scripts, which were broken;
  * the authors' reported accuracy;
  * the published dataset;
  * an Android demo with a stock COCO model;
  * the CS30 capture SDK.
* **Implemented in this project (demonstrable now):**
  * a verified inference package and evaluation for WOAD;
  * the alert engine and input-quality gate;
  * the complete NeuroSonic server and mobile client;
  * local neural speech with an interruption-capable priority queue;
  * offline voice commands;
  * the Vellore offline map with A* routing, turn-by-turn guidance and re-routing;
  * live RGB camera awareness with carrying modes;
  * iOS-compatible HTTPS connectivity;
  * a test suite with offline guarantees.
* **Proposed (not implemented, or implemented but not physically verified):**
  * physical acceptance tests on the iPhone and in the street;
  * an assistive-specific RGB detector trained on Vellore data, including ground hazards;
  * live WOAD with the CS30 sensor and metric distances from raw depth;
  * a standalone phone application;
  * better place-name recognition;
  * pedestrian-aware routing;
  * orientation-aware guidance;
  * authentication;
  * a user study.

### 7.5 Lessons learned

* **Verify before building.** The decision to prove the re-implementation equivalent to the original model, and
  to audit the dataset before evaluating, prevented two serious errors:
  * presenting an unverified accuracy figure as our own;
  * evaluating on data that was not the model's training domain without saying so.
* **End-to-end tests in a real browser find defects that unit tests cannot.** The swallowed first tap, the
  blurred map canvas and the stale server instance were all found this way.
* **Measure the weak points instead of hiding them.** Spoken-destination accuracy was measured (10 of 24) and
  the interaction was designed around it. That is more useful to a user than an unmeasured "voice navigation"
  feature.

---

## 8. Limitations and future work

**Limitations:**

* the phone's dependence on the laptop;
* no authentication on the local API;
* WOAD requires an unavailable sensor and generalises poorly;
* the RGB detector is generic, unvalidated and blind to ground hazards, and gives no distance;
* spoken place names are unreliable;
* OSM data for Vellore is sparse: few named streets, no pavement or crossing data, no buildings;
* GPS accuracy is coarser than a pavement, and the compass heading is not used;
* nothing has been physically verified on the iPhone or in the street;
* the voice components carry copyleft licences (GPL/AGPL).

**Future work, in order of priority:**

1. Complete the physical acceptance tests: iPhone voice, microphone and camera; a physically disconnected
   network; a short supervised walk in Vellore.
2. Collect and label a Vellore street dataset to measure the RGB detector, then fine-tune or replace it,
   including steps, kerbs, poles and holes.
3. Improve place-name recognition with a Vellore lexicon or a larger model, using real-user recordings.
4. Connect the CS30 sensor to run WOAD live, and derive metric distance from raw depth.
5. Build a standalone phone application with on-device inference and speech.
6. Add pedestrian-aware routing costs and compass-based guidance.
7. Add authentication and review the licences.
8. Conduct a user study with visually impaired participants.

---

## 9. Conclusion

NeuroSonic shows how an existing research model can be turned into a coherent, voice-first assistive
prototype, through careful verification and transparent reporting.

* **Recovery:** the WOAD detector was recovered from a non-functional research code base, proven equivalent to
  the original, and evaluated honestly.
* **Integration:** on this foundation, the project integrated:
  * local neural speech in an Indian-English voice;
  * offline voice commands;
  * an offline Vellore map with optimal walking routes and spoken turn-by-turn guidance;
  * live camera awareness with carrying-mode-aware wording;
  * a robust HTTPS link to phones.

  All of this runs without internet.
* **Testing:** 114 automated Python tests, 17 JavaScript tests and three end-to-end browser tests pass, and the
  report states for every feature whether it is implemented, tested, simulated or physically verified.
* **Remaining steps:** physical validation with the target users, better perception of ground hazards, and a
  standalone phone implementation.

---

## References

[1] J. Redmon, S. Divvala, R. Girshick, A. Farhadi, "You Only Look Once: Unified, Real-Time Object Detection,"
CVPR, 2016.

[2] W. Liu et al., "SSD: Single Shot MultiBox Detector," ECCV, 2016.

[3] A. Howard et al., "Searching for MobileNetV3," ICCV, 2019.

[4] D. Povey et al., "The Kaldi Speech Recognition Toolkit," IEEE ASRU Workshop, 2011.

[5] J. Kim, J. Kong, J. Son, "Conditional Variational Autoencoder with Adversarial Learning for End-to-End
Text-to-Speech (VITS)," ICML, 2021.

[6] OpenStreetMap contributors, OpenStreetMap, https://www.openstreetmap.org (data © OpenStreetMap
contributors, ODbL 1.0).

[7] E. W. Dijkstra, "A Note on Two Problems in Connexion with Graphs," Numerische Mathematik 1, 1959.

[8] P. E. Hart, N. J. Nilsson, B. Raphael, "A Formal Basis for the Heuristic Determination of Minimum Cost
Paths," IEEE Transactions on Systems Science and Cybernetics, 1968.

[9] "WOAD: A Wearable Obstacle Avoidance Device for Visually Impaired Individuals with Cross-Modal Learning,"
original code and README in `F:\Projects\WOAD-Research\original\`.

[10] Software used: PyTorch 2.15 / torchvision 0.29.2 (SSDLite320-MobileNetV3 COCO weights), Piper 1.8.0
(OHF-Voice/piper1-gpl) with the voice `navgurukul-ai-labs/text-to-speech-en-IN-piper`, Vosk 0.3.45 with
`vosk-model-small-en-in-0.4`, ONNX Runtime 1.31.1, OpenCV 5.0, NumPy 2.5.

---

## Appendix A: API summary

| Method and path | Purpose |
|---|---|
| GET `/api/status`, GET `/api/events?since=` | server and model status; alert events |
| POST `/api/replay/start` · `/api/replay/stop`, GET `/api/replay/state` · `/api/replay/frame.jpg` | WOAD replay of recorded IR + depth |
| POST `/api/detect` | WOAD on one uploaded IR + depth pair |
| POST `/api/awareness/frame`, GET `/api/awareness/status` | live RGB camera awareness |
| GET `/api/tts?text=`, GET `/api/tts/status`, POST `/api/voice/report`, GET `/api/voice/reports` | neural voice and playback reports |
| POST `/api/voicecmd`, GET `/api/voicecmd/status` | offline voice commands |
| GET `/api/map/info` · `/api/map/data` · `/api/map/search`, POST `/api/route` | offline map, search, routing |
| GET/POST `/api/places`, POST `/api/places/delete`, GET `/api/history`, POST `/api/history/clear`, GET `/api/stats`, POST `/api/alerts` | SQLite data |

Full details, with captured responses, are in `10_API_REFERENCE.md`.

## Appendix B: Source inventory (application)

| File | Lines | Role |
|---|---|---|
| `neurosonic_app.py` | 132 | start-up |
| `neurosonic/server.py` | 479 | HTTP(S) server and API |
| `neurosonic/service.py` | 234 | WOAD replay and upload |
| `neurosonic/store.py` | 103 | SQLite |
| `neurosonic/tts.py` | 142 | Piper |
| `neurosonic/voicecmd.py` | 230 | Vosk commands |
| `neurosonic/maps.py` | 249 | map, search, A* |
| `neurosonic/awareness.py` | 165 | SSDLite camera awareness |
| `neurosonic/tls.py` | 137 | certificates |
| `neurosonic/netcheck.py` | 68 | firewall check |
| `woad/arch/yolo.py` | 223 | WOAD network |
| `woad/alerts.py` | 249 | alert engine |
| `woad/preprocess.py` | 100 | preprocessing |
| `woad/model_loader.py` | 130 | checkpoint loading |
| `web/js/app.js` | 657 | client glue |
| `web/js/speech.js` | 265 | speech queue and playback |
| `web/js/nav.js` | 161 | navigation maths |
| `web/js/mapview.js` | 186 | map renderer |
| `web/js/recorder.js` | 100 | microphone capture |
| `web/js/eventsim.js` | 67 | event-camera simulation |

## Appendix C: Running the system

```bat
cd F:\Projects\WOAD-Research\implementation
..\.venv\Scripts\python -m unittest discover -s tests -t .           :: run the tests
..\.venv\Scripts\python neurosonic_app.py                             :: laptop browser: http://127.0.0.1:8765
..\.venv\Scripts\python neurosonic_app.py --host 0.0.0.0 --https      :: phone on the same Wi-Fi: https://<laptop-ip>:8765
```

For the phone, a one-time firewall rule and the installation of the local CA certificate are required (see
`12_HTTPS_NETWORK_IPHONE.md`).

## Appendix D: Glossary

| Term | Meaning |
|---|---|
| A* | best-first shortest-path search using f = g + h, where g is the cost so far and h an admissible estimate of the remaining cost |
| Admissible heuristic | an estimate that never exceeds the true remaining cost; guarantees that A* finds an optimal path |
| Anchor (default) box | a predefined box shape at each feature-map position; the detector predicts offsets from it |
| AP / mAP | Average Precision (area under the precision–recall curve of one class) / mean over classes |
| CA (certificate authority) | an entity whose certificate is trusted and which signs server certificates; NeuroSonic creates a local one |
| COCO | Common Objects in Context, a public dataset of 80 object classes used to train general detectors |
| Cross-modal fusion | combining features from different sensor types (here near-infrared and depth) |
| CS30 | the Synexens RGB-ToF sensor used by WOAD (near-IR + depth) |
| Depthwise-separable convolution | a per-channel spatial convolution followed by a 1×1 convolution; much cheaper than a full convolution |
| Haversine | formula for the great-circle distance between two latitude/longitude points |
| IoU | Intersection over Union of two boxes |
| Letterbox | resizing an image into a fixed square while keeping the aspect ratio, padding the rest |
| NMS | non-maximum suppression: removes overlapping duplicate boxes |
| ODbL | Open Database License, the licence of OpenStreetMap data |
| Overpass API | a query service returning OpenStreetMap data for a region |
| Phonetic key | a representation of how a word sounds, used to match misrecognised place names |
| Piper / VITS | offline neural text-to-speech engine / the end-to-end neural TTS model it runs |
| Secure context | an HTTPS (or localhost) page; required by browsers for camera, microphone and GPS |
| SSD / SSDLite | Single Shot MultiBox Detector / its light version with depthwise-separable heads |
| subjectAltName | certificate extension listing the host names/IPs a certificate is valid for; required by iOS |
| Vosk / Kaldi | offline speech-recognition toolkit / the underlying research toolkit |
| WOAD | the research model used as the foundation: cross-modal obstacle detection for a wearable device |
| YOLO | "You Only Look Once", a family of single-stage object detectors; WOAD is based on YOLOv5s |
