# Phase 1: GPU enablement and controlled detector benchmark (2026-11-03)

* **Production is unchanged.**
  * Detector: SSDLite320 in `neurosonic/awareness.py`.
  * Frontend: unchanged.
  * Production environment `F:\Projects\WOAD-Research\.venv`: its package list is identical to the backup in
    `backups/20261103-000843-env-before-gpu-phase1/` (`pip freeze` diff is empty).
* **The original WOAD repository and the datasets were not modified.**
* **Raw results:** `outputs/benchmarks/phase1/results.json`. **Tool:** `tools/benchmark_detectors.py`.

## 1. Environment inspection

| Item | Finding |
|---|---|
| GPU | NVIDIA GeForce RTX 4050 Laptop GPU, 6141 MiB, compute capability 8.9, WDDM; driver 592.82 (reports CUDA 13.1) |
| CPU / RAM | AMD Ryzen 7 7840HS (8 cores / 16 threads), 15.3 GB |
| Production venv | Python 3.12.10, `torch 2.15.0+cpu`, `torchvision 0.29.2`, `onnxruntime 1.31.1` (CPU only); 1.2 GB |
| Available CUDA builds for torch 2.15.0 (cp312, Windows) | `+cu132`, `+cu134` on download.pytorch.org; torchvision 0.29.2 has no CUDA build, so the newest CUDA build of the same series, **0.29.1+cu132**, was used |
| Pre-install download calculation (dry-run resolution + HTTP HEAD) | 89 packages, **2.43 GB** (torch cu132 2108 MB); the only version differences from production were torch and torchvision; 30 additional packages for the benchmark (rfdetr, ultralytics, transformers, …) |
| Disk before | F: 88.8 GB free |

## 2. What was installed (separate environment, production untouched)

* **New environment:** `F:\Projects\WOAD-Research\.venv-gpu`.
  * `torch 2.15.0+cu132`, `torchvision 0.29.1+cu132`;
  * all production packages at the **same versions**;
  * plus `rfdetr 1.11.2` (Apache-2.0) and `ultralytics 8.4.198` (**AGPL-3.0**, used here for benchmarking only);
  * installed with `--no-cache-dir`, so there is no second copy of the 2 GB wheel;
  * **4.2 GB on disk**.
* **Verification:** CUDA is available, CUDA runtime 13.2 and cuDNN 9.26.0 run on the 13.1-reporting driver, and a GPU
  matrix multiplication and torchvision GPU operations worked.
* **Model weights (only what the comparison needed):**
  * YOLO26n, 5.5 MB, and YOLO26s, 20.4 MB, in `models/benchmark/`;
  * RF-DETR Nano, 366 MB, saved by the rfdetr package to **`C:\Users\Allwin\.roboflow\models\rf-detr-nano.pth`**
    (outside the project).
  * RF-DETR Small (386 MB) was **not** downloaded.
  * Hugging Face downloads were blocked during the run (`HF_HUB_OFFLINE=1`); no backbone was fetched.
  * Ultralytics usage-data sync was switched off.

## 3. Method (identical for every detector)

* **Quality.**
  * Data: the published WOAD dataset `VOCdevkit_nc_10`, val split, 365 **near-infrared** images with **129 labelled
    people**.
  * Metric: person AP@0.5 and AP@0.5:0.95 with the project's own metric code (`woad.metrics.ap_per_class`, as
    `tools/evaluate.py` uses). Confidence ≥ 0.001, at most 300 detections, plus precision and recall at the
    production threshold 0.40.
* **Speed.**
  * Data: the first frames of the recorded `detec_test` sequence (640 × 480), 200 timed frames on the GPU and 60 on
    the CPU, after 10 warm-up frames.
  * Latency covers preprocessing, inference and postprocessing of an in-memory frame. Disk reads are excluded. The
    GPU is synchronised for each frame.
  * CPU use via `psutil`. GPU memory as the PyTorch allocator peak, plus `nvidia-smi` (528 MiB were already used by
    other processes before the run).
  * FP32, batch 1, each model at its package's default input size: SSDLite 320 (internal), RF-DETR-N 384,
    YOLO26 640. No TensorRT, FP16 or model optimisation was used, so these are comparable but not each model's best
    case.
* **Qualitative:** `test_street.jpg`, a real Vellore street in colour, with detections ≥ 0.40.

## 4. Results

### Speed

| Detector | Device | Mean latency | Median | p90 | FPS | CPU (% of all cores) | GPU memory (allocator peak) | Load |
|---|---|---|---|---|---|---|---|---|
| SSDLite320 (production) | CPU | 43.7 ms | 43.7 | 47.3 | 22.9 | 50 % | — | 0.2 s |
| SSDLite320 (production) | GPU | 42.3 ms | 41.5 | 47.3 | 23.6 | 48 % | 58 MiB | 0.2 s |
| RF-DETR Nano | CPU | 121.9 ms | 121.0 | 130.1 | 8.2 | 49 % | — | 6.7 s |
| RF-DETR Nano | GPU | 21.3 ms | 20.6 | 25.7 | 47.0 | 48 % | 144 MiB | 2.7 s |
| YOLO26n | CPU | 27.8 ms | 27.7 | 30.3 | 35.9 | 49 % | — | (first-use download) |
| YOLO26n | GPU | **12.4 ms** | 11.8 | 15.8 | **80.6** | **6 %** | 52 MiB | < 0.1 s |
| YOLO26s | CPU | 57.5 ms | 57.2 | 59.8 | 17.4 | 50 % | — | (first-use download) |
| YOLO26s | GPU | **11.8 ms** | 11.4 | 14.0 | **85.0** | **6 %** | 96 MiB | < 0.1 s |

The highest total GPU memory seen by `nvidia-smi` during any run was 805 MiB, of which 528 MiB was already in use.
Every model needs **well under 0.5 GB** of the 6 GB, including the CUDA context.

### Detection quality: people, 365 near-IR validation images (129 people)

| Detector | Person AP@0.5 | Person AP@0.5:0.95 | Precision @ 0.40 | Recall @ 0.40 |
|---|---|---|---|---|
| SSDLite320 (production) | 0.542 | 0.208 | 0.607 | 0.574 |
| RF-DETR Nano | **0.660** | **0.304** | 0.588 | **0.729** |
| YOLO26n | 0.619 | 0.268 | **0.633** | 0.628 |
| YOLO26s | 0.628 | 0.292 | 0.600 | 0.651 |

### Qualitative: `test_street.jpg` (detections ≥ 0.40)

| Detector | Detections |
|---|---|
| SSDLite320 | none |
| RF-DETR Nano | motorcycle 0.71 and person 0.66 (the rider), motorcycle 0.45 (the second rider) |
| YOLO26n | person 0.60 (the second rider) |
| YOLO26s | motorcycle 0.47, person 0.44 |

## 5. Interpretation

1. **The GPU works and is barely used.** The candidates need < 150 MiB of GPU memory and 12–21 ms per frame. That
   leaves large headroom for the later depth and segmentation stages.
2. **SSDLite gains nothing from the GPU** (43.7 → 42.3 ms). The time goes into torchvision's SSD post-processing
   and data handling, not into the network. Moving the current detector to the GPU alone is not worthwhile.
3. **YOLO26n is better than the production detector even on the CPU.** It was faster (27.8 vs 43.7 ms) and more
   accurate on people (AP@0.5 0.619 vs 0.542). On the GPU it runs at about 80 fps using only 6 % CPU, which leaves
   the CPU free for Piper, Vosk and the web server. YOLO26s is just as fast on the GPU and slightly more accurate.
   **Licence:** AGPL-3.0, with source-release obligations for a network service.
4. **RF-DETR Nano is the most accurate** (AP@0.5 0.660, AP@0.5:0.95 0.304, recall 0.73 vs 0.57) and **Apache-2.0**.
   Unoptimised FP32 runs at 47 fps on the GPU, which is well above the app's need. However:
   * it uses about half the CPU even on the GPU (preprocessing and postprocessing on the CPU);
   * it is too slow as a CPU fallback (122 ms);
   * the package warns that FP16 / optimised inference would be faster. That was not tested.
5. **The 2.5 fps limit of the app is not the detector.** It comes from the phone's 400 ms frame interval and one
   request at a time. Any of the GPU candidates could serve 10 fps or more. That change is not made yet; it belongs
   to the frontend phase.

## 6. Limitations of this benchmark (read before deciding)

* **The quality data is near-infrared**, not phone colour photos, and only **129 people** in one dataset. Differences
  of a few AP points are within the uncertainty. Only the person class could be scored. There is **no labelled
  colour or Vellore street data**, and the street result is one image, so it is anecdotal.
* **Speed excludes JPEG decoding, the network and the phone.** It is the laptop's per-frame compute only. Laptop power
  state and thermal behaviour over long runs were not controlled.
* **All models were run FP32 without optimisation.** RF-DETR in particular could be faster with its own optimised
  inference mode, which is untested.
* **The person AP here is not comparable to the WOAD figures** (0.218 / 0.173 in `docs/EVALUATION.md`). The metric code
  is the same, but WOAD uses IR + depth pairs, different preprocessing and its own classes.
* **Nothing here shows that NeuroSonic is safe for real-world navigation.** Better benchmark numbers mean fewer
  missed people in this test set, not safe walking.

## 7. Tests after the environment change

| Suite | Production `.venv` | `.venv-gpu` |
|---|---|---|
| Python `unittest discover -s tests -t .` | **182 tests OK** (1 skipped: opt-in live cloud test) | **182 tests OK** (1 skipped) |
| Browser: ui_vision, ui_smoke, ui_voice_map, ui_refine, ui_final, ui_vision_slow | production venv unchanged (last full pass 2026-11-02) | **all 6 PASS** against a server started from `.venv-gpu` |

## 8. Options for the next decision (no change made)

| Option | For | Against |
|---|---|---|
| **A. RF-DETR Nano on the GPU, SSDLite kept as the CPU fallback** | most accurate; Apache-2.0; 47 fps | ≈ 50 % CPU while running; slow on CPU; 366 MB weights outside the project folder |
| **B. YOLO26n (or 26s) on the GPU and CPU** | fastest; better than SSDLite even on CPU; 6 % CPU on GPU; built-in trackers for Phase 2 | **AGPL-3.0** obligations |
| C. Measure more first (no change) | RF-DETR optimised/FP16 inference (no download); optionally RF-DETR Small (386 MB); recorded colour phone frames for quality (needs a consented recording) | delays the decision |

Switching the app to the GPU would mean running it from `.venv-gpu`, or installing the CUDA build into the production
venv. Either needs approval.
