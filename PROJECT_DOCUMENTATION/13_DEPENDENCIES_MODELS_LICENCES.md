# 13. Dependencies, downloaded models, sizes and licences

Environment: Windows 11, **Python 3.12.10** (`F:\Projects\WOAD-Research\.venv`), Node.js v24.21.0 (tests only),
OpenSSL CLI (Git for Windows, for `--https`). Pinned list: `requirements.txt`.

## 13.1 Python packages (installed versions, read from package metadata on 2026-11-02)

| Package | Version | Licence (metadata) | Used for |
|---|---|---|---|
| torch | 2.15.0 (CPU build) | Apache-2.0 / BSD family (bundle) | WOAD and SSDLite inference |
| torchvision | 0.29.2 | BSD | SSDLite320 model definition, NMS ops |
| numpy | 2.5.4 | BSD-3-Clause (+ bundled) | arrays, map graph |
| opencv-python | 5.0.0.93 | Apache 2.0 | image I/O, resizing, colour conversion |
| piper-tts | 1.8.0 | **GPL-3.0-or-later** | neural TTS (bundles espeak-ng) |
| onnxruntime | 1.31.1 | MIT | runs the Piper ONNX voice |
| vosk | 0.3.45 | Apache-2.0 (Vosk project; the pip metadata field is empty) | offline speech recognition |
| pathvalidate, protobuf, flatbuffers, cffi, srt, websockets | dependencies of piper/onnxruntime/vosk | MIT / BSD-3 / Apache-2.0 / MIT-0 / MIT / BSD-3 | — |

Everything else is the **Python standard library**:

* `http.server`, `ssl`, `sqlite3`, `json`, `wave`, `heapq`, `difflib`, `threading`, `subprocess`.

The web client uses **no external JavaScript libraries and no CDN**.

## 13.2 Models and data

| Item | File(s) | Size | Source | Licence |
|---|---|---|---|---|
| WOAD exp72 checkpoint | `weights/best.pt` | 15,493,935 B (SHA-256 `da043ff2…f8aa`) | original repository `runs/train/exp72/weights/best.pt` (copy, original unchanged) | as the original WOAD project |
| Piper voice, Indian English | `models/tts/en_IN-spicor/en_IN-spicor.onnx` (+ `.onnx.json` 4,858 B) | 63,516,050 B | Hugging Face `navgurukul-ai-labs/text-to-speech-en-IN-piper` | **AGPL-3.0**; training-data licence not stated |
| Vosk model | `models/asr/vosk-model-small-en-in-0.4/` | zip 37,573,330 B; 55 MB unpacked | alphacephei.com | Apache-2.0 |
| SSDLite320 COCO weights | `models/rgb/ssdlite320_mobilenet_v3_large_coco-a79551df.pth` | 14,069,355 B | download.pytorch.org | BSD-3-Clause; COCO annotations CC BY 4.0 |
| Vellore OSM package | `maps/vellore/{map,graph,places,manifest}.json` | 1,052,137 + 1,646,391 + 96,374 + 1,496 B | built from Overpass downloads (4,164,985 + 548,032 + 171,359 B, in `datasets/osm/vellore/`) | ODbL 1.0, attribution required |
| WOAD demo recordings | `demo_data/detec_test/` (600 IR + depth pairs) | 189 MB | the WOAD authors' Google Drive `detec_test.rar` (SHA-256 `53cd2d29…febfd`) | as published by the authors |
| WOAD published dataset (evaluation only) | `datasets/VOCdetiv_data/` | 1.4 GB | the authors' Google Drive `VOCdetiv_data.rar` (SHA-256 `b2109f20…e391`) | as published by the authors |

## 13.3 Licence implications (for the viva)

* **GPL/AGPL:** Piper (GPL-3.0+) and the voice model (AGPL-3.0) are fine for research and local use. If
  NeuroSonic were distributed, or offered to others as a network service, the source-availability obligations of
  GPL/AGPL would apply. That must be reviewed before any public release.
* **OSM ODbL:** the attribution "© OpenStreetMap contributors" is shown on the map. A redistributed derived
  database must stay under ODbL.
* **Weights pickle:** the WOAD `.pt` file is a Python pickle, so it is only loaded with hash verification.
