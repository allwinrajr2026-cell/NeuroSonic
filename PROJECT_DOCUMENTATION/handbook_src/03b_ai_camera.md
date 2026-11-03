## C1. File: neurosonic/awareness.py {: .file}

#### 1. Purpose
The **live camera pipeline**. It receives one JPEG from the phone and returns the walking-path state, event
messages, detections and timing. It holds the detector, runs all inference on one dedicated thread, and keeps
separate state for each phone session.

#### 2. How the code works (`process_frame`, L205)
1. Check `mode` (`chest` or `handheld`); decode the JPEG with `cv2.imdecode` (error 400 if it cannot be decoded).
2. `quality(bgr)` (L171): grey mean and standard deviation. Mean < 20 or std < 6 → `UNUSABLE` ("too dark or
   covered"); mean < 45 → `WARN`; otherwise `OK`.
3. If usable, `detect(bgr)` (L153) submits `_detect_on_worker` to the single-thread `ThreadPoolExecutor` and waits.
   The worker loads the detector on first use (`_load` → `make_detector`) and runs it.
4. `_state(session, mode)` (L189) returns the per-phone `_Session` (alert engine, `PathGuide`, `ByteTracker`,
   `PathEventDetector`, previous grey frame). Sessions idle for 120 s are deleted.
5. **Tracking:** `small_gray()` → `estimate_camera_motion(prev_gray, gray, track boxes)` →
   `st.tracker.update(dets, t, w, h, cam)`.
6. **Walking guidance:** `assess_frame(...)` gives this frame's level; `guide.update(fa, t)` confirms it over frames
   and says whether to announce.
7. **Events:** `st.events.update(tracks, …, path["state"])`. If an "entering" event and a generic "Caution" happen
   together, the more specific entering sentence replaces the generic one (L237–248).
8. **Object description** (only if `describe=True`): the WOAD `AlertEngine` (re-used) produces "Person on the left."
   style messages with category `description` (never interrupting).
9. Per-device counters (`self.clients`: frames, frame size, detector, processing times) are updated – counters only,
   no image.
10. Return a dict: `path`, `events`, `detections`, `tracks`, `camera_motion`, `detector`, `timing`, `quality`.

#### 3. Important functions and classes

| Name | Input | Processing | Output | Called by |
|---|---|---|---|---|
| `OBSTACLE_CLASSES` L42 | — | COCO id → (name, plural, priority), 23 classes | dict | detectors, alert engine |
| `RGBAwareness.__init__` L80 | SSDLite weights, detector preference | creates the 1-thread executor `_infer` | object | `neurosonic_app.py` |
| `info()` L111 | — | detector name/device/precision, `recommended_frame_ms`, clients | dict | `/api/awareness/status` |
| `warm_up()` L144 | — | detects on a black 320×240 image | True/False | `neurosonic_app.py` |
| `detect()` / `_detect_on_worker()` L153/L159 | BGR image | runs the active detector under a lock, counts frames | detections list | `process_frame` |
| `quality()` L171 | BGR image | brightness/contrast check | `QualityReport` | `process_frame` |
| `process_frame()` L205 | JPEG bytes, session, mode, describe | full pipeline above | result dict | `server.py r_awareness_frame` |

#### 4. Important code sections
- **One inference thread (L91–95):** `self._infer = ThreadPoolExecutor(max_workers=1, thread_name_prefix=
  "neurosonic-infer")`. The comment records why: running the GPU model from ever-new request threads made memory grow
  about 2 MiB/s in a 10-minute soak test.
- **Frame interval (L58, L120):** `FRAME_MS_GPU, FRAME_MS_CPU = 200, 400` and
  `"recommended_frame_ms": FRAME_MS_GPU if det["device"] == "cuda" else FRAME_MS_CPU` – the server tells the phone
  how fast to send.
- **Priorities (L233):** path messages get `urgent 40 / obstacle 30 / system 20 / info 5`.

#### 5. Connections
Called by `server.py`. Uses `detectors.py`, `tracking.py`, `pathguide.py`, `events.py`, and from the WOAD package
`woad/alerts.py` (`AlertEngine`) and `woad/quality.py` (`QualityReport`, `OK/WARN/UNUSABLE`).

#### 6. Faculty demonstration explanation
> "This is the heart of the live system. One camera frame comes in; I check the brightness, run RF-DETR on the GPU,
> track the objects while cancelling the phone's own movement, decide whether the walking path is clear, possibly
> blocked or blocked, and check whether something is moving into the path. Only changes are spoken."

#### 7. Possible faculty questions
- **Why one inference thread?** The web server creates a new thread for every request; PyTorch/CUDA kept per-thread
  state that was never freed. One long-lived thread fixed the memory growth (soak test: flat memory, 0 errors).
- **Why keep state per session?** Confirmation over frames and tracking need the history of the *same* phone; two
  phones must not mix.
- **Does it measure distance?** No – `info()` even reports `"distance": "not available (single RGB camera)"`.
- **What if the image is too dark?** No detection runs; the path state becomes "I cannot clearly assess the path".

## C2. File: neurosonic/detectors.py {: .file}

#### 1. Purpose
The two object detectors and the logic that chooses between them: **RF-DETR Nano on the NVIDIA GPU (FP16)** as the
primary detector, and **SSDLite320-MobileNetV3 on the CPU** as the guaranteed fallback.

#### 2. How the code works (`make_detector`, L161)
1. Read the preference (`auto` / `rfdetr` / `ssdlite`). For `ssdlite` return SSDLite directly.
2. Otherwise build `RFDETRDetector` (L87):
   - raise `DetectorUnavailable` if CUDA is not available, the `rfdetr` package is missing, or the local weights are
     not found (`find_rfdetr_weights()` looks in `models/rfdetr/` and `~/.roboflow/models/`; nothing is downloaded);
   - set `HF_HUB_OFFLINE=1`; limit PyTorch to 2 CPU threads (`GPU_MODE_CPU_THREADS`);
   - create `RFDETRNano(device="cuda", pretrain_weights=…)`;
   - try `self.model.inference(compile=False, dtype=torch.float16)` → precision `fp16`, else stay `fp32`.
3. Warm-up: detect on a black 320×240 image to prove inference works on this machine.
4. Wrap it in `FallbackDetector(primary, ssd)`. If any step fails, log the reason and return SSDLite.
5. At run time, `FallbackDetector.detect()` (L147): if RF-DETR throws an exception, switch permanently to SSDLite,
   restore the CPU thread count, and **re-analyse the same frame** with SSDLite.

#### 3. Important functions and classes

| Name | Input | Processing | Output | Called by |
|---|---|---|---|---|
| `_filter(...)` L40 | raw boxes, scores, labels | keep score ≥ threshold and class in `OBSTACLE_CLASSES` | list of `{class_id, class_name, confidence, box_xyxy}` | both detectors |
| `SSDLiteDetector.detect()` L69 | BGR image | resize to max 320 px, BGR→RGB, tensor /255, `inference_mode` | detections in original pixels | `FallbackDetector` |
| `RFDETRDetector.detect()` L119 | BGR image | BGR→RGB PIL image, `model.predict(threshold=0.40)` | detections | `FallbackDetector` |
| `FallbackDetector` L125 | primary, fallback factory | switch on first runtime failure | `name`, `device`, `fallback_reason` | `awareness.py` |
| `make_detector()` L161 | classes, preference | choose, warm up, fall back | `(detector, info)` | `RGBAwareness._load` |

#### 4. Important code sections
- **CPU busy-wait fix (L30–33, L104):** with PyTorch's default 8 threads the idle threads spun between frames
  (measured 712 % of one core vs 121 % with 2 threads, same latency).
- **FP16 (L107–115):** the comment records the measurement: person AP@0.5 0.660 in both FP16 and FP32.

#### 5. Connections
Used by `awareness.py`. Imports `torch`, `cv2`, `numpy`, and lazily `torchvision` (SSDLite) and `rfdetr`.

#### 6. Faculty demonstration explanation
> "Here the detector is chosen. If CUDA, the RF-DETR package and its weights are all present, RF-DETR Nano runs on
> the RTX 4050 in half precision. If anything is missing – or if RF-DETR fails during a session – the app switches
> to SSDLite on the CPU automatically and says why. The user never loses guidance because of the GPU."

#### 7. Possible faculty questions
- **Why RF-DETR Nano?** In our benchmark it was the most accurate (person AP@0.5 0.660 vs SSDLite 0.542), fast on the
  GPU (21.3 ms FP32), and Apache-2.0 licensed.
- **Why not YOLO26?** Faster, but AGPL-3.0: offering NeuroSonic over a network would oblige publishing our source.
- **What does FP16 change?** Same accuracy in our test, lower latency at 5 frames/s (53.2 vs 66.5 ms median).
- **What is the confidence threshold?** 0.40 (`score_thres`) for both detectors.
- **Was the model trained by you?** No. Both detectors use public COCO-pretrained weights; no training was done.

## C3. File: neurosonic/pathguide.py {: .file}

#### 1. Purpose
Turns detections into **walking guidance**. The lower-middle part of the image is treated as the walking path, and one
of five states is decided and confirmed over frames: `CLEAR_VIEW`, `POSSIBLE_OBSTACLE`, `BLOCKED_VIEW`, `UNCERTAIN`,
`CAMERA_UNAVAILABLE`.

#### 2. How the code works
1. `PATH_POLYGON` (L57) is a trapezoid in normalised image coordinates: bottom from x 0.22 to 0.78, top from 0.40 to
   0.60 at y 0.45. `_path_mask()` rasterises it on a 64×48 grid.
2. `assess_frame()` (L119) for one frame:
   - unusable image → `UNCERTAIN`; sharpness (Laplacian variance) < 20 → `UNCERTAIN`;
   - for each detection with confidence ≥ 0.40, `box_path_overlap()` gives *cover* (share of the path region covered)
     and *inpath* (share of the box inside the region);
   - **BLOCKED** if cover ≥ 0.30 and the object is centred or mostly inside, or if inpath ≥ 0.50 and the box reaches
     the bottom 10 % and is at least half the image height; **POSSIBLE** if cover ≥ 0.06 or inpath ≥ 0.35;
   - a "clear" frame that is too dark (brightness < 45 or quality WARN) becomes `UNCERTAIN`.
3. `PathGuide.update(fa, t)` (L191) keeps the last 3 frames and `_decide()` (L172): `BLOCKED` if 2 of 3 frames are
   blocked; `POSSIBLE` if 2 of 3 are blocked or possible; `UNCERTAIN` after 2 uncertain frames in a row; `CLEAR` only
   after 3 clear frames; otherwise keep the current state (hysteresis).
4. Announcement policy: speak when the state changes (escalations at once; de-escalations only after 2 s of quiet),
   repeat "Stop … may still be blocked" every 8 s, repeat uncertain every 30 s, repeat caution only if the obstruction
   moved to another zone.

#### 3. Important functions and classes

| Name | Input | Output | Called by |
|---|---|---|---|
| `Thresholds` L73 | — | all numeric thresholds in one dataclass | `assess_frame` |
| `sharpness(bgr)` L85 | image | Laplacian variance of a 320 px grey copy | `awareness.py` |
| `box_path_overlap(box, w, h)` L93 | box | (cover, inpath) | `assess_frame`, `events.py` |
| `assess_frame(...)` L119 | detections, size, quality, brightness, sharpness | `FrameAssessment(level, reason, in_path, at_side)` | `awareness.py` |
| `PathGuide.update()` L191 | assessment, time | dict(state, announce, text, category) | `awareness.py` |

#### 6. Faculty demonstration explanation
> "A blind user does not need a list of object names every half second. This file decides one calm state for the
> walking path and speaks only when it changes. 'Clear' needs three good frames, warnings need two of three, and a dark
> or blurred image can never be called clear. The message is 'appears clear, continue carefully' – never 'safe'."

#### 7. Possible faculty questions
- **Why a trapezoid?** A chest-mounted camera sees the walking path widening towards the bottom of the image, like a
  corridor in perspective.
- **Does lower in the image mean closer?** Not reliably, so the code never claims a distance.
- **Are the thresholds validated?** No. They are engineering defaults, not tested with users or on Vellore streets.
- **Why hysteresis?** Without it the state would flicker between clear and caution on noisy detections.

## C4. File: neurosonic/tracking.py {: .file}

#### 1. Purpose
Follows each object from frame to frame and measures its motion **relative to the background**, so that the user's
own walking or turning does not look like objects moving.

#### 2. How the code works
1. `estimate_camera_motion(prev_gray, gray, exclude_boxes)` (L41): find up to 150 corner points
   (`cv2.goodFeaturesToTrack`) outside the detected objects, follow them with Lucas–Kanade optical flow
   (`cv2.calcOpticalFlowPyrLK`), and fit a similarity transform (shift, scale, rotation) with RANSAC
   (`cv2.estimateAffinePartial2D`). At least 12 inlier points are needed, otherwise `ok=False`.
2. `ByteTracker.update(dets, t, w, h, cam)` (L125), ByteTrack-style:
   - move each track's last box by the camera motion (where it would be if it stood still);
   - match **confident** detections (≥ 0.55) by IoU ≥ 0.25, then **lower-confidence** ones (0.40–0.55) to the
     remaining tracks with IoU ≥ 0.45, always within the same class;
   - for matched tracks store `rel_dx, rel_dy` = observed centre minus predicted static centre (image fractions);
   - delete tracks missed more than 3 frames; start new tracks only from confident detections.

#### 6. Faculty demonstration explanation
> "When the person carrying the phone walks, everything in the picture moves. Here I estimate that global movement from
> the background and subtract it, so a parked car that slides across the image while the user turns is not treated as
> moving. The tracker is a small implementation of the ByteTrack idea, without an extra library."

#### 7. Possible faculty questions
- **What is IoU?** Intersection over union: overlap area divided by combined area of two boxes (0 to 1).
- **Why two matching rounds?** Low-confidence detections help keep an existing track alive but should not start new
  ones (fewer false tracks).
- **Is this the official ByteTrack code?** No, a small own implementation of the same idea (cited in the docstring).

## C5. File: neurosonic/events.py {: .file}

#### 1. Purpose
Conservative **event alerts** from the tracks: an object **entering** the walking path from a side, or **crossing**
in front of the user. "Approaching" is deliberately not announced.

#### 2. How the code works (`PathEventDetector.update`, L59)
1. Keep a short history of camera motion; return nothing if the state is `UNCERTAIN`, `CAMERA_UNAVAILABLE` or
   `BLOCKED_VIEW`, or if an event was spoken less than 3 s ago (`GLOBAL_GAP_S`).
2. Consider only confirmed tracks (≥ 3 hits, ≥ 0.4 s old) of classes that move by themselves (`MOVERS`: person,
   bicycle, motorcycle, car, bus, truck, dog, cat, cow, horse).
3. Require a **stable camera** in the window (shift ≤ 6 % of the width per frame, scale change ≤ 4 %).
4. `_entering()` (L87): within 1.5 s the box was outside the path region and now overlaps it, and its relative
   horizontal speed towards the centre is ≥ 0.12 image widths per second → "Caution. A bicycle is moving into your path
   from the left."
5. `_crossing()` (L112): within 3 s the centre moved from < 0.35 to > 0.65 of the width (or back), speed ≥ 0.15, box
   in the lower half → "A person is crossing in front of you, from left to right."
6. Each event type is spoken once per track, at most one event per frame.

#### 6. Faculty demonstration explanation
> "Objects alone are not enough – what matters is movement into the path. Using motion relative to the background,
> these rules detect someone stepping into the path or crossing in front. I deliberately left out 'approaching',
> because with a walking camera every object grows in the picture, which would cause false alarms."

#### 7. Possible faculty questions
- **How fast is the entering alert?** On the demo clip about 1 s after the rider first appears.
- **Why suppress events while the camera shakes?** Object motion cannot be separated from the user's motion then.
- **Why no events during "Stop"?** The urgent "Stop" message is already the right warning.
