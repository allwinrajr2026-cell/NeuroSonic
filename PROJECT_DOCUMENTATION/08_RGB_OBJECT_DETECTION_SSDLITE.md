# 8. RGB camera object detection: SSDLite320-MobileNetV3-Large

## 8.1 Problem

The WOAD model needs a Synexens CS30 sensor (near-infrared + depth), which ordinary phones don't have. To give
**live** camera awareness with a normal phone camera, a detector for ordinary colour (RGB) images is needed.

## 8.2 Choice of model

| Candidate | Comment |
|---|---|
| WOAD exp72 | cannot be used: it needs IR + depth input |
| Repository's `best-fp16.tflite` (stock COCO YOLOv5s, Android app) | would need TensorFlow (about 400 MB) to run in Python on Windows / Python 3.12; not reused |
| **torchvision `ssdlite320_mobilenet_v3_large`, COCO weights** | **chosen**: part of torchvision 0.29.2, which was already installed; only 14 MB of weights to download; 3.44 M parameters; fast on CPU; BSD-3 licence |

**Weights:** `models/rgb/ssdlite320_mobilenet_v3_large_coco-a79551df.pth`, 14,069,355 bytes. The SHA-256 starts
`a79551df`, matching the hash in the file name. Accuracy per the torchvision metadata: **COCO val2017 box mAP
21.3**, a modest detector. This figure is torchvision's published metadata; it was not re-measured in this project.

## 8.3 How SSDLite / MobileNetV3 works (for the viva)

* **CNN backbone, MobileNetV3-Large.** A convolutional neural network designed for phones. It uses
  depthwise-separable convolutions (a cheap per-channel convolution followed by a 1×1 convolution), inverted
  residual blocks, squeeze-and-excitation attention and the hard-swish activation. It turns the image into
  feature maps at several scales.
* **SSD, the Single-Shot multibox Detector.** At each position of several feature maps it predicts, for a fixed
  set of **default (anchor) boxes**, the class scores and box offsets, in **one pass** (single-stage, like YOLO;
  unlike two-stage Faster R-CNN). **SSDLite** replaces the ordinary convolutions in the prediction heads with
  depthwise-separable ones, making it cheaper.
* **Post-processing:** per-class score thresholding and **non-maximum suppression** remove overlapping
  duplicates.
* **Input size:** "320" means it is designed for about 320×320 inputs, which makes it fast.

## 8.4 Implementation: `neurosonic/awareness.py::RGBAwareness`

| Function | Lines | What it does |
|---|---|---|
| `_load` | L126–134 | creates the detector with `detectors.make_detector` (2026-11-03): RF-DETR Nano on CUDA when available (`.venv-gpu`), otherwise the SSDLite320 described here (`ssdlite320_mobilenet_v3_large(weights=None, num_classes=91)`, local state dict, eval mode); the fallback reason is reported |
| `detect` | L145–156 | runs the active detector under a lock (SSDLite: long side ≤ 320 px, BGR→RGB, one forward pass, only `OBSTACLE_CLASSES` (L41) with score ≥ 0.40, boxes rescaled; RF-DETR: same output format); counts frames per detector |
| `quality` | L159–166 | grey mean/std: < 20 or std < 6 → UNUSABLE ("too dark or covered"); < 45 → WARN |
| `_session` / `_state` | L172–191 | per phone session (sessions idle > 120 s are removed): one `woad.alerts.AlertEngine`, one `PathGuide`, one `ByteTracker`, one `PathEventDetector` and the previous frame for camera motion; recreated when the carrying mode changes |
| `process_frame` | L193–266 | decode JPEG → quality → detect → camera motion + tracking → **walking-path state** → **entering / crossing events** → optional object descriptions → JSON with `path`, `tracks`, `camera_motion`, `detector`, `timing` |

* **Obstacle classes** (`OBSTACLE_CLASSES` L41): person, bicycle, car, motorcycle, bus, truck, traffic light,
  fire hydrant, stop sign, bench, cat, dog, horse, cow, chair, sofa, potted plant, table, TV, microwave,
  refrigerator, umbrella, suitcase. Each has a spoken name and a priority; vehicles have the highest.
* **Carrying modes** (`MODES` L50):
  * `chest` → "on the left / ahead / on the right";
  * `handheld` → "in camera view, left / centre / right". It never says "ahead", because a handheld camera may
    not point where the user walks.
* **Urgency (replaced on 2026-11-02).** Originally, an object in the middle third covering ≥ 25 % of the image got
  the prefix "Caution.". Since the product refinement, urgency comes from the walking-path state BLOCKED_VIEW
  ("Stop. The walking path may be blocked."), and object names are spoken only in the optional Object Description
  mode, never as urgent. See `17_PRODUCT_REFINEMENT.md`. The original code was:

```python
urgent = (e.kind == "object" and e.data.get("position") == "ahead"
          and e.data.get("max_area_frac", 0) >= URGENT_AREA)
d["urgent"] = urgent
if urgent:
    d["text"] = "Caution. " + d["text"]
```

### Client side: `web/js/app.js`

* `startAwareness` (L541–566) opens the rear camera (`facingMode: "environment"`).
* `awarenessStep` (L580–637) runs every 400 ms:
  1. draws the video into a 320 px canvas;
  2. `toBlob('image/jpeg', 0.7)`;
  3. `POST /api/awareness/frame?session&mode`.
  If the previous request is still running, it skips the frame (`aBusy`).
* **Overlay:** `drawAwareness` (L638–660) draws the returned boxes over the preview.
* **Speech:** events are spoken with category `urgent`, `obstacle` or `system`.

## 8.5 Measured results

| Test | Result | Evidence |
|---|---|---|
| Inference time | about 38–55 ms per 320 px frame (laptop CPU) | session measurements |
| Real recorded frames (near-IR images from `detec_test`, *not* colour) | people and bicycles detected; confirmed alerts after 2 frames; a false "Fire hydrant" (0.51) on one frame | `test_detects_people_and_confirms_over_frames`, session output |
| Handheld wording never says "ahead" | passes | `test_handheld_wording_never_says_ahead` |
| Dark frame → unusable → "Obstacle detection unavailable" | passes | `test_dark_frame_is_unusable_and_reported` |
| Blocked path (replaces the urgency heuristic) | a large central person → "Stop. The walking path may be blocked." with the urgent flag | `test_urgent_flag_for_large_central_object` (updated) |
| Offline | 0 network attempts | `test_offline` |
| Browser with Chrome's fake camera playing recorded frames | spoken "Person …" alert | `ui_final_cdp.mjs` PASS |
| **Real phone camera in real streets** | **not measured** | acceptance test C1 pending |

## 8.6 Limitations

* Low COCO accuracy (mAP 21.3), never measured on Indian street scenes.
* It cannot detect steps, kerbs, holes, poles, walls or wet floors. The app therefore says only "The visible
  path *appears* clear. Continue carefully.", which means "no recognised object in the path region", never "safe".
* **No distance**, because a single RGB camera cannot measure it.
* Inference runs on the laptop: about 2.5 frames/s over Wi-Fi, so latency depends on the network.

## 8.7 Likely questions

* *Why not use YOLO here too?* WOAD *is* a YOLOv5-based two-stream model, but it needs IR + depth. A YOLO COCO
  model for RGB would need another dependency or download. SSDLite was already available in torchvision; it is
  less accurate and that is documented.
* *What does 21.3 mAP mean?* The mean Average Precision over COCO's 80 classes and over IoU thresholds
  0.50–0.95. Roughly, it indicates how well boxes are found *and* localised. 21.3 is modest.
* *How do you avoid speaking every frame?* The shared `AlertEngine`: 2-of-3 confirmation, cooldowns, repetition
  rules, merging.
