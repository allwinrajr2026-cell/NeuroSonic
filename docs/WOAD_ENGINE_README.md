# WOAD — Cross-Modal Obstacle Detection (inference engine)

Standalone, tested inference for the WOAD cross-modal obstacle detector
(*"WOAD: A Wearable Obstacle Avoidance Device for Visually Impaired Individuals with Cross-Modal
Learning"*). It runs the trained **exp72** checkpoint on paired **near-infrared (IR)** and
**colour-mapped depth** images and detects **person, Ebike, Car**.

The original research code lives untouched in `../original/`. This folder is a clean,
self-contained re-implementation of the *inference path only*. The model math is vendored verbatim
and verified bit-exact against the original code.

## NeuroSonic app (integrated prototype)

**NeuroSonic** is the product built on this engine: a **voice-first, offline-capable assistive navigation
prototype**. It's a mobile-first web app with:

* a local neural voice (Piper, Indian English) and **offline voice commands** (Vosk; push-to-talk);
* **online scene description** (Sprint 1, opt-in): one camera photo on request goes from the laptop to a cloud vision
  model (Gemini, replaceable) and the answer is spoken; not yet confirmed with a successful live request
  ([`docs/ONLINE_VISION.md`](docs/ONLINE_VISION.md));
* **RF-DETR Nano on the laptop's NVIDIA GPU** (run from `..\.venv-gpu`; automatic fallback to SSDLite on the CPU),
  ByteTrack-style tracking with camera-motion compensation and spoken **events** ("A person is moving into your path
  from the left", "A bicycle is crossing in front of you"): see
  [`docs/NEUROSONIC_FINAL_TECHNICAL_DOCUMENTATION.md`](docs/NEUROSONIC_FINAL_TECHNICAL_DOCUMENTATION.md);
* **Walking Guidance** from the phone camera: a general COCO detector (not WOAD; no distances) plus a walking-path
  assessment that speaks only path changes (clear / caution / stop / cannot assess / camera unavailable), with an
  optional **Object Description** mode and chest/handheld wording;
* an offline Vellore map with place search and walking routes with spoken turn-by-turn guidance;
* WOAD replay detection with alerts;
* browser GPS with fix-quality and signal-loss handling, local SQLite history, an optional webcam event-camera
  simulation, and a compact iPhone interface with a **How it works** screen.

The phone is a thin client: detection, speech recognition, the neural voice and routing run on the laptop over
the local Wi-Fi. The local guidance needs no internet; only online scene description does. The app is **not**
standalone on the iPhone.

```bat
..\.venv-gpu\Scripts\python neurosonic_app.py --host 0.0.0.0 --https   :: recommended: RF-DETR on the GPU, phone on the same Wi-Fi
..\.venv\Scripts\python neurosonic_app.py                    :: CPU only (SSDLite fallback), http://127.0.0.1:8765
..\.venv\Scripts\python neurosonic_app.py --host 0.0.0.0 --https   :: CPU only, phone on the same Wi-Fi
```

* Background start / stop (keeps running after the terminal closes): `powershell -ExecutionPolicy Bypass -File
  .\START_NEUROSONIC.ps1` (add `-Cpu` for CPU only) and `.\STOP_NEUROSONIC.ps1`. Both are described in
  `PROJECT_DOCUMENTATION/HANDOFF_STATUS.md` §4.
* Current state and what still needs the iPhone: [`PROJECT_DOCUMENTATION/HANDOFF_STATUS.md`](PROJECT_DOCUMENTATION/HANDOFF_STATUS.md).
* Publication package (manuscript, slides, test report, installation and user guides, figures): [`publication/`](publication/).
* iPhone / field validation protocol: [`docs/IPHONE_VALIDATION_PROTOCOL.md`](docs/IPHONE_VALIDATION_PROTOCOL.md).
* What works, and the evidence for it: [`docs/FEATURE_STATUS.md`](docs/FEATURE_STATUS.md).
* App guide and phone setup: [`docs/NEUROSONIC_APP.md`](docs/NEUROSONIC_APP.md).
* Tests a person must do on the iPhone and outdoors: [`docs/MANUAL_TESTING.md`](docs/MANUAL_TESTING.md).
* Walking guidance, GPS and interface refinement: [`PROJECT_DOCUMENTATION/17_PRODUCT_REFINEMENT.md`](PROJECT_DOCUMENTATION/17_PRODUCT_REFINEMENT.md).
* Direction and priorities: [`docs/ARCHITECTURE_AND_ROADMAP.md`](docs/ARCHITECTURE_AND_ROADMAP.md).
* Voice model: [`models/tts/README.md`](models/tts/README.md). Map data: [`maps/vellore/README.md`](maps/vellore/README.md).

Assistive research prototype: not a replacement for a cane, guide dog or human assistance.

---

## Quick start

```bat
cd F:\Projects\WOAD-Research\implementation
..\.venv\Scripts\activate
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu   :: already satisfied in ..\.venv

:: run on the demo set: 600 real IR + depth pairs (about 75 s on CPU)
python woad_detect.py --source demo_data/detec_test

:: run the test suite (204 tests incl. app API, phone access, voice, offline map, walking guidance, online-vision mock + browser logic, about 1.5 min on CPU)
python -m unittest discover -s tests -t . -v
```

### Demo data

| Folder | What | Use for |
|---|---|---|
| `demo_data/detec_test/` | **Primary demo.** 600 real, unlabelled IR + colour-depth pairs published by the authors (`detec_test.rar`); indoor and outdoor scenes, with brightness matching the training data | trying the detector, demos, visual checks. Expected output and known errors are listed in its README |
| `demo_data/reconstructed_val/` | 187 frames rebuilt (degraded) from exp72's validation plots | regression-test fixtures (golden detections). Not for demos or accuracy |

Neither folder has labels. Measured accuracy is in `docs/EVALUATION.md`.

## Usage

```
python woad_detect.py (--ir FILE --depth FILE | --ir-dir DIR --depth-dir DIR | --source DIR) [options]
```

| Option | Default | Meaning |
|---|---|---|
| `--source DIR` | | folder with `ir/` and `depth/` sub-folders (original `LoadImages` layout) |
| `--ir-dir`, `--depth-dir` | | two folders, paired by filename |
| `--ir`, `--depth` | | a single pair |
| `--match name\|stem` | `name` | pair by exact filename (as in training) or by stem (allows `.jpg`↔`.png`) |
| `--skip-unpaired` | off | otherwise unpaired files abort the run with a list of the offenders |
| `--conf`, `--iou` | 0.25, 0.45 | confidence / NMS IoU thresholds (training-plot defaults) |
| `--classes` | all | e.g. `--classes person Ebike` or ids |
| `--device` | `cpu` | `cpu`, `cuda`, `0`, `auto` (installed torch is a CPU build) |
| `--project`, `--name` | `outputs/`, `detect` | run folder; auto-increments (`detect2`, …), **never overwrites** |
| `--no-images` | off | only write JSON |

Output (`outputs/<name>/`):

```
annotated/<stem>.jpg   IR | depth side by side, boxes drawn on both
json/<stem>.json       {"ir_path", "depth_path", "image_size", "depth_size", "size_mismatch",
                        "detections": [{"class_id","class_name","confidence","box_xyxy"}], "timing_ms"}
results.json           model hash, settings, library versions, summary, failures, all results
```

Boxes are `[x1, y1, x2, y2]` in **original IR pixel coordinates**. Exit codes: `0` ok, `1` all
pairs failed to load, `2` usage/pairing/checkpoint error.

Python API:

```python
from woad.detector import WOADDetector
det = WOADDetector(conf_thres=0.25)
result, _ = det.detect_files("ir/0001.png", "depth/0001.png")
result = det.detect_arrays(ir_bgr, depth_bgr)       # uint8 HxWx3 OpenCV images
```

### Replay with alerts (Stage 2, text only)

```bat
python woad_replay.py --source demo_data/detec_test --segment-gap 10
```

This replays frames as a timed stream (synthetic timestamps, deterministic). Each frame goes
through an input-quality check, the detector and the alert engine. Output is written to
`outputs/replay*/transcript.txt`, with lines like `[74.8s #374 0000060711.png] 2 people detected ahead.`

Alert rules, thresholds, results and limitations are in
[`docs/STAGE2_ALERTS.md`](docs/STAGE2_ALERTS.md). "Ahead" means the middle of the camera view, not a
distance. No speech yet (Stage 4).

## Input requirements (important)

| Stream | Expected input | Notes |
|---|---|---|
| IR | the sensor's near-infrared frame (Synexens CS30), 8-bit, typically 640×480 | stored as a 3-channel gray image; single-channel files are expanded automatically |
| depth | the **colour-mapped (jet-like) depth PNG** produced by the capture pipeline, 8-bit, 3-channel | raw 16-bit depth or a single-channel depth map is **rejected**: it is out of distribution |

The model was trained at 640×640 only. The depth branch was letterboxed to a hard-coded 640 in
training, so `img_size` is fixed. The IR and depth images should share a resolution. If they
don't, inference still runs, boxes refer to the IR frame, and the run reports `size_mismatch`.

## Preprocessing (reproduced from the original `utils/datasets.py`, validation path)

1. **IR:** `cv2.imread` (BGR) → if the long side ≠ 640, resize by `640/max(h,w)` (INTER_AREA to
   shrink, INTER_LINEAR to enlarge) → `letterbox(640, auto=False, scaleup=False)`, pad 114.
2. **Depth:** `cv2.imread` (BGR) → `cv2.medianBlur(3)` → `letterbox(640, auto=False)`, pad 114.
3. Both: HWC→CHW, BGR→RGB, `/255` → float32 `(1,3,640,640)`.
4. `model(ir, depth)` → original YOLOv5 `non_max_suppression` → `scale_coords` back to the IR frame.

## Architecture (exp72)

```
IR    ─ YOLOv5s layers 0-2 (Conv,Conv,C3) ─┐  (B,64,160,160)
depth ─ separate Conv,Conv,C3 stem ────────┤  (B,64,160,160)
                                           ▼
        fixed 0.5/0.5 gate → 8×8 avg-pool tokens (2×64) + pos-emb
        → 8 × transformer block (d=64, 8 heads) → split, upsample
        → per-stream (conv4→bn3→ReLU)×2 × attention map → concat → conv3→bn3→ReLU
                                           ▼
        YOLOv5s layers 3-24 (backbone, PAN head) → Detect P3/P4/P5, 3 classes
```

7,521,992 parameters; output `(B, 25200, 8)` at 640×640. Checkpoint metadata: saved 2023-04-05,
optimizer stripped, `names = [person, Ebike, Car]`.

## Repository layout

```
weights/best.pt              copy of original runs/train/exp72/weights/best.pt
                             SHA-256 da043ff2…f8aa (verified at every load)
woad/arch/{common,yolo}.py   vendored model classes (only the 9 the checkpoint pickles)
woad/ops.py                  letterbox, original NMS, scale_coords (verbatim)
woad/model_loader.py         hash + architecture checks, legacy-module aliasing, device selection
woad/preprocess.py           training-faithful preprocessing + input validation
woad/pairing.py              filename pairing with clear errors
woad/detector.py             WOADDetector API
woad/visualize.py            drawing
woad/sources.py              ReplaySource (Frame stream; live sources will share the interface)
woad/quality.py              input-quality check (IR brightness/contrast, depth validity)
woad/alerts.py               alert engine (confirmation, position, cooldowns, availability)
woad/replay.py               replay pipeline
woad/metrics.py              original process_batch / ap_per_class / confusion matrix (verified equal)
woad_detect.py               CLI (detection)
woad_replay.py               CLI (replay + alert transcript)
neurosonic_app.py            NeuroSonic app server (docs/NEUROSONIC_APP.md)
neurosonic/                  server.py (HTTP API), service.py (WOAD replay/upload), store.py (SQLite), tts.py (Piper voice),
                             maps.py (offline search + routing), tls.py + netcheck.py (phone HTTPS)
models/tts/en_IN-spicor/     Piper Indian-English voice (AGPL-3.0, see models/tts/README.md)
maps/vellore/                offline OSM map package (ODbL, see maps/vellore/README.md)
tools/build_offline_map.py   builds maps/<region> from raw Overpass downloads in ../datasets/osm/
web/                         mobile-first UI: index.html, style.css, js/{app,speech,nav,mapview,eventsim}.js
data/                        created at runtime: SQLite history, self-signed TLS key (keep private)
tools/verify_equivalence.py  bit-exact check vs. the original repository code
tools/reconstruct_val_samples.py   builds demo_data/reconstructed_val from the saved validation mosaics
tools/prepare_detec_test_demo.py   copies detec_test into demo_data/detec_test (verified, never overwrites)
experiments/ir_brightness_test.py  IR brightness experiment (docs/EVALUATION.md section 8)
tools/evaluate.py            mAP evaluation on a labelled IR+depth dataset (docs/EVALUATION.md)
tools/make_golden.py         regenerates tests/golden_detections.json (only after a reviewed change)
demo_data/detec_test/        PRIMARY DEMO: 600 real unlabelled pairs + manifest.json (read its README)
demo_data/reconstructed_val/ 187 reconstructed, DEGRADED pairs = regression-test fixtures (read its README)
tests/                       unittest suite
outputs/                     run folders (outputs/recon_val_full = full demo-set run, outputs/eval = evaluations)
docs/                        FEATURE_STATUS.md, ARCHITECTURE_AND_ROADMAP.md, NEUROSONIC_APP.md, EVALUATION.md, STAGE2_ALERTS.md
```

## Verification evidence

| Claim | How it was verified | Result |
|---|---|---|
| Checkpoint is exp72 and unmodified | SHA-256 of copy and original | identical (`da043ff2…`) |
| Vendored model == original code | `tools/verify_equivalence.py`: original `models/yolo.py` run in a subprocess on the same seeded 2×640×640 inputs | max abs. difference **0.0** |
| Input order is `(ir, depth)` | 32 frames: swapping the streams | confidence mass drops to **8 %** |
| Both modalities are used | blank IR / blank depth | IR blank → **0 %**, depth blank → **65 %** (IR dominant, depth contributes) |
| Detections are meaningful | batch 0 vs. predictions saved during training on the raw frames (`val_lidar batch0_pred.jpg`) | **13 / 16** frames agree in class and location (see below) |
| Box mapping | same scene at 640×480 and 1280×960 | boxes scale ×2 (IoU ≥ 0.85) |
| Tests detect real bugs | mutation runs: no median blur / no BGR→RGB / swapped inputs | each mutation fails ≥ 2 tests |

Batch-0 disagreements: frame index 0 (person, training conf 0.9) scores only 0.15 after overlay
removal; index 1 (training: one Ebike at 0.3) falls just under 0.25; index 11 gains an Ebike that
matches a ground-truth box the training plot didn't show.

Caveat found during verification: on frame index 0, the burned-in ground-truth box *raised* the
person score from 0.15 to 0.85. Raw mosaic tiles therefore leak labels, and all tests use the
cleaned reconstructions. Over the whole set the cleaned frames give more detections than the raw
tiles (284 vs 246), so cleaning does not inflate results.

**Accuracy:** see [`docs/EVALUATION.md`](docs/EVALUATION.md). Keep these three apart:

| Source | person | Ebike | Car | Status |
|---|---|---|---|---|
| Training plots (exp72's own val split, `runs/train/exp72/PR_curve.png`) | 0.771 | 0.839 | 0.395 | reported, **not reproducible**: that data is not published |
| Reconstructed demo frames | — | — | — | sanity check only, no labels |
| **Published dataset `VOCdetiv_data` (nc_10), measured here**, AP@0.5 | **0.218** (val, 129 people) / **0.173** (train, 458) | no labels | no labels | genuine, but **cross-dataset**: different scenes and classes |

The published dataset has classes person/box/bike/…, none of exp72's 187 validation frames, and no
Ebike or Car labels. The training-time mAP@0.5 = 0.669 therefore remains unverified. On the
published data the model is precise but misses most people (val recall 0.31).

Performance: about 100 ms per pair for the forward pass on this laptop CPU (batch 1, default torch
threading). The 187-pair run takes 24 s end-to-end including I/O and drawing.

## Original dataset

From `../original/README.md`, section 4 "Data availability":
`https://drive.google.com/file/d/1B9atHC74YXSZ89GcjtqVp_gJUezdxpPE/view` →
**`VOCdetiv_data.rar`**. Verified on 2026-11-02 without downloading the archive: an HTTP HEAD
request returns `Content-Length: 1313438415` (1.22 GiB) and `Last-Modified: 2024-12-17`. The
first 64 bytes carry a RAR5 signature, and the first entry's path begins `VOCdevkit_n…`. Google
publishes no checksum, so integrity is checked with RAR's internal CRCs (`7z t`). The training
YAMLs expect a `VOCdevkit/{images,clouds}/{train,val}/` layout with YOLO labels. 7-Zip is
installed at `C:\Program Files\7-Zip\7z.exe`. The full code bundle is a separate
`Cross Modal obstacle detection.rar` (`1tJpmOu5…`).

**Downloaded 2026-11-02:**

* Archive: `..\datasets\download\VOCdetiv_data.rar`, SHA-256 `b2109f20…e391`; `7z t` passes.
* Extracted to `..\datasets\VOCdetiv_data\`: variants `VOCdevkit_nc_{4,6,8,10}`, 1,651 unique
  images.
* It is **not exp72's dataset**; details in `docs/EVALUATION.md`.

Evaluate with:

```bat
python tools\evaluate.py --split-root ..\datasets\VOCdetiv_data\VOCdevkit_nc_10 --split val --class-map 0:person
```

`--class-map DATASET_ID:MODEL_CLASS` is required because dataset and model class ids differ.

## Product roadmap

The full product requirements (voice, navigation, laptop dashboard, Android, offline-first,
safety) and their feasibility with this model are in
[`docs/ARCHITECTURE_AND_ROADMAP.md`](docs/ARCHITECTURE_AND_ROADMAP.md).

## Known limitations

* Inference and evaluation only. Training still requires the original scripts, which are broken
  (single-input calls, `np.int`, `torch.load` defaults, missing `clouddir` argument in `val.py`).
* exp72's own dataset (person/Ebike/Car) is not available, so Ebike and Car accuracy cannot be
  measured.
* Low person recall on the published dataset (cyclists and distant people are missed).
* Only the exp72 architecture is supported. The repository-root `best.pt` is a different 5-class
  fusion variant and is rejected with a clear error.
* `torch.load(weights_only=False)` is required by the YOLOv5 checkpoint format, so only load
  trusted checkpoints.
* GPU inference is untested: the installed torch is a CPU build.
