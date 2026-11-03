# NeuroSonic: installation and deployment guide

## 1. Hardware and software used

| Item | Value |
|---|---|
| Laptop | HP Omen, AMD Ryzen 7 7840HS (8 cores / 16 threads), 15.3 GB RAM, NVIDIA GeForce RTX 4050 Laptop GPU (6 GB), Windows 11 |
| NVIDIA driver | 592.82 (reports CUDA 13.1) |
| Phone | iPhone with Safari, on the same Wi-Fi network |
| Python | 3.12.10 |
| Node.js (browser tests only) | v24 |

## 2. Environments

| Environment | Purpose | Key packages |
|---|---|---|
| `F:\Projects\WOAD-Research\.venv` | original CPU environment (kept unchanged) | torch 2.15.0+cpu, torchvision 0.29.2, onnxruntime 1.31.1, piper-tts 1.8.0, vosk 0.3.45, opencv-python 5.0.0.93, google-genai 2.34.0 |
| `F:\Projects\WOAD-Research\.venv-gpu` | **recommended**: GPU perception | same packages at the same versions, plus torch 2.15.0+cu132, torchvision 0.29.1+cu132, rfdetr 1.11.2 (Apache-2.0); ultralytics 8.4.198 for benchmarking only (AGPL-3.0, not imported by the app) |

How the GPU environment was created (already done, 2.43 GB download, 4.2 GB on disk):

```bat
"C:\Users\Allwin\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv-gpu
.venv-gpu\Scripts\python -m pip install --no-cache-dir -r <production requirements> torch==2.15.0+cu132 torchvision==0.29.1+cu132 rfdetr==1.11.2 ^
    --extra-index-url https://download.pytorch.org/whl/cu132
```

**Model files** (all local; nothing is downloaded at run time):

| Model | Location | Size |
|---|---|---|
| RF-DETR Nano | `C:\Users\Allwin\.roboflow\models\rf-detr-nano.pth` (also searched in `implementation\models\rfdetr\`) | 366 MB |
| SSDLite320 (fallback) | `implementation\models\rgb\` | 14 MB |
| Piper voice | `implementation\models\tts\` | 64 MB |
| Vosk | `implementation\models\asr\` | — |
| Offline map | `implementation\maps\vellore\` | 2.8 MB |

## 3. Start the application

```bat
cd F:\Projects\WOAD-Research\implementation
..\.venv-gpu\Scripts\python neurosonic_app.py --host 0.0.0.0 --https
```

* **Expected console line:**
  `Camera awareness: RF-DETR Nano (Roboflow, COCO, 384 px) on the NVIDIA GPU ready (cuda; frame interval 200 ms; ...)`.
  If it shows `SSDLite ... fallback: ...`, the GPU detector could not start; the reason is printed, and the app keeps
  working on the CPU.
* **iPhone:** open `https://<laptop-ip>:8765` (here `https://192.168.1.5:8765`).
* **First time only:** open `http://<laptop-ip>:8766` and install and trust the "NeuroSonic Local CA" certificate
  (iOS: Settings → General → About → Certificate Trust Settings).
* **Windows firewall:** allow Python on the private network. The start-up check prints the exact command if it is
  blocked.

**Options:**

| Option | Effect |
|---|---|
| `--detector auto\|rfdetr\|ssdlite` | default `auto` |
| `--no-events` | switches off the entering / crossing messages |
| `--vision-provider gemini\|mock\|off`, `--vision-model gemini-3.8-flash` | online description provider and model |
| `--port 8765` | server port |
| `GEMINI_API_KEY` | read on the laptop only |
| `NEUROSONIC_VISION_TIMEOUT_S` / `NEUROSONIC_VISION_BUDGET_S` | 30 / 45 by default |

**Laptop power settings for demonstrations** (measured effect: at 5 frames/s the GPU drops to its lowest power state
between frames, and RF-DETR then takes ≈ 53 ms instead of ≈ 17 ms per frame):

* keep the laptop on mains power and use the manufacturer's performance mode (OMEN Gaming Hub → Performance);
* NVIDIA Control Panel → Manage 3D settings → Program settings → the venv's `python.exe` → Power management mode →
  **Prefer maximum performance**. Not applied or measured in this project; it is a recommendation.

**CPU-only alternative:**

```bat
..\.venv\Scripts\python neurosonic_app.py --host 0.0.0.0 --https
```

## 4. Tests

```bat
cd F:\Projects\WOAD-Research\implementation
..\.venv-gpu\Scripts\python -m unittest discover -s tests -t .
..\.venv\Scripts\python -m unittest discover -s tests -t .
```

Browser tests need a running server (`--port 8799 --vision-provider mock`) and Chrome. See
`docs/NEUROSONIC_FINAL_TECHNICAL_DOCUMENTATION.md`, section 11, and `tests/js/*_cdp.mjs`.

* `ui_vision_slow_cdp.mjs` needs `NEUROSONIC_VISION_MOCK_SCRIPT=slow20`.
* `ui_vision_cdp.mjs` needs `NEUROSONIC_VISION_MOCK_SCRIPT=ok,503,503`, so run it against a second server.

**Stability and performance tools:**

* `tools\soak_test.py`: 10-minute stream with parallel slow cloud requests;
* `tools\benchmark_precision.py`: FP32 vs FP16;
* `tools\make_publication_figures.py`: regenerates `publication/figures/` from the result files.

## 5. Troubleshooting

| Symptom | Check |
|---|---|
| Chip shows "SSDLite · CPU (fallback)" | the start-up reason line; `nvidia-smi`; the app must run from `.venv-gpu` |
| Phone cannot connect | same Wi-Fi; firewall rule; the URL uses the IP printed by the app; the certificate is installed |
| "Port … is already in use" | another NeuroSonic is running; stop it, or use `--port` |
| No sound on the iPhone | tap the screen once; ring/silent switch; Settings → Test Voice |
| Online description unavailable | internet on the laptop; `GEMINI_API_KEY`; local guidance continues regardless |
