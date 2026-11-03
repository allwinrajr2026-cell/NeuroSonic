# NeuroSonic: Faculty Demonstration Guide

**Workspace:** open `F:\Projects\WOAD-Research\NeuroSonic_Faculty_Demo.code-workspace` in Visual Studio Code.
**Demo commands:** Terminal → Run Task… → "Demo 1" … "Demo 10".
**Navigation:** `Ctrl+P` and a file name jumps to any file. `Ctrl+G` and a line number jumps to a line.

> NeuroSonic is a research prototype, not a safety device. It gives no distances and has no 360-degree vision.
> Physical iPhone and field tests are still pending.

## Faculty question → what to open

| Question | Open this | What to point at |
|---|---|---|
| **Show me your development environment** | Explorer: the roots are numbered 1–9 by topic. Main root: `NeuroSonic (implementation)` | Python 3.12.10; two virtual environments: `F:\Projects\WOAD-Research\.venv` (CPU, production) and `.venv-gpu` (CUDA). The workspace interpreter is `.venv-gpu` |
| **How you configured Python** | `requirements.txt` | Pinned versions; CPU vs GPU install notes. Run task **Demo 1** and **Demo 2** |
| **Show me your backend** | `neurosonic_app.py` (entry point: `main()` at line 28, command-line options at lines 30–53) | Then `neurosonic/server.py` lines 392–402: the table of all GET/POST API routes |
| | `neurosonic/awareness.py` | `process_frame()` line 205 (one camera frame end to end); `_detect_on_worker()` line 159 (single inference thread); `FRAME_MS_GPU, FRAME_MS_CPU = 200, 400` at line 58 |
| | `neurosonic/pathguide.py`, `events.py`, `tracking.py` | Walking-path states; entering/crossing events; ByteTrack-style tracker plus camera-motion estimate (`estimate_camera_motion`, line 41) |
| | `maps.py`, `tts.py`, `voicecmd.py`, `store.py`, `tls.py`, `vision/gemini.py`, `vision/assistant.py` | A* routing; Piper voice; Vosk commands; SQLite text history; local certificate authority; optional Gemini with timeout rules |
| **Show me your frontend** | `web/index.html`, `web/style.css` | Screens: Home, Navigate, Speak, History, Settings, How it works |
| | `web/js/app.js` | `startAwareness()` line 541; `awarenessStep()` line 580, which sends each camera frame (`fetch` at line 599) |
| | `web/js/speech.js` | Priority speech queue; neural voice fetched from `/api/tts` (line 218) |
| | `web/js/nav.js`, `mapview.js`, `recorder.js`, `eventsim.js` | Route following; map drawing; push-to-talk recording; webcam event simulation (research tool) |
| **Explain your AI engine** | `neurosonic/detectors.py` | `RFDETRDetector` line 87 (RF-DETR Nano on CUDA); FP16 at lines 107–113; `SSDLiteDetector` line 51 (CPU fallback); `FallbackDetector` line 125; `make_detector()` line 161 (warm-up, then automatic fallback) |
| | Base paper: `woad/arch/yolo.py`, `woad/model_loader.py`, `woad/preprocess.py`, `woad/detector.py`, `woad/alerts.py`, `woad/quality.py` | WOAD IR + depth fusion model (re-implemented, identical output to the original); quality gate; alert engine |
| **Which ML framework?** | `requirements.txt`, task **Demo 2** | **PyTorch** (torch 2.15.0, CUDA 13.2 build in `.venv-gpu`), torchvision, `rfdetr` 1.11.2, ONNX Runtime (Piper voice only), Vosk (speech recognition). **TensorFlow is not used**: it is not installed in either environment, and no project code imports it |
| **Show me your trained models** | Explorer root **5 Trained models** plus the README files open in tabs | See the model table below. Do not open `.pth`/`.pt`/`.onnx` files as text |
| **GPU configuration** | `detectors.py` lines 30–33 (CPU threads limited to 2 while the GPU works), lines 92–93 (CUDA check), lines 107–113 (FP16 with FP32 fallback) | Run task **Demo 3** (`nvidia-smi` plus PyTorch CUDA check) and **Demo 4** (live server: rf-detr-nano, cuda, fp16) |
| **Show me your benchmarks** | Root **6 Benchmark results**: `phase1/results.json`, `precision/results.json`, `soak/soak_10min_before_fix.json` and `soak/soak_10min_after_fix.json` | Explained in `docs/PHASE1_GPU_DETECTOR_BENCHMARK.md`, `docs/EVALUATION.md`, `publication/TESTING_AND_VALIDATION_REPORT.md`. Scripts: `tools/benchmark_detectors.py`, `benchmark_precision.py`, `soak_test.py`, `evaluate.py` |
| **How the frontend connects to the backend** | `app.js` line 599 → `server.py` route `/api/awareness/frame` → `awareness.py` `process_frame()` → JSON reply → `speech.js` → `/api/tts` | All traffic is HTTPS on the local Wi-Fi (port 8765); setup page on port 8766. No cloud is involved except optional Gemini |
| **Run the complete application** | `START_NEUROSONIC.ps1`, `STOP_NEUROSONIC.ps1` | Tasks **Demo 6** (stop) → **Demo 5** (start) → **Demo 7** (API check) → **Demo 8** (iPhone URL) → **Demo 9** (browser) |

## Trained models and where they are

| Model | Location | Size | Use |
|---|---|---|---|
| RF-DETR Nano (COCO) | `C:\Users\Allwin\.roboflow\models\rf-detr-nano.pth` (**outside the project**; the path is searched in `detectors.py` lines 27–28) | 366 MB | Main live detector, GPU, FP16 |
| SSDLite320 MobileNetV3 (COCO) | `implementation\models\rgb\ssdlite320_mobilenet_v3_large_coco-a79551df.pth` | 14 MB | CPU fallback |
| WOAD exp72 checkpoint (copy) | `implementation\weights\best.pt` (SHA-256 starts `da043ff2e1edd393`) | — | Base-paper model, Research tools |
| Piper voice `en_IN-spicor` | `implementation\models\tts\en_IN-spicor\` (`.onnx` plus `.onnx.json` config) | 63.5 MB | Neural speech |
| Vosk `vosk-model-small-en-in-0.4` | `implementation\models\asr\` | 55 MB unpacked | Offline voice commands |
| YOLO26n / YOLO26s | `implementation\models\benchmark\` | 5.5 / 20.4 MB | Benchmark comparison only, not used in the app |
| Offline Vellore map | `implementation\maps\vellore\` (`graph.json`, `places.json`, `map.json`) | ~2.8 MB | A* routing and place search |

**Training:** no model was trained or retrained in this project. RF-DETR, SSDLite, Piper and Vosk are pretrained public models. WOAD exp72 was trained by the original authors.

**RF-DETR configuration:** there is no separate config file. The model configuration comes from the `rfdetr` package (`RFDETRNano`, used at `detectors.py` line 106), and the settings are in code: score threshold 0.40, FP16, frame interval 200 ms.

## Terminal commands (verified 3 Nov 2026)

```powershell
cd F:\Projects\WOAD-Research\implementation

# Activate the GPU environment (allowed: the CurrentUser execution policy is RemoteSigned)
..\.venv-gpu\Scripts\Activate.ps1
python --version                                   # Python 3.12.10
pip list | Select-String "torch|rfdetr|vosk|piper-tts|onnxruntime|google-genai"

# GPU
nvidia-smi                                         # NVIDIA GeForce RTX 4050 Laptop GPU, 6 GB, driver 592.82
python -W ignore -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# Start / stop (the server runs in the background and logs to logs\neurosonic_<time>.log)
powershell -ExecutionPolicy Bypass -File .\STOP_NEUROSONIC.ps1
powershell -ExecutionPolicy Bypass -File .\START_NEUROSONIC.ps1        # add -Cpu for SSDLite on CPU

# Model status and API check (Windows curl needs --ssl-no-revoke with the local certificate)
curl.exe -s --ssl-no-revoke --cacert data\tls\neurosonic-ca.crt https://127.0.0.1:8765/api/awareness/status
curl.exe -s --ssl-no-revoke --cacert data\tls\neurosonic-ca.crt https://127.0.0.1:8765/api/status

# Browser interface
#   laptop: https://127.0.0.1:8765
#   iPhone: https://192.168.1.5:8765   (one-time certificate setup: http://192.168.1.5:8766)

# Tests (several minutes)
python -m unittest discover -s tests -t .
```

The tasks in the workspace run exactly these commands without activating anything: they call
`..\.venv-gpu\Scripts\python.exe` directly.

## Before faculty arrive

- Laptop on mains power and in performance mode; on the same Wi-Fi as the iPhone.
- Run task **Demo 4**. It should show `rf-detr-nano`, `cuda`, `fp16`. If the server is not running, run **Demo 5**.
- Do not tap **Describe** on the phone unless you want a real Gemini request.
- Do not open `data\tls\` or show environment variables: they contain private keys and the API key.
