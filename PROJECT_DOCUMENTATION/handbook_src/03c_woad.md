## D1. File: woad/model_loader.py {: .file}

#### 1. Purpose
Loads the base-paper **WOAD exp72** checkpoint safely: it verifies the file's SHA-256 fingerprint, loads the pickled
PyTorch model without importing the broken original training code, and checks the architecture.

#### 2. How the code works (`load_model`, L76)
1. Check the file exists; compute `sha256()` (L34). For the default `weights/best.pt`, require
   `EXP72_BEST_SHA256 = "da043ff2e1edd393…"` (L24); otherwise raise `CheckpointError` ("modified or replaced").
2. Inside `_legacy_module_aliases()` (L46), temporarily map the module names `models`, `models.yolo`, `models.common`
   (used inside the pickle) to our copied classes in `woad.arch`, then restore `sys.modules`.
3. `torch.load(weights, map_location="cpu", weights_only=False)` – required because the YOLOv5-format checkpoint
   stores a whole `nn.Module`.
4. Take `ckpt["ema"]` or `ckpt["model"]`; check it is `arch_yolo.Model` and that its children equal
   `EXPECTED_CHILDREN` (refuses the different 5-class root `best.pt`).
5. `model.float().eval().to(device)`; freeze all parameters; return `(model, info)` with names, number of classes,
   strides, parameter count (7,521,992) and device.

#### 6. Faculty demonstration explanation
> "The original checkpoint can only be loaded with the authors' code, which no longer works with current PyTorch and
> NumPy. Here I load it with a copy of only the nine classes it needs, after checking its fingerprint, so a wrong or
> modified file is refused."

#### 7. Possible faculty questions
- **Is `weights_only=False` dangerous?** Unpickling can run code, so only the hash-verified, trusted file is loaded.
- **How do you know the copy is identical?** `tools/verify_equivalence.py` runs both versions on the same input; the
  maximum difference is 0.0.

## D2. Files: woad/arch/yolo.py and woad/arch/common.py {: .file}

#### 1. Purpose
The WOAD neural network (copied from the original repository): a YOLOv5-style detector with **two input streams** –
a near-infrared image and a colour-mapped depth image – fused by a transformer.

#### 2. How the code works (`Model._forward_once`, yolo.py L165)
1. The depth stream (`self.model1`: Conv, Conv, C3) produces depth features.
2. The IR stream runs through `self.model` layer by layer. After layer 2 (`if i == 2`, L175) the fusion happens:
   - both feature maps are weighted 0.5 / 0.5 (`init_score`);
   - average-pooled to 8×8 (`self.avp`), flattened and concatenated as tokens, plus a position embedding;
   - passed through the transformer blocks (`self.trans_blocks`, 8 blocks of self-attention) and normalised;
   - split back into IR and depth parts, upsampled, and multiplied with each stream's convolution features;
   - concatenated and reduced with `conv3` → continue through the rest of the YOLO network.
3. The `Detect` head outputs 25,200 candidate boxes per image (8 values each: box, objectness, 3 class scores).

`common.py` holds the building blocks `Conv`, `C3`, `SPPF`, `Concat`. `Model.__init__` deliberately raises an error:
the model can only come from the checkpoint (training is not part of this package).

#### 6. Faculty demonstration explanation
> "This is the base paper's model. The infrared and depth images go through two branches, and after the second layer a
> transformer lets every region of one image attend to every region of the other. That is the 'cross-modal fusion'.
> We measured that IR matters most: blanking the IR removes all detections, blanking depth keeps about 65 %."

#### 7. Possible faculty questions
- **Why can't the phone camera use WOAD?** It needs the CS30 sensor's IR + colour-depth pair; an RGB photo is a
  different kind of input.
- **How good is it?** The authors report mAP@0.5 0.669 from their plot (not verifiable). On the published dataset we
  measured person AP@0.5 = 0.218.
- **Classes?** person, Ebike, Car.

## D3. Files: woad/preprocess.py and woad/ops.py {: .file}

#### 1. Purpose
Prepare inputs exactly as during training, and provide the YOLO helper functions: letterbox, non-maximum suppression
(NMS) and mapping boxes back to the original image.

#### 2. How the code works
1. `read_image()` (preprocess L36) reads 8-bit images; a grey or 16-bit depth image is rejected.
2. `preprocess_ir()` (L62): resize the long side to 640 (INTER_AREA when shrinking), letterbox to 640×640 with grey
   padding 114. `preprocess_depth()` (L72): `cv2.medianBlur(depth, 3)`, then letterbox.
3. `_to_tensor()`: BGR→RGB, HWC→CHW, divide by 255. `prepare_pair()` (L87) returns both tensors plus originals.
4. `non_max_suppression()` (ops L74): drop boxes below the confidence threshold and keep the best box among
   overlapping boxes of the same class (IoU > 0.45). `scale_coords()` (L161) undoes the letterbox.

#### 6. Faculty demonstration explanation
> "A model only works if the input is prepared exactly as in training. I copied these rules from the original
> validation code, and mutation tests prove it: removing the median blur or the colour conversion makes tests fail."

#### 7. Possible faculty questions
- **What is letterboxing?** Resizing while keeping the aspect ratio and padding the rest, so the image becomes square.
- **What is NMS?** Non-maximum suppression: among overlapping boxes for the same object, keep only the highest score.

## D4. File: woad/detector.py {: .file}

#### 1. Purpose
`WOADDetector`: one simple interface around loading, preprocessing, the forward pass, NMS and box mapping.

#### 2. How the code works
`__init__` (L20) calls `load_model`. `raw_forward(ir, depth)` (L45) runs `self.model(ir, depth)[0]` under
`torch.inference_mode()` → shape (B, 25200, 8). `detect_prepared()` (L49) applies NMS (`conf_thres` 0.25 default,
`iou_thres` 0.45), scales boxes to original IR pixels and returns `detections` plus timings. `detect_arrays()` and
`detect_files()` accept images or file paths.

#### 6. Faculty demonstration explanation
> "This is the WOAD equivalent of a detector class: two images in, a list of boxes with class names and confidences
> out, in the original image's pixel coordinates."

#### 7. Possible faculty questions
- **Who uses it?** `neurosonic/service.py` (replay and upload), `woad_detect.py` and `tools/evaluate.py`.

## D5. File: woad/quality.py {: .file}

#### 1. Purpose
The **input-quality gate** for WOAD frames: it decides whether a frame is similar enough to the training data for the
detections to mean anything. Unusable frames never reach the detector.

#### 2. How the code works (`InputQualityChecker.check`, L55)
1. Compute the IR grey **mean** and **standard deviation** (contrast) and the share of **invalid (black) depth
   pixels**.
2. Apply `QualityThresholds` (L28): mean < 40 or std < 10 or > 95 % invalid depth → `UNUSABLE`; mean < 100 or
   std < 40 → `WARN`; different IR/depth sizes → `WARN`; otherwise `OK`.
3. Return `QualityReport(status, reasons, ir_mean, ir_std, depth_invalid)`.

The thresholds were calibrated on our data (docstring table): 100 % of `detec_test` passes; the dark CS30 recording
is 42.5 % unusable and 56.1 % warn.

#### 6. Faculty demonstration explanation
> "We found the model is blind on dark infrared images – the sensor recording averaged brightness 59 versus 135–142 in
> training-like data. Instead of guessing, this gate refuses such frames and the system says 'Obstacle detection
> unavailable: IR image too dark'. A silent false 'all clear' would be worse."

#### 7. Possible faculty questions
- **Why not brighten dark images?** We tested five corrections; the best one found one real person but produced 56
  false alarms, so none was adopted.
- **Is the camera pipeline using the same gate?** It uses the same `QualityReport` type, with its own thresholds for
  phone photos (`awareness.py quality()`).

## D6. File: woad/alerts.py {: .file}

#### 1. Purpose
`AlertEngine` turns flickering detections into a few stable, non-repetitive spoken messages, and reports when
detection is unavailable. Used by the WOAD replay/upload and by Object Description mode for the phone camera.

#### 2. How the code works (`process`, L140)
1. If the input is unusable or missing for longer than `unavailable_after_s`, say "Obstacle detection unavailable:
   <reason>"; after recovery, "resumed".
2. Keep detections with confidence ≥ `alert_conf` (0.40).
3. Match them to existing tracks by IoU ≥ 0.30 (per class); each track remembers hits in the last 3 frames.
4. A track is **confirmed** with 2 hits in 3 frames (`confirm_hits`, `confirm_window`).
5. Position = left / ahead / right by thirds of the image.
6. Announce once; repeat only after 15 s (`repeat_s`) or a position change; merge similar objects ("2 people detected
   ahead"); at most 2 messages per frame, ordered by class priority.

`AlertConfig` (L31) holds all thresholds and wording (the camera uses chest/handheld wording and no "detected" word).

#### 6. Faculty demonstration explanation
> "A detector produces many boxes per second; a user needs a few correct sentences. This engine confirms each object
> over 2 of 3 frames, says where it is, and avoids repeating itself."

#### 7. Possible faculty questions
- **Why 2 of 3?** One-frame false positives are not spoken; it costs about one frame of delay. The values are
  engineering defaults, not user-validated.
- **Are messages invented?** No; they are fixed templates filled only from detections in the current frame (a
  randomised test checks this).

## D7. Files: woad/sources.py, replay.py, pairing.py, visualize.py, metrics.py, woad_detect.py, woad_replay.py {: .file}

#### 1. Purpose
Support code and command-line tools for the base-paper reproduction.

#### 2. What each does
| File | Role |
|---|---|
| `woad/pairing.py` | `pair_directories()` pairs IR and depth files by exact filename and lists unpaired files |
| `woad/sources.py` | `ReplaySource` yields `Frame` objects with synthetic timestamps (index / fps) and detects clip changes from filename-number gaps |
| `woad/replay.py` | `run_replay()`: the offline replay pipeline (quality → detector or cached detections → alert engine) |
| `woad/visualize.py` | draws boxes and makes the IR/depth side-by-side image |
| `woad/metrics.py` | the original YOLOv5 scoring code (`ap_per_class`, `process_batch`), proven identical by a test |
| `woad_detect.py` | CLI: detect on one pair, two folders or a `--source` folder; writes annotated images, JSON and `results.json` in a new run folder (never overwrites) |
| `woad_replay.py` | CLI: replays recorded frames through detector + alert engine, writes `transcript.txt` / `.jsonl`; two runs give byte-identical transcripts |

#### 6. Faculty demonstration explanation
> "With these tools I reproduced the base paper on Windows: `woad_detect.py --source demo_data/detec_test` processes
> the authors' 600 recorded frames, and `woad_replay.py` shows which spoken alerts the system would produce."

#### 7. Possible faculty questions
- **What does `detec_test` show?** Detections in 313 of 600 frames (person 271, Ebike 160, Car 52), with some visible
  errors (a missed person, cars on shrubs).
