# NeuroSonic: handoff status (2026-11-03, end of the final phase)

NeuroSonic is a research prototype, **not** a safety device.

**Main documents:**

* technical: `../docs/NEUROSONIC_FINAL_TECHNICAL_DOCUMENTATION.md`;
* tests: `../publication/TESTING_AND_VALIDATION_REPORT.md`;
* publication package: `../publication/`.

## 1. State

* **Application:** complete for laptop use.
  * **Perception:** RF-DETR Nano (FP16) on the RTX 4050, with an automatic SSDLite CPU fall-back.
  * **Tracking:** camera-motion-compensated tracking.
  * **Events:** entering and crossing.
  * **Other functions:** walking-path states, object description, Piper voice, Vosk commands, offline Vellore map with
    A* routing, text-only history, and an optional opt-in Gemini description.
  * **Phone client:** Safari on the iPhone, frame interval chosen by the server (200 ms on GPU, 400 ms on CPU), and a
    detector chip on Home.
* **Final-phase changes (backups in `backups/20261103-final-ui/`):**
  * FP16 inference for RF-DETR;
  * all inference on one long-lived thread;
  * quiet handling of client disconnects;
  * the active weights and precision reported in `/api/awareness/status`;
  * detector chip;
  * new tools: `tools/soak_test.py`, `tools/benchmark_precision.py`, `tools/make_publication_figures.py`.
* **Unchanged:** the original WOAD repository, the datasets, the WOAD checkpoint, and the production `.venv` (its
  `pip freeze` is identical to the backup).

## 2. Verified on 2026-11-03 (after the last code change)

| Check | Result |
|---|---|
| Python tests, `.venv-gpu` | Ran 204, OK (1 skipped: opt-in live cloud test) |
| Python tests, `.venv` | Ran 204, OK (3 skipped) |
| Browser tests (7) | 7 / 7 PASS |
| 10-minute soak, final code | 2980 frames, 0 errors, 4.97 fps, request medians 70–78 ms, 7 / 7 slow cloud requests |
| Quality gate | GPU launch (documented command, port 8770) and CPU launch: frames, speech, search, route, voice command, history |
| Figures | 6 figures regenerated from the result files and inspected |
| PDFs | `publication/NeuroSonic_Manuscript.pdf` (15 pages), `publication/NeuroSonic_Slides.pdf` (12 slides), checked visually |

## 3. Not done: needs the owner and the iPhone

See `../docs/IPHONE_VALIDATION_PROTOCOL.md` and `../publication/TESTING_AND_VALIDATION_REPORT.md` §7.

1. RF-DETR on real iPhone frames: check `/api/awareness/status → clients`.
2. Wi-Fi capture → answer latency.
3. iPhone audio and microphone.
4. Real scenes, with a cane and a sighted companion.
5. A GPS route walk.
6. A physically disconnected internet connection.
7. A live Gemini description (needs the owner's approval).
8. A run of an hour or longer over Wi-Fi.

## 4. Launch and shutdown (verified 2026-11-03, 05:44–05:49)

**Recommended:** use the scripts in `implementation\`. They start the server as an independent background process,
so it keeps running after the terminal or Claude Code closes. Run them from PowerShell:

```powershell
cd F:\Projects\WOAD-Research\implementation
powershell -ExecutionPolicy Bypass -File .\START_NEUROSONIC.ps1          # RF-DETR on the GPU (.venv-gpu)
powershell -ExecutionPolicy Bypass -File .\STOP_NEUROSONIC.ps1           # stop every NeuroSonic server
```

* **START options:**
  * `-Cpu`: production `.venv`, SSDLite on the CPU.
  * `-Port N`: use port N; the setup page goes on N+1.
  * `-VisionProvider off|mock|gemini`: online description setting. The default is gemini, which makes no request
    until the user opts in on the phone.
* **What START does:**
  * runs the documented command `..\.venv-gpu\Scripts\python.exe neurosonic_app.py --host 0.0.0.0 --https`
    (from `neurosonic_app.py` and `README.md`);
  * refuses to start if port 8765 or 8766 is in use, or if another NeuroSonic server is running;
  * waits until the server's own log says it is listening, then prints the detector, device, precision, the
    current LAN IP, the iPhone URL and the setup URL;
  * logs to `logs\neurosonic_<time>.log` and writes the PID to `data\neurosonic.pid`.
* **What STOP does:**
  * stops only processes that run `neurosonic_app.py` from this project's `.venv` or `.venv-gpu`, together with their
    base-Python children and the `cmd.exe` wrapper;
  * never touches other Python processes;
  * keeps the history database;
  * `-Port N` limits it to one server; `-WhatIf` lists what it would stop.
* **Manual launch (foreground; stops when its window closes):**
  `cd F:\Projects\WOAD-Research\implementation` then `..\.venv-gpu\Scripts\python neurosonic_app.py --host 0.0.0.0 --https`.
  For CPU only, use `..\.venv\Scripts\python` instead.
* **iPhone (address checked 2026-11-03 with `ipconfig`; Wi-Fi 192.168.1.5):** `https://192.168.1.5:8765`;
  one-time setup page `http://192.168.1.5:8766`. If the router gives the laptop a different address, START prints
  the new one.

**Verified on the laptop:**

* GPU start: RF-DETR Nano on cuda, fp16, frame interval 200 ms, weights `rf-detr-nano.pth`.
* LAN address `192.168.1.5`, over HTTPS:
  * the page, `/js/app.js` and `/style.css` return 200;
  * the status, awareness, TTS, voice-command, map and vision endpoints all return 200;
  * the certificate chain and hostname verify against `data\tls\neurosonic-ca.crt`;
  * the setup page on 8766 returns 200.
* Six test frames went through `rf-detr-nano`, median 78 ms (laptop loopback, not an iPhone).
* CPU start (`-Cpu`): SSDLite on the CPU at 400 ms, with the fallback reason printed.
* A second START is refused and names the owning process.
* **Survival after Claude Code exits:**
  * The server's parent chain is `WmiPrvSE.exe → cmd.exe → python`; `claude.exe` is not in it.
  * In a test, a kill-on-close job object was closed. A normally started child died; a child created the same way as
    START creates the server survived.
  * Not yet observed directly: the server still running after Claude Code itself was closed.
* **Note for checking from Windows:** Windows `curl` gives "revocation status is unknown" for the local certificate
  authority. Add `--ssl-no-revoke`; this is not a server fault.

## 5. Processes (2026-11-03, 05:49)

* **Running:** one NeuroSonic server, started by `START_NEUROSONIC.ps1` (`.venv-gpu`, port 8765/8766, log
  `logs\neurosonic_20261103_054819.log`). Stop it with `STOP_NEUROSONIC.ps1`.
* **Stopped:**
  * the owner's old server (PIDs 79032 / 62688, production `.venv`, code from before the final phase, Gemini
    flags identical to the defaults);
  * the old test servers on 8790 and 8797 (PIDs 52864 / 55448, 26524 / 56016; their databases were scratch files).
* **History database:** backed up before the shutdown with SQLite's online backup to
  `backups/20261103-release-launch/neurosonic.sqlite3` (integrity ok; 1926 alerts, 0 places). The live
  `data\neurosonic.sqlite3` is unchanged and still in use.
* **Left untouched:** other Python processes (the Blender MCP extension).

## 6. Rules for the next agent

* Do not modify the original WOAD repository, the datasets, the checkpoint or the production `.venv`.
* No live Gemini requests without approval.
* Never store camera images.
* Never claim safety, distance or 360-degree vision.
* Back up before changing code, and run both test suites and the browser tests afterwards.
