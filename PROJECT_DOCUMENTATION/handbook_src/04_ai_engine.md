# Part 4 – AI Engine and Model Explanation

NeuroSonic contains **three** neural networks. Only the first two run on the live phone camera.

| Model | Role in the app | Framework | Device | Weights file | Licence |
|---|---|---|---|---|---|
| **RF-DETR Nano** | Primary live camera detector | PyTorch + `rfdetr` 1.11.2 | NVIDIA RTX 4050 (CUDA), FP16 | `models/rfdetr/rf-detr-nano.pth` | Apache-2.0 |
| **SSDLite320-MobileNetV3-Large** | Automatic fallback detector | PyTorch + torchvision | CPU, FP32 | `models/rgb/ssdlite320_mobilenet_v3_large_coco-a79551df.pth` | BSD-3 |
| **WOAD exp72** (base paper) | Research mode: replay and IR + depth upload | PyTorch (own copy of the original code in `woad/arch/`) | CPU (`--device cpu`) | `weights/best.pt` (SHA-256 checked) | from the original repository |

Both live detectors use **public COCO-pretrained weights**. No model was trained or fine-tuned in this project.
**TensorFlow is not used anywhere.**

## 4.1 RF-DETR Nano (primary detector)

**What it is.** RF-DETR is a *detection transformer* (DETR family) from Roboflow. A pre-trained vision-transformer
backbone turns the image into feature tokens; a transformer decoder then uses a fixed set of learned "object queries",
and each query predicts at most one object (a box plus class scores). Because each object is predicted once, DETR-style
models do **not** need non-maximum suppression. The Nano version works at **384 × 384 pixels** (`input_size = 384`).

**How NeuroSonic loads it** (`detectors.py` `RFDETRDetector.__init__`, L90):

1. Refuse to start (raise `DetectorUnavailable`) if `torch.cuda.is_available()` is false, the `rfdetr` package is
   missing, or the weights are not on disk. **Nothing is downloaded at run time** (`HF_HUB_OFFLINE=1`).
2. Limit PyTorch's CPU threads to 2 (`GPU_MODE_CPU_THREADS`), because the GPU does the heavy work.
3. `RFDETRNano(device="cuda", pretrain_weights=...)` puts the network on the GPU.
4. `self.model.inference(compile=False, dtype=torch.float16)` switches it to **FP16**. If that fails, it stays FP32.

**How one frame is detected** (`RFDETRDetector.detect`, L119): BGR image → RGB (OpenCV stores colours as BGR) →
PIL image → `model.predict(image, threshold=0.40)` → boxes `xyxy`, `confidence`, `class_id` → `_filter()` keeps
only the 23 obstacle classes.

## 4.2 SSDLite320-MobileNetV3 (fallback detector)

**What it is.** A *single-shot detector*: one pass of a light convolutional network (MobileNetV3-Large backbone)
predicts scores and box corrections for many fixed "anchor" boxes at once; torchvision then removes duplicate boxes
with NMS inside the model. It was the project's original live detector and is designed for phones and CPUs.

**How one frame is detected** (`SSDLiteDetector.detect`, L69):

1. Shrink the image so its longest side is at most 320 px (`cv2.INTER_AREA`); remember the `scale`.
2. BGR → RGB, `HWC → CHW` (`permute(2, 0, 1)`), convert to float and divide by 255 (pixel values 0–1).
3. Run the model inside `torch.inference_mode()` (no gradient bookkeeping, less memory, faster).
4. `_filter(..., scale)` keeps score ≥ 0.40 and obstacle classes, and divides boxes by `scale` so they are in the
   original image's pixels.

## 4.3 Choosing and switching detectors (GPU first, CPU fallback)

```text
neurosonic_app.py --detector auto (default)
      │
      ▼
make_detector()  ──► RF-DETR possible? (CUDA ✓, rfdetr ✓, weights ✓, FP16 warm-up on a black 320×240 image ✓)
      │                         │ yes                                   │ no (any step fails)
      ▼                         ▼                                       ▼
FallbackDetector(primary = RF-DETR on GPU)              FallbackDetector(primary = SSDLite on CPU)
      │                                                  + fallback_reason shown in /api/awareness/status
      ▼
during the session: RF-DETR raises an exception  ──►  switch to SSDLite permanently, restore CPU threads,
                                                      re-analyse the SAME frame (user gets an answer anyway)
```

The phone is told the right speed: `recommended_frame_ms` is **200 ms on the GPU** and **400 ms on the CPU**
(`awareness.py` L58, L120).

## 4.4 Which objects are reported

`OBSTACLE_CLASSES` (`awareness.py` L42) maps 23 COCO category ids to a name, a plural and a priority – for example
person, bicycle, car, motorcycle, bus, truck, dog, cow, bench, chair, potted plant, fire hydrant, stop sign. Everything
else (cups, laptops, food …) is ignored.

**Limits that must be stated honestly:** COCO has no classes for steps, kerbs, potholes, poles or walls, so neither
detector can see them. A single RGB camera gives **no distance** (`info()` reports
`"distance": "not available (single RGB camera)"`).

## 4.5 Thresholds and post-processing in one table

| Stage | Value | Where |
|---|---|---|
| Detector confidence | ≥ 0.40 | `score_thres` in `detectors.py`, `awareness.py` |
| Image unusable | grey mean < 20 or std < 6 | `awareness.py quality()` |
| Image dark (warning) | mean < 45 | `awareness.py quality()` |
| Image blurred → "uncertain" | Laplacian variance < 20 | `pathguide.py` |
| Path BLOCKED (one frame) | covers ≥ 30 % of path region and centred/mostly inside, or large box at the bottom | `pathguide.py assess_frame` |
| Path POSSIBLE obstacle | covers ≥ 6 % or ≥ 35 % of box inside region | `pathguide.py` |
| Confirmation over frames | BLOCKED 2 of 3; CLEAR needs 3 clear frames | `PathGuide._decide` |
| Tracker matching | IoU ≥ 0.25 (confident ≥ 0.55), IoU ≥ 0.45 (0.40–0.55) | `tracking.py` |
| Camera-motion estimate | ≥ 12 RANSAC inlier points | `tracking.py` |
| Entering event | relative speed ≥ 0.12 widths/s, within 1.5 s | `events.py` |
| Crossing event | 0.35 → 0.65 of the width within 3 s, speed ≥ 0.15 | `events.py` |
| WOAD detections | conf 0.25, NMS IoU 0.45 | `woad/detector.py` |

## 4.6 CUDA, FP16 and CPU fallback in simple words

- **CUDA** lets PyTorch send the network's matrix calculations to the thousands of small cores on the NVIDIA GPU.
- **FP16** stores numbers in 16 bits instead of 32. The GPU moves half as much data and uses its fast half-precision
  units. Measured result (`benchmark_precision.py`): person AP@0.5 **0.6600 (FP16) vs 0.6597 (FP32)**, paced median
  latency **53.2 ms vs 66.5 ms**.
- **CPU fallback** means the app never depends on the GPU: if CUDA is missing (for example started from `.venv`),
  SSDLite runs on the CPU, and the phone sends frames every 400 ms instead of 200 ms.

## 4.7 The base-paper WOAD model (research mode)

WOAD is a YOLOv5-style detector with **two inputs**: a near-infrared image and a colour-mapped depth image from the
CS30 sensor. After layer 2 a **transformer fuses the two streams** (8 attention blocks on 8×8 pooled tokens). The head
outputs 25,200 candidate boxes; NMS keeps the best ones. Classes: person, Ebike, Car.

It is **not** used on the phone camera, because an ordinary RGB photo is a different kind of input. In NeuroSonic it
powers the replay screen (`/api/replay/*`) and the IR + depth upload (`/api/detect`). Measured on the published data:
person AP@0.5 **0.218**; the authors' reported 0.669 mAP could not be verified.

## 4.8 Optional online scene description (not a detector)

`neurosonic/vision/` sends **one photo, only after the user agrees**, to Google Gemini (default model
`gemini-3.8-flash`, key read from `GEMINI_API_KEY` on the laptop only). The answer is filtered and spoken as a
`scene` message. It needs internet; local guidance continues without it. The image is processed in memory and never
stored.
