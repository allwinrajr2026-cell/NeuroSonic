# Evaluation of the exp72 checkpoint on the published WOAD dataset

Date: 2026-11-02. Tool: `tools/evaluate.py`. Raw results: `outputs/eval/<run>/metrics.json`,
`per_image.json` and `pr_curve.json`.

## TL;DR

* The published dataset (`VOCdetiv_data.rar`) is **not the dataset exp72 was trained or validated on.**
  Its classes are person / box / bike / doors / poles / signs …. There is no Ebike class and no Car
  class. None of exp72's 187 validation frames appear in it.
* **The training-time figure (mAP@0.5 = 0.669, person 0.771, Ebike 0.839, Car 0.395) therefore
  cannot be re-measured with the published data.** It remains an unverified number read from a plot.
* The genuine measurement possible here is **person only, on a different dataset (cross-dataset)**:
  **AP@0.5 = 0.218 (val, 129 people) and 0.173 (train split, 458 people)**. The model is precise
  but misses most people in this data, especially cyclists and distant people.

## 1. Three kinds of numbers. Keep them apart.

| Source | What it measures | person | Ebike | Car | Status |
|---|---|---|---|---|---|
| Training plots `runs/train/exp72/PR_curve.png` | exp72's own val split (187 images), FP16/CUDA, 2023 | 0.771 | 0.839 | 0.395 | **reported by the authors, not reproducible** (data unpublished) |
| Reconstructed demo frames (`demo_data/reconstructed_val`) | sanity only: 13/16 frames agree with training-time predictions | — | — | — | **no labels; never use for accuracy** |
| **This evaluation** (`VOCdetiv_data`, nc_10) | genuine AP@0.5 on a different, published dataset, FP32/CPU | **0.218** val / **0.173** train | n/a (no Ebike labels) | n/a (no Car labels) | **measured** |

## 2. Dataset identity and integrity

| Check | Result |
|---|---|
| Source | `https://drive.google.com/file/d/1B9atHC74YXSZ89GcjtqVp_gJUezdxpPE` (original README, section 4) |
| Size | 1,313,438,415 bytes, the same as the server's `Content-Length` before download |
| SHA-256 | `b2109f20c26bd8150df6dfa10e650548fd92888274a99e9eb1427508a4bee391` (also stored in `datasets/download/VOCdetiv_data.rar.sha256`) |
| Integrity | `7z t`: "Everything is Ok". RAR5 with per-file CRCs; 14,138 files; 1,401,574,903 bytes unpacked |
| Location | archive: `F:\Projects\WOAD-Research\datasets\download\`; extracted: `F:\Projects\WOAD-Research\datasets\VOCdetiv_data\` (1.4 GB) |

### Structure

```
VOCdevkit_nc_{4,6,8,10}/
  images/{train,val}/*.png    IR, 640x480, 8-bit single-channel
  clouds/{train,val}/*.png    colour-mapped depth, 640x480, 8-bit 3-channel (same name as the IR image)
  labels/{train,val}/*.txt    YOLO format: class cx cy w h (normalised)
  labels/*.py, *.cache, *_not_in_nc_*   the authors' label-remapping helpers and YOLOv5 caches
```

| Variant | train imgs | val imgs | classes (from `original/.../data/stairscoco_nc_*.yaml`) |
|---|---|---|---|
| nc_4 | 601 | 177 | person, box, bike, Door closed |
| nc_6 | 834 | 244 | + Door opened, Building entrance |
| nc_8 | 916 | 262 | + Traffic signs, Down stairs |
| nc_10 | 1286 | 365 | person, box, bike, Zebra crossing, Telegraph Pole, Door opened, Door closed, Building entrance, Traffic signs, Down stairs |

nc_10 contains every image of the smaller variants (checked by MD5 of the pixel files):
**1,651 unique images** (1,598 unique filenames).

* nc_10 val instances: person 129, box 124, bike 81, zebra crossing 57, telegraph pole 86, door opened 29,
  door closed 22, building entrance 38, traffic signs 18.
* nc_10 train instances: person 458, box 472, bike 275, zebra crossing 146, telegraph pole 471,
  door opened 71, door closed 79, building entrance 162, traffic signs 82.
* The yaml lists 10 names, but labels only use ids 0–8: "Down stairs" has no instances.

Label meaning was checked visually. Class 1 "box" = cardboard boxes indoors. Class 2 "bike" =
bicycles, including shared bikes.

Data issues found:

* Every image has a depth image and a label file. No label file breaks the original
  `verify_image_label` rules, so no images were excluded.
* nc_10 has one orphan label, `labels/val/0000202019.txt`, with no image.
* In nc_10, **53 filenames exist in both train and val with different pixels** (filename reuse
  across capture sessions, not leakage of identical frames).
* Label files have no trailing newline. Concatenating them with `cat` merges lines, so count
  per file.

### Why this is not exp72's data

1. **Classes:** exp72's checkpoint names are `[person, Ebike, Car]`. The dataset has no Ebike or
   Car class, and its class 1 and 2 are box and bicycle.
2. **Frames:** all 187 reconstructed exp72 validation frames were matched against all 1,651
   dataset images (normalised 64×48 grayscale correlation). Best similarity: 0.72. The matcher
   recovers 35/40 deliberately degraded dataset frames at >0.9, and the misses are probably
   near-identical consecutive frames. **No exp72 val frame is in the archive.**
3. **Dates and paths:** the archive was modified on 2024-12-17, and its yamls point to
   `/data1/songjie/...VOCdevkit_nc_*`. exp72 is from 2023-04-05 (`/data/zhangxueyi/ljq/...VOCdevkit`).
4. The repository-root `best.pt` (5 classes: person/box/bike/chair/stairs; a different fusion
   architecture) is closer to this dataset's class set. It is incompatible with the current model
   code and was not evaluated.

Whether any of these images were in **exp72's training** set cannot be checked (that data is not
published). The low scores make substantial overlap unlikely, but it is not excluded.

## 3. Method (follows the original validation)

| Item | Original (`val.py`, `utils/datasets.py`, exp72 `opt.yaml`) | This tool |
|---|---|---|
| Inputs | `model(ir, depth)`; IR from `images/`, depth from `clouds/` with the same filename | same (`woad.pairing`, exact-name match) |
| Preprocessing | IR resize to long side 640 (INTER_AREA) + letterbox 640, `rect: false`; depth medianBlur(3) + letterbox 640; BGR→RGB; /255 | same code path (`woad.preprocess`, already mutation-tested) |
| NMS | conf 0.001, IoU 0.6, multi-label, max 300 | same (vendored original NMS) |
| Matching | `process_batch`, IoU 0.50:0.05:0.95, native coordinates | same function, verbatim |
| AP | `ap_per_class`, 101-point interpolation; P/R at max mean F1 | same; **verified equal to the original source** on random data (`tests/test_evaluate.py`) |
| Labels | `verify_image_label`: 5 columns, values in [0, 1], duplicates removed, bad file → image dropped | same rules |
| Precision | FP16 on CUDA (final validation) | **FP32 on CPU** (difference expected to be negligible, but not measured) |

Class handling: the dataset and model ids differ, so the tool takes an explicit one-to-one
`--class-map`. Ground truth of unmapped dataset classes is ignored, and detections of unmapped
model classes are discarded. Only `0:person` is semantically valid here.

Note: with this AP method a perfect detector scores **0.995**, not 1.0 (original behaviour).

## 4. Results

### Primary result: person (dataset 0 → model person)

| Split (nc_10) | Images | Person instances | P | R | AP@0.5 | AP@0.5:0.95 |
|---|---|---|---|---|---|---|
| val | 365 | 129 | 0.345 | 0.310 | **0.218** | 0.073 |
| train | 1286 | 458 | 0.361 | 0.199 | **0.173** | 0.050 |

P/R are at the max-F1 operating point (confidence 0.18 on val, 0.33 on train).

Confusion at the original plotting settings (conf 0.25, IoU 0.45), people only:

* **val:** 37 people detected, 89 missed, 5 detections with no matching person.
* **train:** 104 detected, 345 missed, 9 unmatched.

Unmatched detections are counted only in images that also contain a match (original quirk), so
false positives are under-stated.

Runtime: about 126–131 ms per image for the forward pass (batch 8, CPU). The full val run took 55 s.

### Exploratory, not a valid accuracy figure: bicycles scored as "Ebike"

| Split | bicycles | AP@0.5 |
|---|---|---|
| val | 81 | 0.001 |
| train | 275 | 0.000 |

The model essentially never labels bicycles as Ebike. That is reasonable given different
classes, and this must not be reported as Ebike accuracy.

### Qualitative error analysis (sampled frames)

* **Cyclists:** riders on bicycles in the outdoor road sequence are almost never detected as
  person.
* **Distant or small people** indoors (corridor scenes) are often missed.
* **Close, upright people** are detected with high confidence (0.74–0.87), and boxes land on them.
  The detector *does* work, but recall is low on this data.
* **Domain shift:** the dataset's IR frames are more saturated and speckled, and the scenes
  (indoor corridors with boxes, a different road) differ from exp72's outdoor campus sequences.

## 5. Interpretation and limits

* The published data allows **only a cross-dataset person measurement**. It shows the exp72 model
  does **not** generalise well to these scenes: person AP@0.5 is about 0.17–0.22 here vs 0.771
  reported on its own validation split.
* The 0.669 / 0.771 / 0.839 / 0.395 training-time figures **remain unverified**. Reproducing them
  needs exp72's actual dataset (person/Ebike/Car), which the repository does not link. Possible
  sources: the other Drive links (code bundle `1tJpmOu5…`, data-collection demo `16nxM4Gk…`), which
  have not been checked, or the authors.
* For the product, low person recall is a **safety-relevant finding**: in unfamiliar scenes the
  model misses most people. It must not be presented as reliable obstacle detection.

## 6. Other Drive links in the repository (checked 2026-11-02; nothing downloaded)

Method:

* File name, size and date come from HTTP HEAD.
* Archive contents come from each RAR5 archive's quick-open index, fetched with a few small
  HTTP Range requests (about 0.03–1.1 MB per archive).
* The method was validated: the code bundle's listing contains all 9,370 PNGs of the downloaded
  `VOCdetiv_data` with identical sizes.

| Link ID | File | Size | Date | Contents | exp72 data? |
|---|---|---|---|---|---|
| `1tJpmOu5…` | Cross Modal obstacle detection.rar | 1.70 GB (1.83 GB unpacked) | 2024-12-23 | the YOLOv5 code (several `yolo*.py`/`datasets*.py` variants), `best.pt` 16,504,077 B (≠ exp72 15,493,935 B, ≠ root `best.pt` 15,472,390 B), `yolov5s.pt`, the same `VOCdevkit_nc_{4,6,8,10}` images (**labels only as YOLOv5 `.cache` files, no `.txt`**), **`VOCdevkit_nc2`: 2-class set, 249 train + 74 val, plus `VOCdevkit_241029-nc2-hbb` (323 images)**, `data/testdata` (172 depth + 172 rgb). **No `runs/`, no exp72.** | **unlikely**: the nc2 set has 2 classes and 74 val images vs exp72's 3 classes and 187 val images; its class names are unknown |
| `1ClceTKm…` | detec_test.rar | 183 MB | 2024-05-30 | 600 `ir/` + 600 `pointcloud/` PNGs (input for `detect.py`), **no labels** | no labels |
| `16nxM4Gk…` | test1730450780.rar | 170 MB | 2024-12-17 | one CS30 capture (2024-11-01): 501 `ir/`, 501 `depth/` (colour), 501 `depthgray/` PNGs, **no labels** | no labels |
| `1wmSLaWw…` | Data collection and pre-processing.rar | 91 MB | 2024-05-31 | libsynexens3 v0.2.5 SDK binaries plus OpenCV 4.4 (no capture source code) | no |
| `1kWT_anR…` | intermediates.rar | 733 MB | 2024-05-30 | Android build intermediates (by name/location) | not inspected |
| `11F03TID…` | RL for adaptive video compression.rar | 896 MB | 2024-12-23 | RL project | not inspected |
| `1PExD1QZ…` | Hardware deployment.rar | 3.3 MB | 2024-07-14 | FPGA files | not inspected |
| `1Kava0aK…` | Smartphone deployment.zip | 643 MB | 2024-07-14 | Android app | not inspected |
| `100_sZQy…` | — | — | — | **HTTP 404** (dead link) | — |

Conclusion: **no published link contains exp72's labelled person/Ebike/Car dataset or its run
folder.** The only remaining unknown is `VOCdevkit_nc2`. Its labels exist only inside YOLOv5
`.cache` files, and its classes are unknown. Its size and class count do not match exp72's
validation set.

Useful side findings:

* `test1730450780` contains matched **colour and grey depth** frames from the CS30. That pair could
  be used to recover the SDK's depth colormap, which is roadmap risk R1 (live-input fidelity).
* `detec_test` and `test1730450780` are real, unlabelled IR+depth sequences, good for
  qualitative/demo testing in place of the degraded reconstructions.

## 7. Unlabelled sequences (downloaded 2026-11-02, qualitative only)

| | detec_test | sensor recording test1730450780 |
|---|---|---|
| Archive | `datasets/download/detec_test.rar`, 182,665,941 B, SHA-256 `53cd2d29…febfd`, `7z t` OK | `datasets/download/test1730450780.rar`, 170,477,746 B, SHA-256 `c7fa0222…66c7`, `7z t` OK |
| Extracted | `datasets/detec_test/detec_test/` (189 MB) | `datasets/test1730450780/test1730450780/` (180 MB) |
| Content | 600 IR (`ir/`, 8-bit grey) + 600 colour depth (`pointcloud/`), same filenames; `depth/` empty | 501 frames each of `ir/ir{i}.png`, `depth/depth_{i}_num{k}.png` (colour), `depthgray/depthgray{i}.png`; other folders empty. Meaning of `num{k}` unknown |
| Pairing | by filename (as `woad_detect.py --ir-dir/--depth-dir`) | by index i. Verified: depthgray{i} and depth_{i} have identical invalid-pixel masks. Hard-linked pairs in `datasets/test1730450780_paired/{ir,depth}/{i:04d}.png` |
| Overlap | none with the labelled dataset (0/600 identical; 16 filenames coincide with different pixels); none with exp72 val (best similarity 0.72) | — |
| IR brightness (mean / std) | 135 / 71, like the training-type data (labelled set 142 / 61, exp72 val 137 / 68) | **59 / 22: much darker, out of the training distribution** |
| `woad_detect.py` (conf 0.25) | 313/600 frames with detections: person 271, Ebike 160, Car 52 (`outputs/detec_test`) | 3/501 frames, all "person" at 0.26–0.33 at the same left-edge door position; the two inspected are false alarms (`outputs/sensor_recording_1730450780`) |

Observations (no labels, so these are not accuracy figures):

* **detec_test:**
  * Mostly plausible detections: people at 0.57–0.94, and cyclists boxed as "Ebike".
  * Visible errors: a missed, clearly visible walking person (`0000000103.png`), and "Car" on
    roadside shrubs (0.68).
  * The model boxes rider + bicycle as one "Ebike". That box-extent mismatch, not only the class,
    explains the near-zero exploratory bike→Ebike AP in section 4.
* **Sensor recording:**
  * The recording contains only one person: small and distant, in about frames 94–106. The
    detector misses it in every frame, and its 3 detections are false alarms. Too few people
    appear to measure recall; see section 8.
  * The IR exposure/brightness differs strongly from all training-type data, so the training
    images must have been captured with different settings or post-processed.
  * **This is a direct risk for live input (roadmap R1):** the sensor's raw `ir` output may not
    match what the model expects.
* **Depth colormap:**
  * The SDK colour depth is close to, but not exactly, OpenCV JET applied to `depthgray`
    (mean per-channel difference 28).
  * A grey level maps to one colour for only 24 % of pixels, so the colour is probably computed
    from the raw 16-bit depth, which this recording did not save.
  * Exact recovery needs raw depth (CS30 hardware) or the SDK's `sy3_get_colormap_table`.

## 8. IR brightness experiment (2026-11-02)

Script: `experiments/ir_brightness_test.py`. Results: `outputs/experiments/ir_brightness/`
(`results.json`, and `frames/` with every frame that had a detection under any transform).

Only the IR stream is transformed; depth is unchanged. The transforms are: raw; linear gain to the
reference mean; per-frame percentile stretch; histogram matching to the pooled `detec_test` IR
histogram; gamma 0.5.

**Part B: controlled test.**

* Setup: 200 `detec_test` frames were darkened by histogram-matching them to the recording's IR
  distribution. Reference = the 164 detections on the original frames (same class, IoU ≥ 0.5).
* Caveat: histogram matching back partly inverts this synthetic darkening, so its recovery figure
  is optimistic.

| | dark (raw) | + gain | + stretch | + histmatch | + gamma |
|---|---|---|---|---|---|
| reference detections recovered | 27 % | 54 % | 18 % | 87 % | 28 % |
| extra detections | 16 | 24 | 20 | 24 | 30 |

**Part A: the real recording (501 frames).**

* Ground truth was established by eye: one person, small and distant, visible in about frames
  94–106. No other people were found.

| | raw | gain | stretch | histmatch | gamma |
|---|---|---|---|---|---|
| IR mean / std | 60 / 22 | 131 / 44 | 53 / 56 | 142 / 66 | 117 / 22 |
| detections (all "person") | 3 | 4 | 2 | 57 | 0 |
| correct (the real person) | 0 | 0 | 0 | **1** (frame 95, conf 0.68) | 0 |
| false alarms | 3 | 4 | 2 | **56**: bright door leaves/frames, conf up to 0.78 | 0 |

Conclusions:

1. **The model is highly sensitive to IR brightness.** Darkening training-like frames to the
   recording's level removes about 73 % of detections.
2. **Brightness correction does not fix the real recording.** The best transform finds the only
   real person in 1 of about 13 frames, and adds 56 false "person" alarms on bright doors.
   Precision is about 2 % in this scene.
3. Other differences therefore remain, for example capture settings/exposure,
   noise characteristics, depth colouring, and indoor door-heavy scenes. Brightness is a
   **necessary but not sufficient** correction. **No transform is adopted** in the pipeline.
4. For live use: frames must be checked against the training IR statistics (warn or refuse if out of
   range), and **the CS30 capture settings that produced the training data must be found**. A
   post-hoc histogram fix is not safe.

## Reproduce

```bat
cd F:\Projects\WOAD-Research\implementation
set N=person,box,bike,Zebra crossing,Telegraph Pole,Door opened,Door closed,Building entrance,Traffic signs,Down stairs
..\.venv\Scripts\python tools\evaluate.py --split-root ..\datasets\VOCdetiv_data\VOCdevkit_nc_10 --split val   --class-map 0:person --dataset-names "%N%" --name nc10_val_person
..\.venv\Scripts\python tools\evaluate.py --split-root ..\datasets\VOCdetiv_data\VOCdevkit_nc_10 --split train --class-map 0:person --dataset-names "%N%" --name nc10_train_person
```
