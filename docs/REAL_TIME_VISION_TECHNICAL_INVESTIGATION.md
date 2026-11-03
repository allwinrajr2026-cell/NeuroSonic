# NeuroSonic: real-time environmental perception and event detection

## Technical investigation report

* **Date:** 2026-11-02.
* **Scope:** investigation only. No source code was changed, no models or datasets were downloaded, nothing was
  trained, and no live API requests were made.
* **Evidence:** every external claim links to its source. Figures that could not be verified are marked
  **(unverified)** or **(estimate)**. Benchmarks are quoted as published, on the publisher's hardware. None of them
  were measured on NeuroSonic's hardware unless stated.

---

## A. Executive summary

1. **Gemini is not the main bottleneck. It is the wrong layer for real-time warnings.**
   * By design it is on demand, one photo per request, and it depends on the cloud.
   * Observed latency was 25–30 s or more, with 503 (overload), 429 (quota) and 504 (deadline) failures.
   * No cloud VLM call that takes seconds can produce "a motorcycle is approaching from your right" in time.
   * Real-time awareness has to come from a **local, continuous perception pipeline**. Gemini, or a local VLM, should
     only answer questions and give rich descriptions.
2. **The local pipeline that exists today is limited by its architecture, not just its model:**
   * **Frames:** one 320 px JPEG every 400 ms (measured ≈ 2.5 frames/s).
   * **Detector:** SSDLite320-MobileNetV3, COCO mAP 21.3, 23 COCO classes, running **on the CPU**.
   * **Time handling:** per-frame logic only. There is no tracking with velocity, no motion model, no depth and no
     segmentation of the surface or structures.
   * **Consequences:** it cannot tell "approaching" from "standing", cannot see stairs, doors, kerbs, poles or
     potholes, and cannot judge proximity except through box size.
3. **The laptop has an unused NVIDIA RTX 4050 Laptop GPU with 6 GB VRAM** (verified with `nvidia-smi`). The installed
   frameworks are CPU-only: `torch 2.15.0+cpu`, and ONNX Runtime with only the `CPUExecutionProvider`. Enabling the
   GPU is the cheapest large improvement. It allows a stronger detector, higher resolution and frame rate, plus depth
   and segmentation in the same frame budget.
4. **Recommended direction.** Keep the architecture (phone camera → laptop → spoken output) and add a local
   **perception stack** in three layers:
   * **(1) Detection.** A modern real-time detector on the GPU: RF-DETR or D-FINE (Apache-2.0), or YOLO26 (AGPL-3.0,
     see the licence caution).
   * **(2) Multi-object tracking plus an event layer.** ByteTrack (MIT) feeds rules over track histories: approach
     (box looming, time-to-contact), crossing, entering the path, stationary obstacle, crowd counts.
   * **(3) Scene geometry.** Relative monocular depth (Depth Anything V2 Small, Apache-2.0) and semantic segmentation
     with ADE20K classes (sidewalk, road, floor, stairs, step, door, pole, railing…). Segmentation needs a licence
     decision (section I).

   Gemini stays as the optional cloud layer for questions. A small **local VLM** (for example SmolVLM, Apache-2.0)
   can be added later behind the existing `VisionProvider` interface for offline descriptions.
5. **Little manual work is needed.** Everything above uses ready pretrained weights. Custom training is only justified
   later for **potholes and kerbs**, which no general pretrained model covers reliably. CC BY 4.0 datasets exist on
   Roboflow Universe (section C.15), but their quality is unknown.
6. **No approach here makes the system safe.** Monocular depth is relative, not metres. Detection and segmentation miss
   things. Event rules give false alarms while the user walks. Every phase needs field testing (`docs/MANUAL_TESTING.md`).

---

## B. Diagnosis of the existing NeuroSonic architecture

Inspected in the source code, not assumed.

### B.1 What exists and how it actually works

| Component | Actual implementation (file) | What it can do | What it cannot do |
|---|---|---|---|
| Phone camera input | `web/js/app.js::awarenessStep`: one 320 px-wide JPEG (quality 0.7) every 400 ms (`FRAME_MS = 400`), at most one request in flight, paused when the page is hidden | live frames reach the backend; measured 50 frames in 20 s ≈ **2.5 fps** (`ui_vision_slow_cdp.mjs`) | higher resolution or frame rate (fixed); no on-device inference |
| Object detector | `neurosonic/awareness.py::RGBAwareness`: torchvision SSDLite320-MobileNetV3-Large, COCO weights, **COCO box mAP 21.3**, score ≥ 0.40, 23 obstacle-relevant COCO classes, CPU | people, vehicles, bicycles, animals, benches, chairs… | stairs, steps, kerbs, potholes, doors, poles, walls, surfaces (not COCO classes); small or distant objects at 320 px |
| Walking guidance | `neurosonic/pathguide.py`: lower-central trapezoid, box overlap, side vs centre, 2-of-3 / 3-of-3 confirmation, quality and sharpness checks, five states | conservative per-frame path state with hysteresis | motion, direction of approach, distance, surfaces |
| Temporal logic | `woad/alerts.py::AlertEngine`: greedy per-class IoU matching (`track_iou = 0.30`) used **only** for confirmation and repetition control | stable announcements, no flicker | no persistent IDs across occlusion, no velocity, no trajectories, so no "approaching" or "crossing" |
| WOAD model | `woad/`: two-stream IR + depth transformer fusion (person, Ebike, Car), bit-exact with the original; person AP@0.5 0.218 / 0.173 cross-dataset (`docs/EVALUATION.md`) | works on **recorded** CS30 near-IR + depth | cannot use the phone's RGB camera; the CS30 sensor is not connected |
| Event-camera simulation | `web/js/eventsim.js`: brightness difference between consecutive webcam frames in the browser, thresholded per pixel | a demonstration of where the image changes | **not** an event camera (no microsecond asynchronous events, no high dynamic range), not obstacle detection; camera motion fires everywhere |
| Online scene description | `neurosonic/vision/` (Sprint 1): one still photo per user request goes to Gemini `gemini-3.8-flash`; opt-in; 30 s per attempt, 45 s budget | rich descriptions and answers when the service responds | real-time warnings (latency 25–30 s+; 503 / 429 / 504 observed); offline use |
| Speech output | `web/js/speech.js` priority queue (urgent > system > obstacle > navigation/scene > info), Piper on the laptop | timely, de-duplicated, interruptible warnings | — (well suited to the new event messages) |
| Navigation, voice, history | `maps.py` (A*), `nav.js`, `voicecmd.py` (Vosk), `store.py` | offline routing, GPS handling, voice commands | — (unaffected) |
| Hardware use | `torch 2.15.0+cpu`; `onnxruntime` providers `['AzureExecutionProvider', 'CPUExecutionProvider']`; laptop has an **AMD Ryzen 7 7840HS, 15.3 GB RAM, NVIDIA RTX 4050 Laptop GPU 6 GB, driver 592.82**; F: has 88.8 GB free | everything runs on the CPU | the GPU is unused |

### B.2 Root causes of the limitations

1. **Object-level, frame-level perception only.** Event understanding needs identities over time and their
   motion. The IoU matching exists but is not exposed as tracks with velocities.
2. **The class set is too small for walking.** COCO has no stairs, step, kerb, door, pole, wall, sidewalk or
   pothole classes. No threshold tuning can fix this; it needs segmentation or other models.
3. **No geometry.** There is no depth, so "close" can only be guessed from box size, and surfaces cannot be judged.
4. **Throughput.** At 2.5 fps a motorcycle at about 10 m/s moves 4 m between frames. Approach can be seen, but late
   and noisily. Event rules need ≥ 5 fps, and 8–10 fps is better. The cap is set by the 400 ms client interval,
   one request at a time and CPU inference (52 ms median per frame on the laptop).
5. **The cloud is in the wrong role.** A slow, quota-limited, sometimes unavailable service can be an add-on for
   questions, but never the source of warnings.
6. **The phone round trip** (JPEG upload over Wi-Fi) adds latency that was not measured on the iPhone. Detection
   could later run on the phone itself (C.13, C.14), but that is a later phase.

---

## C. Investigated solutions

The 15 candidates below, plus 4 more listed in C.16, were checked against the official repositories, documentation or
papers.

* **Ready:** a production-grade, maintained tool.
* **Research:** a paper or prototype code.

### C.1 Ultralytics YOLO26 / YOLO11 (detection, segmentation, built-in tracking)
* **What it does:** single-stage real-time detector family. It also does segmentation and pose, and has trackers
  built in (BoT-SORT, ByteTrack). It exports to ONNX, Core ML, TFLite and TensorRT.
* **Benchmarks** (official docs):
  * YOLO26n: 40.9 mAP50-95, **38.9 ± 0.7 ms CPU ONNX**, 1.7 ms T4 TensorRT10, 2.4 M parameters, 5.4 B FLOPs
    ([docs.ultralytics.com/models/yolo26](https://docs.ultralytics.com/models/yolo26/)).
  * YOLO11n: 39.5 mAP, 56.1 ms CPU ONNX ([YOLO11 vs YOLO26](https://docs.ultralytics.com/compare/yolo11-vs-yolo26)).
  * The CPU figures are on an Intel Xeon @ 2.00 GHz, not our CPU.
* **Video:** yes (video and stream inputs; tracking mode). **Pretrained:** COCO (80 classes). **Training:** not
  needed for COCO classes.
* **Runs locally:** yes, on Windows with Python. **iPhone:** yes, via the Core ML export. The documented path is
  `export(format="coreml")` ([Ultralytics Core ML](https://docs.ultralytics.com/integrations/coreml)). A community
  report claims 30+ FPS on the Neural Engine ([dev.to](https://dev.to/john-rocky/real-time-object-detection-on-iphone-with-yolo26-2dgk)) **(unverified)**.
* **Licence: AGPL-3.0**, or a paid Enterprise licence ([HF model card](https://huggingface.co/Ultralytics/YOLO11)).
  NeuroSonic serves the model to phones over a network, and the AGPL network clause would then require releasing
  NeuroSonic's source under the AGPL.
* **Limitations:** COCO classes only, the same gaps as now; the AGPL obligations.
* **Status:** Ready. Links: [github.com/ultralytics/ultralytics](https://github.com/ultralytics/ultralytics).

### C.2 RF-DETR (Roboflow)
* **What it does:** real-time detection transformer, with detection and segmentation variants.
* **Benchmarks** (official README and docs, T4 TensorRT FP16, NMS included): RF-DETR-N 48.4 AP at 2.32 ms, S 53.0 at
  3.52 ms, M 54.7 at 4.52 ms ([rfdetr.roboflow.com](https://rfdetr.roboflow.com/), [PyPI rfdetr](https://pypi.org/project/rfdetr/)).
  No CPU figures were found.
* **Pretrained:** COCO. **Training:** optional fine-tuning.
* **Runs locally:** yes, as a Python package (`pip install rfdetr`), with ONNX export. **iPhone:** via ONNX or Core ML
  conversion **(unverified)**.
* **Licence:** **Apache-2.0** for the code and the Nano to Large models. XL and 2XL use PML 1.0.
* **Limitations:** a transformer, so it is probably heavy on CPU **(unverified)**. It benefits from the GPU.
* **Status:** Ready. Links: [blog.roboflow.com/rf-detr-nano-small-medium](https://blog.roboflow.com/rf-detr-nano-small-medium/amp).

### C.3 D-FINE and DEIM (real-time DETR, CVPR 2025)
* **What it does:** real-time detection transformers.
* **Benchmarks** (paper, T4, TensorRT, batch 1): DEIM-D-FINE-L 54.7 AP at 124 FPS; X 56.5 AP at 78 FPS
  ([arXiv 2412.04234](https://arxiv.org/abs/2412.04234)). A repository mirror lists D-FINE-N at 2.12 ms
  ([ecosyste.ms mirror](https://science.ecosyste.ms/projects/96808)).
* **Licence:** **Apache-2.0** for the code and weights ([Roboflow D-FINE](https://playground.roboflow.com/models/ustc/d-fine)).
* **Limitations:** research code; less tooling than Ultralytics or RF-DETR.
* **Status:** Research with good code. Links: [github.com/Peterande/D-FINE](https://github.com/Peterande/D-FINE) (not
  opened directly; reached through mirrors), [DEIM project](https://www.shihuahuang.cn/DEIM/).

### C.4 RT-DETR / RT-DETRv2 (Baidu)
* **What it does:** the first real-time DETR.
* **Benchmarks** (official repository, T4 TensorRT FP16): RT-DETR-R18 217 FPS; RT-DETRv2-M 51.9 AP at 145 FPS;
  v2-L 53.4 AP at 108 FPS. RT-DETRv4 was announced on 2025-11-18 ([github.com/lyuwenyu/RT-DETR](https://github.com/lyuwenyu/RT-DETR)).
* **Licence:** Apache-2.0. It is also in Hugging Face `transformers`.
* **Status:** Research/Ready. It has been superseded in accuracy per latency by D-FINE and RF-DETR, according to their
  papers.

### C.5 YOLO-World (open-vocabulary detection)
* **What it does:** detects classes named in a text prompt ("door", "stairs", "pole") without training. It is a CNN
  and reported to be ≈ 20× faster than Grounding DINO ([Roboflow blog](https://blog.roboflow.com/what-is-yolo-world/),
  [arXiv 2401.17270](https://arxiv.org/abs/2401.17270)).
* **Licence:** **GPL-3.0** ([Roboflow listing](https://playground.roboflow.com/models/tencent%20ai%20lab/yolo-world)).
* **Limitations:** accuracy on rare classes (stairs, potholes) is not established. Open-vocabulary detectors produce
  confident false positives. No exact latency was found **(unverified)**.
* **Status:** Research. Links: [github.com/AILab-CVC/YOLO-World](https://github.com/AILab-CVC/YOLO-World).

### C.6 Grounding DINO (open-set detection from text)
* **What it does:** detects anything described in text. It is strong but heavy.
* **Benchmarks:** Grounding DINO 1.5 Edge reaches 75.2 FPS with TensorRT on an A100, and > 10 FPS on a Jetson Orin
  NX at 640 px ([arXiv 2405.10300](https://arxiv.org/abs/2405.10300)).
* **Availability:** the 1.5 models are offered through an API with tokens
  ([grounding-dino-1.5-api](https://github.com/idea-research/grounding-dino-1.5-api)). Local Edge weights were not
  confirmed **(unverified)**.
* **Fit:** not real time on our hardware. It is useful **offline for automatic labelling** if custom training ever
  becomes necessary.
* **Status:** Research / API.

### C.7 Semantic segmentation with ADE20K classes (SegFormer, OneFormer, Mask2Former)
* **What it does:** labels every pixel.
* **Class coverage.** ADE20K has 150 classes. The SegFormer ADE20K checkpoint's `config.json` was checked: wall 0,
  floor 3, road 6, grass 9, **sidewalk 11**, person 12, **door 14**, car 20, water 21, **fence 32**, **railing 38**,
  column 42, **path 52**, **stairs 53**, **stairway 59**, bus 80, truck 83, **pole 93**, bannister 95, escalator 96,
  **step 121**, bicycle 127 ([nvidia/segformer-b0-finetuned-ade-512-512](https://huggingface.co/nvidia/segformer-b0-finetuned-ade-512-512)).
  There is **no "curb" class.**
* **Why it matters:** this is the cheapest route to **doors, stairs, steps, poles, railings and the walking surface
  (sidewalk / road / floor / path) without custom training**.
* **Licences, the key constraint:**
  * **SegFormer** code and NVIDIA checkpoints use the NVIDIA Source Code Licence, **non-commercial, research or
    evaluation only** ([github.com/NVlabs/SegFormer](https://github.com/NVlabs/SegFormer)).
  * **OneFormer** code is MIT ([github.com/SHI-Labs/OneFormer](https://github.com/SHI-Labs/OneFormer)), but NVIDIA's
    hosted checkpoint is marked non-commercial ([NGC](https://catalog.ngc.nvidia.com/orgs/nvidia/tao/models/oneformer/oneformer_coco_pretrained_research)).
  * **Mask2Former:** sources conflict, MIT versus CC BY-NC 4.0 ([mirror](https://gitee.com/cw_zhou/Mask2Former),
    [fork](https://github.com/jmfortin/Mask2Former)).
  * **The ADE20K images themselves** are for non-profit research and education; commercial use needs MIT CSAIL's
    permission ([ade20k.csail.mit.edu/terms](https://ade20k.csail.mit.edu/terms)).
  * **Conclusion:** fine for this research prototype. A commercial product would need legal review or a different
    training set.
* **Speed:** small SegFormer variants (B0) are light, but no verified latency was found for our hardware
  **(unverified)**.
* **Limitations:** ADE20K is mostly scene photos, not chest-height walking views. Stairs and step quality on real
  pavements is unmeasured. There is no kerb class.
* **Status:** Ready to research.

### C.8 Segment Anything: MobileSAM and SAM 2
* **What it does:** class-agnostic masks from prompts.
* **Speed:**
  * MobileSAM: image encoder ≈ 8 ms on a GPU, ≈ 3 s on a Mac i5 CPU (official README).
  * SAM 2: Apache-2.0, video segmentation with memory ([HF card](https://huggingface.co/facebook/sam2.1-hiera-large)).
* **MobileSAM licence:** conflicting sources, Apache-2.0 per a fork versus CC BY-NC-SA per the paper page
  ([MobileSAM](https://github.com/ChaoningZhang/MobileSAM)) **(unverified)**.
* **Fit:** low for warnings. The masks have no class ("what"), so they would need a detector or VLM on top.
  Possible later use: cleaner obstacle outlines or surface masks.
* **Status:** Ready (SAM 2) / Research.

### C.9 Monocular depth: Depth Anything V2, ZoeDepth
* **What it does:** a depth map from one RGB image.
  * Depth Anything V2: Small model has **24.8 M parameters**. The relative-depth models are the standard ones; metric
    models fine-tuned from Small and Base were released 2024-06-22
    ([github.com/DepthAnything/Depth-Anything-V2](https://github.com/DepthAnything/Depth-Anything-V2)).
  * ZoeDepth combines relative and metric depth ([github.com/isl-org/ZoeDepth](https://github.com/isl-org/ZoeDepth)).
* **Licences:**
  * DA-V2 **Small: Apache-2.0**; Base, Large and Giant: **CC-BY-NC-4.0**.
  * The licence of the metric checkpoints was not found **(unverified)**.
  * ZoeDepth: MIT.
* **Speed on our hardware:** not found **(unverified)**; the model must be benchmarked.
* **Fit:**
  * proximity ordering ("closer than");
  * obstacle and drop cues inside the path region (a depth discontinuity, possibly a step);
  * separating looming from lateral motion.
* **Limitations:** relative depth is not metres. Metric monocular depth has a scale error that varies by scene. Glass,
  reflections, darkness and sky fail.
* **Status:** Ready (Small, Apache).

### C.10 Multi-object tracking: ByteTrack, BoT-SORT, Roboflow `supervision` / `trackers`
* **What it does:** stable IDs over time from per-frame detections. That gives trajectories, velocities and box-size
  change.
* **Projects:**
  * ByteTrack: MIT ([github.com/ifzhang/ByteTrack](https://github.com/ifzhang/ByteTrack)).
  * BoT-SORT: MIT, adds camera-motion compensation ([github.com/NirAharon/BoT-SORT](https://github.com/NirAharon/BoT-SORT),
    [arXiv 2206.14651](https://arxiv.org/abs/2206.14651)).
  * `supervision` is MIT. Its `sv.ByteTrack` is deprecated in favour of the separate `trackers` package
    ([supervision FAQ](https://supervision.roboflow.com/latest/faq/)).
* **Cost:** ByteTrack association runs on the CPU and is light (Kalman filter plus IoU). It needs no weights.
* **Fit:** essential. It is the basis of every event in section F. BoT-SORT's **camera-motion compensation** matters
  because the camera moves with the walker.
* **Status:** Ready.

### C.11 Optical flow: OpenCV DIS / Farneback
* **What it does:** dense motion between frames. OpenCV's DIS optical flow (`DISOpticalFlow`, preset FAST) and
  Farneback are both in OpenCV ([OpenCV optflow docs](https://docs.opencv.org/3.4/de/d67/optflow_8hpp.html)).
  OpenCV is already installed.
* **Fit:**
  * estimating the walker's own motion (ego-motion, focus of expansion), so that "the world grows because I walk"
    can be separated from "an object approaches";
  * motion of objects the detector does not know.
* **Speed:** no published CPU benchmark was found **(unverified)**; measure at 320 px.
* **Status:** Ready.

### C.12 Time-to-contact (TTC) from looming (method, not a library)
* **What it does:** TTC ≈ box height h / (dh/dt). It needs no depth and no camera calibration. The approach is widely
  taught, for example in a [sensor-fusion course on camera TTC](https://sensor5.github.io/Sensor%20Fusion%20v5.0.0/Part%2003-Module%2001-Lesson%2003_Engineering%20a%20Collision%20Detection%20System/03.%20Estimating%20TTC%20with%20a%20Camera.html).
* **Datasets:** TSTTC is a monocular TTC dataset ([arXiv 2309.01539](https://arxiv.org/abs/2309.01539)).
* **Accuracy:** both sources warn that **detector boxes are noisy**, so smoothing over several frames and tracking are
  required. Optical-flow-based TTC is surveyed in [Sensors 2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6412735/).
* **Fit:** the core signal for "approaching" and "dangerous proximity" messages, combined with tracking.
* **Status:** Ready method (needs tuning and validation).

### C.13 MediaPipe Tasks (Google): on-device detection in the browser and on mobile
* **What it does:** a ready Object Detector. The default model is EfficientDet-Lite0 (320 × 320, COCO).
* **Benchmarks:** EfficientDet-Lite0 fp32 takes 61.30 ms on CPU and 27.83 ms on GPU, **on a Pixel 6**
  ([MediaPipe Object Detector](https://ai.google.dev/mediapipe/solutions/vision/object_detector)).
* **Platforms:** web, Android and iOS. Chrome and Safari are listed for web
  ([setup_web](https://ai.google.dev/mediapipe/solutions/setup_web)). GPU delegate support for object detection in iOS
  Safari is not confirmed **(unverified)**.
* **Licence:** Apache-2.0.
* **Fit:** a fallback detector **on the phone**, so the phone keeps basic detection if the laptop or Wi-Fi drops.
  Accuracy is similar to the current SSDLite, so it is not an upgrade.
* **Status:** Ready.

### C.14 Apple on-device stack: Core ML, Vision and ARKit LiDAR depth (native iOS app)
* **What it does:**
  * Core ML runs detectors on the Neural Engine. YOLO exports to Core ML (C.1).
  * ARKit provides **metric LiDAR depth per frame** (`ARFrame.sceneDepth` / `smoothedSceneDepth`) on LiDAR iPhones,
    which includes the iPhone 17 Pro Max ([Unity ARKit occlusion docs](https://docs.unity3d.com/Packages/com.unity.xr.arkit@6.1/manual/arkit-occlusion.html)).
* **Web limits:**
  * **Safari cannot access this.** WebXR depth sensing is "not supported" in iOS Safari up to 26.5
    ([caniuse](https://caniuse.com/wf-webxr-depth-sensing), [WebKit bug 208988](https://webkit.org/b/208988)).
  * WebGPU is on by default in iOS 26 Safari, but onnxruntime-web lists only wasm and webgl backends for iOS
    ([onnxruntime-web on npm](https://www.npmjs.com/package/onnxruntime-web)).
* **Fit:** the strongest long-term route. It gives **real metric distance**, no Wi-Fi latency, and offline operation.
  It is a separate native app, though, which the current instructions exclude. Treat it as a later phase that reuses
  the backend design.
* **Status:** Ready (Apple frameworks); the app would be new work.

### C.15 Pretrained or ready data for potholes, stairs and kerbs
* **What exists:** Roboflow Universe has CC BY 4.0 datasets: "Pothole&Stair_Detection" (classes pothole, downstairs,
  upstairs) and several pothole sets ([pothole-stair_detection](https://universe.roboflow.com/devansh2205/pothole-stair_detection),
  [pothole-detection-nbpd2](https://universe.roboflow.com/academic-jugbj/pothole-detection-nbpd2)), plus a 665-image
  pothole set mirrored on Hugging Face ([manot/pothole-segmentation2](https://huggingface.co/datasets/manot/pothole-segmentation2)).
* **Quality:** these are hobby or academic datasets of unknown quality. Downloadable trained weights under a clear
  licence were not confirmed.
* **Fit:** the only reasonable source for **potholes** and **kerbs** without manual labelling. It means fine-tuning a
  small detector, the one place where training is justified.
* **Status:** data available; model quality unknown.

### C.16 Also investigated

| Candidate | Finding |
|---|---|
| **Local VLMs (SmolVLM, Moondream 2, Florence-2)** | SmolVLM2 is Apache-2.0 ([Roboflow listing](https://playground.roboflow.com/models/hugging-face/smolvlm2)). For SmolVLM-256M, CPU preprocessing dominates latency, and optimising it cut time-to-first-token by 93 % ([arXiv 2603.16987](https://arxiv.org/abs/2603.16987)). Moondream 2 is about 1.86 B parameters and ≈ 2 GB; its licence is reported as Apache-2.0 but sources conflict ([moondream.ai](https://moondream.ai/models)). No verified CPU/GPU timings for our hardware. They suit **offline "describe the environment"**, not warnings. They fit the existing `VisionProvider` interface |
| **Streaming video LLMs** | StreamingVLM runs at up to 8 FPS on **one H100** ([project](https://hanlab.mit.edu/projects/streamingvlm), [arXiv 2510.09608](https://arxiv.org/abs/2510.09608)). VideoLLM-online (CVPR 2024) runs > 10 FPS with a 7 B model on an **A100** ([arXiv 2406.11816](https://arxiv.org/abs/2406.11816)). Research only; data-centre GPUs; **not practical** on a 6 GB laptop GPU |
| **NVIDIA DeepStream** | Runs on Windows 11 only inside WSL2 and Docker, with GeForce/Quadro GPUs in WDDM mode ([DeepStream on WSL](https://docs.nvidia.com/metropolis/deepstream/9.1/text/DS_on_WSL2.html)). Built for multi-camera video analytics. **Overkill**, Linux-centred, and no help on the iPhone |
| **Event cameras (Prophesee OpenEB)** | OpenEB is Apache-2.0 ([openeb docs](https://docs.ros.org/en/iron/p/openeb_vendor/standard_docs/README.html)), but **needs event-camera hardware**. Phones have none. The browser frame-difference demo is not an event camera (B.1). Not applicable without new hardware |
| **ONNX Runtime GPU / DirectML** | `onnxruntime-gpu` defaults to CUDA 12.x since 1.19 ([install docs](https://onnxruntime.ai/docs/install/)). DirectML works with any DirectX 12 GPU but is in "sustained engineering" ([DirectML EP](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)). Either can move ONNX models to the RTX 4050 |
| **OpenVINO** | Intel's runtime, optimised for Intel hardware. Our CPU is AMD Ryzen, so no benefit could be verified. **Low priority** |

---

## D. Comparison table

* **Integration effort** is relative to the existing backend: **L** = days, **M** = 1–2 weeks, **H** = several weeks
  or a new app.
* **Speed** figures are the published ones (hardware in brackets); "n/v" = no verified figure.

| # | Solution | Function | Live video | Pretrained / training | Local, Windows, Python | iPhone | Speed (published) | Licence | Effort |
|---|---|---|---|---|---|---|---|---|---|
| 1 | YOLO26 / YOLO11 | detection, segmentation, tracking | yes | COCO / none | yes | Core ML export | YOLO26n 38.9 ms (Xeon CPU ONNX), 1.7 ms (T4 TRT) | **AGPL-3.0** / paid | L |
| 2 | RF-DETR N/S/M | detection (+ segmentation) | yes | COCO / none | yes | via export (n/v) | N 2.32 ms, S 3.52 ms (T4 TRT FP16) | Apache-2.0 | L–M |
| 3 | D-FINE / DEIM | detection | yes | COCO / none | yes | via ONNX (n/v) | D-FINE-N 2.12 ms; L 124 FPS (T4) | Apache-2.0 | M |
| 4 | RT-DETR(v2) | detection | yes | COCO / none | yes (transformers) | n/v | R18 217 FPS (T4) | Apache-2.0 | M |
| 5 | YOLO-World | open-vocabulary detection | yes | open vocabulary / none | yes | n/v | n/v (≈ 20× faster than Grounding DINO) | GPL-3.0 | M |
| 6 | Grounding DINO | open-set detection | not real time here | open vocabulary | yes (1.0) / API (1.5) | no | 1.5 Edge 75 FPS (A100 TRT) | Apache-2.0 (code) | M (offline labelling) |
| 7 | ADE20K segmentation (SegFormer / OneFormer / Mask2Former) | surface and structure classes | yes (per frame) | ADE20K / none | yes | via conversion (n/v) | n/v | NVIDIA NC / MIT code / unclear; ADE20K images non-commercial | M |
| 8 | MobileSAM / SAM 2 | class-agnostic masks | SAM 2 video | yes / none | yes | n/v | MobileSAM ≈ 8 ms encoder (GPU), ≈ 3 s (i5 CPU) | Apache-2.0 (SAM 2); MobileSAM unclear | M |
| 9 | Depth Anything V2 Small / ZoeDepth | relative / metric depth | yes (per frame) | yes / none | yes | via conversion (n/v) | n/v | Apache-2.0 (Small) / MIT | L–M |
| 10 | ByteTrack / BoT-SORT / `trackers` | tracking with IDs | yes | none needed | yes (CPU) | portable logic | light (Kalman + IoU) | MIT | L |
| 11 | OpenCV DIS / Farneback flow | dense motion, ego-motion | yes | none | yes (installed) | portable | n/v | Apache-2.0 (OpenCV) | L |
| 12 | Looming TTC (h / ḣ) | approach and collision timing | yes | none | yes | portable | negligible | method | L |
| 13 | MediaPipe Object Detector | on-phone detection | yes | COCO / none | web / iOS | yes (web, native) | Lite0 61 ms CPU, 28 ms GPU (Pixel 6) | Apache-2.0 | M |
| 14 | Core ML + Vision + ARKit LiDAR | on-device detection + metric depth | yes | yes | no (Xcode) | **native only** | community: 30+ FPS YOLO (n/v) | Apple SDK | **H (new app)** |
| 15 | Pothole / stairs datasets (Roboflow Universe) | data for fine-tuning | — | data only / **training needed** | yes | — | — | CC BY 4.0 (dataset-specific) | M |
| 16 | Local VLM (SmolVLM / Moondream) | descriptions, questions | not real time | yes / none | yes (GPU better) | possible | n/v | Apache-2.0 (SmolVLM); Moondream conflicting | M |
| 17 | Streaming video LLMs | continuous video reasoning | yes, on H100/A100 | yes | no (hardware) | no | 8 FPS (H100) | varies | H |
| 18 | DeepStream | video analytics pipelines | yes | yes | WSL2 + Docker only | no | n/v | NVIDIA | H |
| 19 | Event camera (OpenEB) | true event sensing | yes (hardware) | — | needs a sensor | no | — | Apache-2.0 | H (hardware) |

**Cost:** all items except the Gemini API are free to run locally. Their costs are disk, GPU time and licence
obligations.

---

## E. The five strongest approaches for NeuroSonic

### E1. GPU-accelerated modern detector at higher resolution and frame rate (foundation)
* **Why:**
  * The RTX 4050 is idle.
  * Published latencies of RF-DETR-N/S, D-FINE-N and YOLO26n are 2–4 ms on a T4 (C.1–C.3), against SSDLite's
    38–77 ms on our CPU.
  * Their COCO accuracy (40.9–53 AP) is about 2–2.5× SSDLite's 21.3 mAP.
* **What it enables:** 640 px input (smaller and more distant objects) and 8–10 fps, leaving GPU time for depth and
  segmentation.
* **Choice:**
  * **RF-DETR (Apache-2.0)** as the default, for licence freedom.
  * YOLO26 only if the AGPL obligations are acceptable; it has the best tooling (built-in tracking, Core ML export).
* **Evidence:** C.1–C.3, B.1 hardware.
* **Risk:** GPU throughput on the RTX 4050 has not been measured. It must be benchmarked before committing.

### E2. Multi-object tracking + rule-based event layer (the core of "event understanding")
* **Why:** every target event ("approaching", "crossing", "entering the path", "stationary obstacle", "several people
  and vehicles") is a statement about **tracks over time**, not about single frames.
* **Tools:** ByteTrack or BoT-SORT (MIT) are ready, need no weights, and run on the CPU. BoT-SORT adds
  camera-motion compensation, which matters because the camera moves with the walker.
* **Evidence:** C.10–C.12. Details in section F.

### E3. Relative monocular depth (Depth Anything V2 Small)
* **Why:**
  * It gives proximity ordering ("closest object ahead").
  * It confirms looming.
  * It shows depth discontinuities in the walking path (possible step or drop) for objects the detector does not
    know.
* **Licence and training:** Apache-2.0 (Small); no training.
* **Wording:** relative, never "metres" (C.9).

### E4. Walking-surface and structure segmentation (ADE20K classes)
* **Why:** it is the only no-training route to **sidewalk / road / floor / path, stairs / stairway / step, door,
  pole, railing, fence** (verified class list, C.7).
* **Combined with depth**, it gives "the walking surface changes from sidewalk to road", "a staircase is visible
  ahead", "a pole is in the path".
* **Caveats:**
  * Licence (non-commercial checkpoints or images) for anything beyond this research prototype.
  * No kerb class; potholes are not covered (E5).

### E5. Two description layers: local VLM (offline) + Gemini (online), fed with structured perception
* **Why:**
  * Natural-language answers ("describe the environment around me") do not need real-time speed, but must not need
    the internet.
  * A small local VLM (SmolVLM, Apache-2.0) can be a second `VisionProvider` (the interface already exists).
  * Gemini stays as an optional, higher-quality provider.
* **Grounding:** both can be given the **current structured scene** as text (tracks, positions, path state, surface
  classes), which grounds their answers in what the local layers measured.
* **Evidence:** C.16 and the existing `neurosonic/vision/` design.
* **Not recommended as a warning source:** VLM latency is seconds; streaming video LLMs need data-centre GPUs.

*Potholes and kerbs* need E1 plus fine-tuning on C.15 data. This is the only justified training, and it comes after
E1–E4 are working.

---

## F. Event understanding: how the target events can be computed

All events are derived per **track** (from E2), using:

* its box history (centre, width, height);
* its class;
* the path-region overlap (existing `pathguide.py` geometry);
* relative depth (E3), when available;
* background optical flow (C.11) to compensate for the walker's own motion.

Approximate rules, all smoothed over a short window of 0.5–1.5 s at ≥ 5 fps. Every threshold needs tuning and field
validation.

| Event | Signals | Rule (sketch) | Spoken message (examples, wording per existing rules) |
|---|---|---|---|
| Object approaching | box height h rising; **TTC = h / (dh/dt)** smoothed; growth beyond the ego-motion-expected background expansion; depth decreasing (E3) | TTC below a threshold (e.g. a few seconds) on ≥ 3 frames, and growth larger than static background at a similar image position | "A motorcycle is approaching from your right." / "A person is walking towards you." |
| Direction of approach | track centre's horizontal position and velocity; entry side of the image | side = position when the approach is confirmed; "from your right" only in chest mode (handheld uses camera wording, as today) | "…from your right" / "…in the centre of the camera view" |
| Person crossing in front | large lateral velocity of the centre through the central third / path region, while the box size is roughly stable | crosses the path region with lateral speed > k × box width per second | "A person is crossing in front of you." |
| Object entering the walking path | path-region overlap fraction (existing `box_path_overlap`) rising from about 0 to the "possible obstacle" level | rising-edge detection on the overlap fraction | "A bicycle is moving into your path." |
| Stationary obstacle | the track barely moves relative to the background flow, but grows as the user walks (TTC consistent with walking speed) | in the path, low motion relative to background, approaching only through ego-motion | "There is a potential obstacle directly ahead." |
| Dangerous proximity / potential collision | TTC very low, or large box in the lower centre (existing BLOCKED_VIEW), or very near relative depth | any of these, confirmed over ≥ 2 frames | "Stop. The walking path may be blocked." (existing urgent wording) |
| Crowds and traffic | counts of confirmed tracks per class | e.g. ≥ 3 people or ≥ 2 vehicles for several seconds | "There are several people and vehicles around you." |
| Change in walking environment | segmentation class in the path region (E4): sidewalk → road, floor → stairs or step; depth discontinuity in the path | class majority change persisting ≥ 1 s; discontinuity on consecutive frames | "The walking surface changes to road." / "A staircase is visible ahead." / "The walking surface appears uneven." |

**Why these components:**

* **Detection** says *what*.
* **Tracking** says *which one, over time*.
* **TTC / looming** says *approaching and how soon* (no metres needed).
* **Optical flow** separates the user's own motion from object motion.
* **Depth** adds *nearer or farther* and surface geometry.
* **Segmentation** adds *where one can walk* and structures COCO does not have.
* **Temporal reasoning** at this level is deterministic rules with hysteresis, like `pathguide.py`. That is
  explainable and testable. A learned temporal model (or a streaming video LLM) would need training data or
  data-centre GPUs (C.16).

---

## G. Existing modules: preserve, improve, replace, supplement

| Module | Decision | Reason |
|---|---|---|
| `woad/` (WOAD model, alert engine, quality gate) | **Preserve** | research asset, verified bit-exact; `AlertEngine` wording, cooldowns and merging stay useful |
| `neurosonic/pathguide.py` | **Preserve and improve** | its states and announcement policy remain the safety core; add inputs (tracks, TTC, depth, surface) |
| `neurosonic/awareness.py` | **Improve** | put the detector behind an interface; device selection (CPU/GPU); SSDLite becomes the CPU fallback |
| SSDLite320 detector | **Replace as default, keep as fallback** | weak accuracy (21.3 mAP); keep it for machines without a GPU |
| `web/js/app.js` capture loop | **Improve** | adaptive resolution (320 → 640 px) and frame rate (2.5 → 5–10 fps) when the backend is fast enough |
| `web/js/speech.js`, Piper (`tts.py`) | **Preserve** | priorities and interruption fit event warnings; add event message categories |
| `neurosonic/vision/` (SceneAssistant, Gemini) | **Preserve and supplement** | keep for online questions; add a local VLM provider; pass structured scene text |
| `web/js/eventsim.js` | **Preserve as a labelled demo** | not perception; never feed it into warnings |
| maps, nav, GPS, voice commands, history | **Preserve** | unaffected |
| New: `perception/` tracker + events module | **Supplement** | ByteTrack/BoT-SORT + TTC + rules (section F) |
| New: depth and segmentation stages | **Supplement** | E3, E4 (optional, GPU) |

---

## H. Installation size, hardware and effort (estimates)

| Item | Size / requirement | Status |
|---|---|---|
| CUDA-enabled PyTorch for Windows | several GB (bundles CUDA libraries) | **(estimate)**; no verified figure; check `pip download` before installing |
| `onnxruntime-gpu` (alternative runtime) | ≈ 438 MB package, ≈ 2 GB with CUDA libraries (one third-party measurement) | **(unverified)** |
| Detector weights (YOLO26n 2.4 M parameters; RF-DETR-N/S) | tens of MB | **(estimate)** from parameter counts |
| Depth Anything V2 Small (24.8 M parameters) | ≈ 100 MB at fp32 | **(estimate)** from parameter count |
| ADE20K segmentation (small variant) | tens of MB | **(estimate)** |
| Local VLM (SmolVLM-256M … Moondream 2 ≈ 2 GB on disk) | 0.5–2 GB | partly sourced (C.16) |
| Free disk on F: | 88.8 GB | verified |
| GPU | RTX 4050 Laptop, 6 GB VRAM. Expected to fit a detector + depth + small segmentation at 640 px at the same time **(estimate, must be measured)**; a VLM would compete for VRAM | verified hardware |
| RAM | 15.3 GB system | verified |

**Effort** (development estimates for one developer familiar with the code, excluding field testing):

| Phase | Estimate |
|---|---|
| Phase 1 (GPU + detector + benchmark) | ≈ 3–5 days |
| Phase 2 (tracking + events) | ≈ 1–2 weeks |
| Phase 3 (depth + surface) | ≈ 1–2 weeks |
| Phase 4 (local VLM) | ≈ 1 week |
| Phase 6 (native iOS) | several weeks |

These are estimates, not commitments.

---

## I. Risks, limitations and safety

1. **Safety claims.** None of these approaches proves that a path is safe. The current honest wording rules stay
   ("appears", "possible", no distances, "please check").
2. **Ego-motion false alarms.** When the user walks, static objects "approach". Without flow or ground-plane
   compensation, approach alerts will be wrong. This is the main technical risk of E2.
3. **Monocular depth** is relative, and fails on glass, reflections, darkness and texture-less scenes. Never speak
   metres from it.
4. **Licences:**
   * **AGPL-3.0** (Ultralytics) imposes source-release obligations on a network service.
   * **GPL-3.0** (YOLO-World).
   * **Non-commercial** SegFormer / OneFormer checkpoints and ADE20K images.
   * **CC-BY-NC** Depth Anything V2 Base and larger.
   * The Apache-2.0 options (RF-DETR, D-FINE, RT-DETR, DA-V2 Small, SAM 2, MediaPipe) are the safest.
5. **Domain gap.** COCO and ADE20K images are not chest-height pavement views in Vellore. Measured accuracy will be
   lower. Field data is needed even if no training is done.
6. **Latency and throughput.** The Wi-Fi round trip and JPEG encoding on the phone are unmeasured. At ≥ 5 fps the
   phone's battery and heat must be checked. iOS Safari stops the camera when the screen locks.
7. **Unmeasured GPU throughput.** Every speed figure in this report is published, on other hardware. Phase 1 must
   measure on the RTX 4050 before design decisions are fixed.
8. **The cloud.** Gemini latency (25–30 s+), 503, 429 and 504 errors, quota and privacy. It is acceptable only as an
   opt-in description layer.
9. **Overload of speech.** More event types can easily become noise. The existing priority, cooldown and "speak only
   on change" policy must also govern events.

---

## J. Phased roadmap

| Phase | Goal | Work | Exit criterion |
|---|---|---|---|
| **0 (done)** | baseline | walking guidance, speech, navigation, cloud description, timeout fix | 182 tests + 6 browser tests pass |
| **1** | use the GPU; stronger detector | install a CUDA build of PyTorch, or `onnxruntime-gpu` (size check first, with approval); detector interface in `awareness.py`; RF-DETR-N/S (or YOLO26n) vs SSDLite benchmark on recorded and phone frames; adaptive 320/640 px and fps in `app.js` | measured fps ≥ 8 at 640 px end-to-end on the laptop; no regression in existing tests |
| **2** | event understanding | tracker (ByteTrack / BoT-SORT); per-track velocity and TTC; background flow for ego-motion; event rules (section F) into `pathguide` / speech with priorities and cooldowns; recorded-video tests with expected events | events detected on test clips with documented precision and false-alarm rate; walking-guidance tests still pass |
| **3** | geometry and surface | Depth Anything V2 Small; ADE20K segmentation (licence decision); path-region surface classes, stairs, step, door, pole messages | spoken surface and stairs messages on test clips; throughput still ≥ 5 fps |
| **4** | offline descriptions | local VLM provider (SmolVLM or similar) behind `VisionProvider`; structured scene text into prompts; Gemini optional | "describe the environment" works without internet, with measured latency |
| **5** | potholes and kerbs (only if needed) | fine-tune a small detector on CC BY 4.0 data (C.15); evaluate on Vellore pavement photos | documented accuracy; clear limits in How It Works |
| **6** | on-phone perception (later, separate decision) | native iOS app: Core ML detector + ARKit LiDAR metric depth, reusing the backend's event logic | not in the current scope |

**Every phase:**

* back up first;
* mocked and recorded-data tests;
* browser tests;
* `docs/MANUAL_TESTING.md` field tests with a sighted companion;
* no feature represented as a safety guarantee.

---

## K. Final recommendation

* **Main direction.** Do not depend on Gemini for awareness. Build the real-time capability as a **local perception
  stack on the laptop's idle RTX 4050**:
  * a modern Apache-licensed real-time detector (RF-DETR) at 640 px and 5–10 fps;
  * **ByteTrack/BoT-SORT tracking with looming-based time-to-contact and optical-flow ego-motion compensation**, which
    is what turns detections into events ("approaching from your right", "crossing in front", "entering your path");
  * **Depth Anything V2 Small** for proximity ordering;
  * **ADE20K-class segmentation** for sidewalk, road, stairs, steps, doors and poles.

  All of it uses ready pretrained weights, with no training and no API. All of it feeds the existing `pathguide.py`
  states, speech priorities and Piper voice.
* **Cloud role.** Keep Gemini as an optional online layer for questions, and add a local VLM for offline descriptions
  through the existing `VisionProvider` interface.
* **Training** is only justified later, for potholes and kerbs.
* **Long term,** the strongest architecture is on-device perception in a native iOS app with **ARKit LiDAR metric
  depth**. That is a separate project decision.
* **First concrete step (needs approval).** Phase 1: check the CUDA PyTorch download size, enable the GPU, and
  benchmark RF-DETR-N/S and YOLO26n against SSDLite on recorded and phone frames. These measurements decide the
  rest of the design.

---

## Sources

**Detection and open vocabulary**

* Ultralytics YOLO26: https://docs.ultralytics.com/models/yolo26/
* Ultralytics YOLO11 vs YOLO26: https://docs.ultralytics.com/compare/yolo11-vs-yolo26
* Ultralytics Core ML export: https://docs.ultralytics.com/integrations/coreml
* YOLO11 model card (licence): https://huggingface.co/Ultralytics/YOLO11
* Real-time YOLO26 on iPhone (community report): https://dev.to/john-rocky/real-time-object-detection-on-iphone-with-yolo26-2dgk
* RF-DETR documentation: https://rfdetr.roboflow.com/
* RF-DETR on PyPI: https://pypi.org/project/rfdetr/
* RF-DETR Nano/Small/Medium announcement: https://blog.roboflow.com/rf-detr-nano-small-medium/amp
* DEIM paper: https://arxiv.org/abs/2412.04234
* DEIM project page: https://www.shihuahuang.cn/DEIM/
* D-FINE on Roboflow: https://playground.roboflow.com/models/ustc/d-fine
* D-FINE repository mirror: https://science.ecosyste.ms/projects/96808
* RT-DETR repository: https://github.com/lyuwenyu/RT-DETR
* YOLO-World paper: https://arxiv.org/abs/2401.17270
* YOLO-World overview: https://blog.roboflow.com/what-is-yolo-world/
* YOLO-World licence listing: https://playground.roboflow.com/models/tencent%20ai%20lab/yolo-world
* Grounding DINO 1.5 paper: https://arxiv.org/abs/2405.10300
* Grounding DINO 1.5 API: https://github.com/idea-research/grounding-dino-1.5-api

**Segmentation and depth**

* SegFormer (licence): https://github.com/NVlabs/SegFormer
* SegFormer ADE20K class list: https://huggingface.co/nvidia/segformer-b0-finetuned-ade-512-512
* OneFormer: https://github.com/SHI-Labs/OneFormer
* OneFormer NVIDIA checkpoint: https://catalog.ngc.nvidia.com/orgs/nvidia/tao/models/oneformer/oneformer_coco_pretrained_research
* ADE20K terms of use: https://ade20k.csail.mit.edu/terms
* MobileSAM: https://github.com/ChaoningZhang/MobileSAM
* SAM 2.1 model card: https://huggingface.co/facebook/sam2.1-hiera-large
* Depth Anything V2: https://github.com/DepthAnything/Depth-Anything-V2
* ZoeDepth: https://github.com/isl-org/ZoeDepth

**Tracking, motion and time-to-contact**

* ByteTrack: https://github.com/ifzhang/ByteTrack
* BoT-SORT: https://github.com/NirAharon/BoT-SORT
* BoT-SORT paper: https://arxiv.org/abs/2206.14651
* supervision FAQ: https://supervision.roboflow.com/latest/faq/
* OpenCV optical flow: https://docs.opencv.org/3.4/de/d67/optflow_8hpp.html
* TSTTC dataset: https://arxiv.org/abs/2309.01539
* Optical-flow TTC survey: https://pmc.ncbi.nlm.nih.gov/articles/PMC6412735/

**Mobile and web platforms**

* MediaPipe Object Detector: https://ai.google.dev/mediapipe/solutions/vision/object_detector
* MediaPipe web setup: https://ai.google.dev/mediapipe/solutions/setup_web
* onnxruntime-web: https://www.npmjs.com/package/onnxruntime-web
* WebXR depth sensing support: https://caniuse.com/wf-webxr-depth-sensing
* WebKit WebXR tracking bug: https://webkit.org/b/208988
* ARKit occlusion and scene depth: https://docs.unity3d.com/Packages/com.unity.xr.arkit@6.1/manual/arkit-occlusion.html

**Runtimes and video systems**

* ONNX Runtime install: https://onnxruntime.ai/docs/install/
* DirectML execution provider: https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html
* DeepStream on WSL: https://docs.nvidia.com/metropolis/deepstream/9.1/text/DS_on_WSL2.html
* OpenEB (event cameras): https://docs.ros.org/en/iron/p/openeb_vendor/standard_docs/README.html

**Vision-language models**

* StreamingVLM project: https://hanlab.mit.edu/projects/streamingvlm
* StreamingVLM paper: https://arxiv.org/abs/2510.09608
* VideoLLM-online paper: https://arxiv.org/abs/2406.11816
* SmolVLM2: https://playground.roboflow.com/models/hugging-face/smolvlm2
* SmolVLM latency paper: https://arxiv.org/abs/2603.16987
* Moondream: https://moondream.ai/models

**Datasets**

* Pothole and stair detection: https://universe.roboflow.com/devansh2205/pothole-stair_detection
* Pothole detection: https://universe.roboflow.com/academic-jugbj/pothole-detection-nbpd2
* Pothole segmentation: https://huggingface.co/datasets/manot/pothole-segmentation2

**Assistive-navigation prior work**

* Obs-tackle paper: https://bohrium.dp.tech/paper/arxiv/95a3cc5421772c4d3a5cde401f8dc8ffe6cdc764f2f558e9222cfbf3cc44d998
* Navigation assistance platform for blind people (ARCore depth): https://www.github.com/yolly98/navigation-assistance-platform-for-blind-people
