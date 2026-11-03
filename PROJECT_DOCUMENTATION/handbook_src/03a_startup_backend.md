# Part 3 – Individual Source Code Explanations

Files are grouped as: **A** start-up and configuration, **B** backend, **C** AI engine and camera processing,
**D** base-paper WOAD package, **E** frontend, **F** tools and tests. Line numbers (L…) refer to the code on
3 November 2026.

## A1. File: neurosonic_app.py {: .file}

#### 1. Purpose
The main program of NeuroSonic. It reads the command-line options, creates every engine (database, WOAD model,
voice, map, voice commands, camera detector, online description), starts the HTTPS web server and prints the
addresses the iPhone should open.

#### 2. How the code works
1. `ROOT` is the `implementation` folder; it is added to `sys.path` so `neurosonic` and `woad` can be imported.
2. `main()` (L28) defines the options with `argparse` (L29–53) and parses them.
3. With `--https`, `ensure_certificates()` creates/reuses the certificates and `server_ssl_context()` builds the TLS
   context (L58–65). If OpenSSL is missing it prints an error and returns exit code 2.
4. It creates, in order: `Store` (SQLite), `DetectionService` (WOAD), `PiperTTS` + `warm_up()`, `OfflineMap`,
   `VoiceCommands` + `warm_up()`, `RGBAwareness` + `warm_up()`, then `make_provider()` + `SceneAssistant` (L67–114).
   Each prints one status line, for example `Camera awareness: RF-DETR Nano … ready (cuda; frame interval 200 ms …)`.
5. `make_server(...)` (L116) receives all engine objects. If the port is busy, it prints
   `ERROR: cannot listen … (is the app already running?)` and returns 2.
6. In LAN + HTTPS mode it starts the setup page server on port+1 in a thread (L126–129).
7. It prints `NeuroSonic running: …`, the phone URLs and the CA fingerprint, runs the Windows firewall check
   (`windows_report`), and finally calls `httpd.serve_forever()` (L146). On Ctrl+C the `finally` block stops the
   replay, closes the servers and the database.

#### 3. Important functions and classes

| Name | Input | Processing | Output | Called by |
|---|---|---|---|---|
| `main(argv=None)` L28 | command-line options | builds all engines, starts servers | exit code 0 / 2 | `if __name__ == "__main__"` (L159), `START_NEUROSONIC.ps1` |

Key options: `--host` (default `127.0.0.1`; `0.0.0.0` for the phone), `--port` (8765), `--https`, `--detector`
(`auto`/`rfdetr`/`ssdlite`, default from `NEUROSONIC_DETECTOR` or `auto`), `--vision-provider`
(`gemini`/`mock`/`off`), `--vision-model` (default `gemini-3.8-flash`), `--no-events`, `--db`, `--map`, `--asr-model`,
`--voice-model`, `--rgb-weights`.

#### 4. Important code sections
- L93–94: `RGBAwareness(a.rgb_weights, detector=a.detector or os.environ.get("NEUROSONIC_DETECTOR") or "auto", …)` –
  "auto" means *try RF-DETR on the GPU first, otherwise SSDLite*.
- L104–105: `provider = make_provider(a.vision_provider, a.vision_model)` and `SceneAssistant(provider, enabled=…)` –
  this only configures Gemini; no internet request is made at start-up.
- L116–121: the `try/except OSError` around `make_server` – the friendly "already running" message.

#### 5. Connections
Imports `neurosonic.server`, `service`, `store`, `tls`, `netcheck`, `tts`, `maps`, `voicecmd`, `awareness`,
`vision` and `woad.model_loader`. It is started by `START_NEUROSONIC.ps1`.

#### 6. Faculty demonstration explanation
> "This is the entry point. When I run it, it loads every engine one by one and prints one status line for each, so I
> can see immediately that the GPU detector, the voice, the map and the speech recogniser are ready. Then it starts
> an HTTPS server on port 8765 for the iPhone and a small setup page on 8766 for installing our certificate."

#### 7. Possible faculty questions
- **Why `--host 0.0.0.0`?** It listens on all network interfaces, so the iPhone on the same Wi-Fi can connect; the
  default `127.0.0.1` accepts only the laptop itself.
- **What happens if the GPU is not available?** `RGBAwareness` falls back to SSDLite on the CPU and the start-up line
  prints the reason (`fallback: …`).
- **Does it call Gemini at start-up?** No. It only builds the provider object; a request is sent only when the user
  allows it and taps Describe.
- **Why exit code 2?** To signal a start-up failure (certificate or port problem) to the start script.

## A2. Files: START_NEUROSONIC.ps1 and STOP_NEUROSONIC.ps1 {: .file}

#### 1. Purpose
PowerShell scripts that start the server as an independent background process and stop it safely. They make the
demonstration reliable: the server keeps running even if the terminal (or Claude Code) is closed.

#### 2. How the code works (START)
1. Parameters: `-Port 8765`, `-Cpu`, `-VisionProvider`, `-VisionModel`, `-TimeoutSeconds 180`.
2. Chooses the interpreter: `..\.venv-gpu\Scripts\python.exe` (or `..\.venv\…` with `-Cpu`).
3. **Safety checks:** refuses to start if port 8765 or 8766 already accepts a TCP connection, or if any
   `neurosonic_app.py` process from the project environments is running (it names the process).
4. Creates the process through WMI (`Win32_Process.Create`) running
   `cmd.exe /d /c "python -u neurosonic_app.py --host 0.0.0.0 --https --port N > logs\neurosonic_<time>.log 2>&1"`,
   so the server is not a child of the calling shell.
5. Writes the PID to `data\neurosonic.pid`, waits until the log contains `NeuroSonic running:`, then calls
   `/api/awareness/status` and prints detector, device, precision, frame interval, the LAN IP and the iPhone URL.

**STOP** finds only processes whose command line contains `neurosonic_app.py` and whose executable is under
`F:\Projects\WOAD-Research` (plus their child process and the `cmd` wrapper), stops them, and removes a stale PID
file. `-WhatIf` lists without stopping; `-Port N` limits it to one server. Other Python programs are never touched.

#### 3–5. Functions, sections, connections
The scripts call `neurosonic_app.py` and read `logs\` and `/api/awareness/status`. The important design point is the
TCP-connect port check (Windows' "Listen" query returned nothing on this laptop, so the first version allowed a
duplicate start; this was found and fixed).

#### 6. Faculty demonstration explanation
> "To run the full application I use one script. It checks that nothing else is using the port, starts the server in
> the background, waits until the server reports it is listening, and then prints which detector is active and the
> address for the iPhone. The stop script stops only NeuroSonic, never other Python programs."

#### 7. Possible faculty questions
- **Why WMI instead of `Start-Process`?** A process created by WMI is not part of the terminal's process tree, so
  closing the terminal does not kill it.
- **Where are errors shown?** In `logs\neurosonic_<time>.log` (the server's standard output and error).
- **Can two servers run at once?** Not on the same port: the script refuses, and the server itself binds the port
  exclusively (`SO_EXCLUSIVEADDRUSE` in `server.py`).

## A3. File: requirements.txt {: .file}

#### 1. Purpose
Lists the exact package versions the tests passed with, so the environment can be rebuilt.

#### 2–4. Content
`torch==2.15.0`, `torchvision==0.29.2`, `numpy==2.5.4`, `opencv-python==5.0.0.93`, `piper-tts==1.8.0`,
`onnxruntime==1.31.1`, `vosk==0.3.45`, `google-genai==2.34.0`. Comments explain licences and that the web server,
SQLite store, map routing and TLS use only the standard library (plus `numpy`, and the `openssl` command for HTTPS).
The GPU environment `.venv-gpu` additionally has `torch 2.15.0+cu132`, `torchvision 0.29.1+cu132` and `rfdetr 1.11.2`
(and `ultralytics`, used only for benchmarking).

#### 6. Faculty demonstration explanation
> "All versions are pinned. The production environment `.venv` is CPU-only; the GPU work happens in a separate
> environment `.venv-gpu` so the working CPU setup was never put at risk."

#### 7. Possible faculty questions
- **Why is TensorFlow not listed?** The project does not use it; all models run on PyTorch (Piper uses ONNX Runtime).
- **Why two environments?** Installing the 2.4 GB CUDA build into the working environment could break it; a separate
  one can be deleted without harm.

## B1. File: neurosonic/server.py {: .file}

#### 1. Purpose
The web server of NeuroSonic. It serves the frontend files and all API endpoints (camera frames, speech, voice
commands, map, history, online description, WOAD research tools), over HTTPS. It uses only Python's standard library.

#### 2. How the code works
1. `make_server()` (L462) creates a `NeuroSonicHTTPServer` with a request-handler class built by `make_handler()`
   (L62). The engine objects (`service`, `store`, `tts`, `offline_map`, `voicecmd`, `awareness`, `vision`) are
   captured in that class, so every route can use them.
2. `NeuroSonicHTTPServer` (L421) extends `ThreadingHTTPServer`: **each connection is handled in its own thread**.
3. `finish_request()` (L444) runs in that worker thread: it performs the **TLS handshake** with a 10-second timeout
   (`TLS_HANDSHAKE_TIMEOUT`), then runs the handler.
4. `do_GET`/`do_POST` (L404–411) call `_dispatch()` (L133), which looks up the path in the `GET` or `POST`
   dictionary (L392–402). Unknown GET paths go to `_static()` (the web files).
5. The route method reads the body, calls the engine, and replies with `_json()` or `_send()`.
6. `_dispatch()` turns errors into HTTP status codes: `ApiError` → its own code (400/404/413/415/503), `TTSError` →
   503, `ValueError`/`InvalidInput` → 400, client disconnect → quiet close, anything else → 500.

#### 3. Important functions and classes

| Name | Input | Processing | Output | Called by |
|---|---|---|---|---|
| `make_handler()` L62 | engine objects | defines the `Handler` class and route tables | handler class | `make_server` |
| `Handler._raw_body(limit, kinds)` L91 | binary upload | checks length (413), Content-Type (415) | bytes | frame, voice, vision routes |
| `Handler._body()` L103 | JSON request | parses, checks it is an object | `dict` | JSON routes |
| `Handler._drain_unread_body()` L117 | — | reads a rejected body so Windows does not reset the socket | — | `_dispatch` on error |
| `Handler._static(path)` L161 | URL path | blocks path traversal, sets explicit MIME types (`STATIC_TYPES`) | file bytes | `_dispatch` |
| `r_awareness_frame()` L377 | JPEG body, `session`, `mode`, `describe` | calls `awareness.process_frame`, logs events | JSON result | phone `awarenessStep()` |
| `r_tts()` L249 / `_send_media()` L255 | `text` | Piper WAV; supports HTTP Range (206/416) for iOS | `audio/wav` | `speech.js` |
| `r_voicecmd()` L331 | 16 kHz WAV | `voicecmd.handle` | heard text, intent, places | `app.js listenOnce` |
| `r_route()` L318, `r_map_search()` L311 | from/to or query | `offline_map.route` / `search` | route JSON / results | `app.js` |
| `r_vision_describe()` L356 | photo, consent, question | `vision.describe`; deletes the image | spoken text JSON | `app.js describeScene` |
| `NeuroSonicHTTPServer.finish_request()` L444 | accepted socket | TLS handshake per connection, in the worker thread | — | `socketserver` |
| `server_bind()` L435 | — | `SO_EXCLUSIVEADDRUSE` on Windows | — | server start |
| `make_setup_server()` L469 | CA file | plain-HTTP page that only serves the CA certificate | server | `neurosonic_app.py` |

#### 4. Important code sections
- **Route tables (L392–402).** One place lists every endpoint: 16 GET routes and 12 POST routes.
- **Per-connection TLS (L444–459).** `request.settimeout(self.handshake_timeout)` then
  `self.ssl_context.wrap_socket(request, server_side=True)`. A failed or slow handshake drops only that connection.
- **Exclusive port (L433–438).** `allow_reuse_address = sys.platform != "win32"` and `SO_EXCLUSIVEADDRUSE`.
- **Image never stored (L366).** `del img` after the online description.

#### 5. Connections
Called by the browser (`app.js`, `speech.js`). Calls `service.py`, `store.py`, `tts.py`, `maps.py`, `voicecmd.py`,
`awareness.py`, `vision/assistant.py`. Created by `neurosonic_app.py`.

#### 6. Faculty demonstration explanation
> "This is the backend. All endpoints are in one table at line 392. When the phone sends a camera frame to
> `/api/awareness/frame`, the server reads the JPEG, gives it to the awareness pipeline and returns JSON. Each
> connection runs in its own thread and does its own HTTPS handshake – that fixed a real bug where one slow iPhone
> connection froze the whole server."

#### 7. Possible faculty questions
- **Why not Flask or FastAPI?** The standard library was enough, adds no dependencies, and gave low-level control
  needed for two real fixes (per-connection TLS, exclusive port binding).
- **Is it REST?** It is a resource-style HTTP/JSON API (GET reads, POST actions/uploads, status codes for errors);
  not strictly RESTful everywhere (e.g. `POST /api/places/delete`).
- **How are big uploads prevented?** `_raw_body` limits frames to 3 MB and WAV to 2 MB (413 otherwise); JSON bodies to
  20 MB (`MAX_BODY`).
- **Why the `_drain_unread_body` function?** On Windows, closing a socket with unread data sends a reset, so the
  client saw "connection aborted" instead of the error message. Reading the body first fixed it (regression test).
- **Is there a login?** No. Anyone on the same Wi-Fi can reach it; this is a stated limitation.

## B2. File: neurosonic/service.py {: .file}

#### 1. Purpose
Wraps the base-paper **WOAD** detector for the Research tools: a background **replay** of recorded IR + depth frames,
and detection on a **single uploaded pair**. It also holds the **event log** that feeds the History.

#### 2. How the code works
1. `DetectionService.__init__` (L165) loads `WOADDetector(weights, device, conf_thres=0.25)`, an
   `InputQualityChecker`, a `model_lock`, and an `EventLog(store)`.
2. `start_replay(name, fps)` (L184) checks the set name (only server-known sets in `REPLAY_SETS`) and fps (0.5–10),
   stops any old replay and starts a `ReplayRunner` thread.
3. `ReplayRunner.run()` (L124), for each frame: quality check → (if usable) WOAD detection under `model_lock` →
   `AlertEngine.process` → events added to the log → annotated JPEG published → wait for the next frame time.
4. `detect_upload()` (L213) decodes the two images, checks quality, runs WOAD once, and builds alerts with a
   single-frame `AlertConfig(confirm_hits=1, …)`.
5. `EventLog.add()` (L77) gives each event an increasing id (for `/api/events?since=`) and **writes it to SQLite**
   through `store.add_alert` – this is how camera alerts also reach the History.

#### 3. Important functions and classes

| Name | Input | Output | Called by |
|---|---|---|---|
| `decode_image(data, role)` L41 | bytes | 8-bit BGR image (rejects 16-bit / grey depth) | `detect_upload` |
| `EventLog.add / since / last_id` L77–96 | source, kind, text, data | event dict; list of newer events | server routes, replay |
| `ReplayRunner(threading.Thread)` L99 | set name, fps | state + JPEG (via `snapshot()`) | `start_replay` |
| `DetectionService` L164 | store, weights, device | replay control, upload results | `server.py` |

#### 6. Faculty demonstration explanation
> "This file connects the base paper to the app. WOAD needs an infrared camera and a depth camera, which we do not
> have, so the replay plays the authors' recorded sensor frames through exactly the same path a live sensor would
> use: quality check, WOAD model, alert engine, spoken alerts."

#### 7. Possible faculty questions
- **Why a lock around the model?** The replay thread and uploads share one model instance; the lock prevents two
  threads from running it at the same time.
- **Can a user replay any folder?** No. Only the names in `REPLAY_SETS` are accepted, so no client-supplied paths.
- **Where do events go?** Into an in-memory ring (300 items) for polling, and into SQLite for the History.

## B3. File: neurosonic/store.py {: .file}

#### 1. Purpose
Local SQLite database for the **alert history** and **saved places**. Nothing leaves the laptop, and no image is
ever stored – only text.

#### 2. How the code works
1. `Store.__init__` (L33) opens the database file (`data/neurosonic.sqlite3`) with `check_same_thread=False` and a
   `threading.Lock`, and creates the tables from `SCHEMA` (L6) if they do not exist.
2. `add_alert()` (L47) checks `source` and `kind` against whitelists (`ALLOWED_SOURCES`, `ALLOWED_KINDS`, L28–29),
   cuts text to 300 characters and inserts a row using `?` parameters.
3. `history(limit)` returns the newest rows (1–1000); `stats()` counts by class, kind and source;
   `clear_history()` deletes all alerts.
4. `add_place/places/delete_place` manage saved places with latitude/longitude range checks.

#### 4. Important code section
Table `alerts(id, created, source, kind, text, class_name, position, confidence, frame_id)` – note there is **no
image column**. Table `places` has SQL `CHECK` constraints on `lat` and `lon`.

#### 6. Faculty demonstration explanation
> "History is stored locally in SQLite, text only. Every insert uses parameters, so it is safe against SQL injection,
> and the source and kind are checked against a whitelist."

#### 7. Possible faculty questions
- **Why SQLite?** Built into Python, a single file, no server, enough for one user.
- **Is it thread-safe?** All database calls run under one lock, because the web server uses many threads.
- **Are camera images stored?** No; the schema has no image field, and the frame bytes are discarded after analysis.

## B4. Files: neurosonic/tls.py and neurosonic/netcheck.py {: .file}

#### 1. Purpose
`tls.py` creates the HTTPS certificates that an iPhone accepts. `netcheck.py` checks the Windows network profile and
firewall rules and prints the exact fix commands.

#### 2. How the code works (tls.py)
1. `ensure_certificates(tls_dir)` (L86): if `neurosonic-ca.crt/.key` do not exist, run `openssl req -x509 …` to make
   the local root CA "NeuroSonic Local CA" (825 days).
2. Collect the laptop's addresses with `lan_ips()` (L36) and the host name.
3. If the existing server certificate does not cover these addresses, belongs to another CA, or expires within 14
   days, create a new one signed by the CA with `subjectAltName = IP:…, DNS:localhost, …`, `extendedKeyUsage =
   serverAuth`, `CA:FALSE`, 397 days – the rules iOS requires.
4. `server_ssl_context()` (L133) builds an `ssl.SSLContext` with minimum TLS 1.2.

#### 6. Faculty demonstration explanation
> "Phones only allow the camera and GPS on HTTPS. A plain self-signed certificate was rejected by iOS, so this file
> creates a small local certificate authority. I install it once on the iPhone from the setup page; after that the
> connection is trusted and browser security is never disabled."

#### 7. Possible faculty questions
- **Why did the first certificate fail on iOS?** It had no Subject Alternative Name and no serverAuth usage, and was
  marked as a CA; iOS 13+ rejects such server certificates.
- **What if the laptop's IP changes?** `ensure_certificates` notices the new address and issues a new server
  certificate automatically.
- **Is the private key safe?** It stays in `data/tls/` on the laptop and must never be uploaded (e.g. to GitHub).

## B5. File: neurosonic/tts.py {: .file}

#### 1. Purpose
Offline **neural text-to-speech** with Piper. It turns a sentence into a WAV file on the laptop, which the phone plays.
Voice: Indian-English `en_IN-spicor.onnx` (22.05 kHz mono).

#### 2. How the code works
1. `PiperTTS.__init__` (L32) stores the model path, speaking `STYLE` (`length_scale 1.08`, `noise_scale 0.6`,
   `noise_w_scale 0.7`), and a cache folder.
2. `warm_up()` (L75) loads the model with `PiperVoice.load()` and synthesises "Ready." to prove it works.
3. `synthesize(text)` (L95): `clean()` collapses spaces and rejects empty text or more than 400 characters
   (`MAX_CHARS`); a SHA-256 key of voice + style + text is computed; the audio is returned from the in-memory cache
   (64 items), the disk cache (400 files), or generated with `voice.synthesize_wav()` under a lock and saved.

#### 5. Connections
Called by `server.py` `r_tts()` (`GET /api/tts?text=`), which `speech.js` fetches. Started by `neurosonic_app.py`.

#### 6. Faculty demonstration explanation
> "The voice is generated on the laptop by a neural model, so it works without internet. Common warnings like 'Stop'
> are cached, and the phone even fetches them in advance, so an urgent warning is never delayed by synthesis."

#### 7. Possible faculty questions
- **What if Piper fails?** `TTSError` becomes HTTP 503 and the phone falls back to its built-in `speechSynthesis`.
- **Why cache by hash?** The same sentence always gives the same audio; hashing voice+style+text gives a safe file name.
- **Licences?** Piper is GPL-3.0-or-later; the voice is AGPL-3.0 (stated in `info()`).

## B6. File: neurosonic/voicecmd.py {: .file}

#### 1. Purpose
Offline **voice commands** with Vosk (Indian-English small model). It converts a short recording into text and an
*intent* such as `navigate` + "CMC Hospital".

#### 2. How the code works
1. `handle(wav_bytes, near, saved)` (L224) checks the WAV (`read_wav16k`: mono, 16-bit, 16 kHz, ≤ 8 s) and rejects
   recordings shorter than 0.3 s.
2. `transcribe(pcm)` (L184) runs **two recognisers** on the same audio: one restricted to `COMMAND_WORDS` (robust for
   commands) and one free dictation (for place names).
3. `parse_intent(grammar_text, free_text)` (L74) uses regular expressions and word sets to choose one of 13 intents
   (navigate, search, start/stop navigation, repeat, status, awareness on/off, help, test voice, describe_scene,
   ask_scene, unknown).
4. For navigate/search, `resolve_place()` (L199) tries saved places, then the map's text search, then a
   **sound-alike** match using `phonetic()` (L45) and `place_score()` (L62), because Vosk cannot spell most Vellore
   names ("Katpadi" heard as "cut body").

#### 6. Faculty demonstration explanation
> "Speech recognition runs offline on the laptop. One recogniser only knows the command words, the other listens
> freely for the place name, and a sound-alike matcher finds the closest place in the offline map. Because this is
> not fully reliable, the app says which place it chose and waits for 'start navigation'."

#### 7. Possible faculty questions
- **Why two recognisers?** A grammar-restricted recogniser is reliable for fixed commands but cannot hear unknown
  names; free dictation hears names but often garbles command words.
- **How accurate are place names?** Correct first time in 10 of 24 test commands – so confirmation is required.
- **Is audio stored?** No; it is processed in memory and only the intent is logged.

## B7. File: neurosonic/maps.py {: .file}

#### 1. Purpose
Offline map services on the local OpenStreetMap extract of Vellore (`maps/vellore/`): coverage check, place search
and walking routes with the **A\*** shortest-path algorithm, plus spoken turn instructions.

#### 2. How the code works
1. `OfflineMap.__init__` (L59) loads `manifest.json`, `graph.json` (nodes, ways, edges) and `places.json`, builds an
   adjacency list, and finds **connected components** (islands such as paths inside Vellore Fort).
2. `search(query, near)` (L111) scores names: exact 100, prefix 80, contains 60, all words 40; ties by distance.
3. `route(start, end)` (L140): checks coverage, snaps both points to the nearest graph node (`nearest_node`, max 250 m,
   600 m for islands), runs `_astar()`, rebuilds the path, and `_steps()` turns it into instructions.
4. `_astar(s, t)` (L184): a priority queue (`heapq`) ordered by *distance so far + straight-line (haversine) distance
   to the goal*. The straight-line estimate never over-estimates, so A* finds the shortest path.
5. `_steps()` (L222) keeps a turn only if the direction changes ≥ 30° (measured 20 m before/after the junction) or a
   named street begins, and merges steps shorter than 12 m.

#### 6. Faculty demonstration explanation
> "Routing works without internet. The Vellore street network is a graph of 31,439 path points; A* searches it using
> straight-line distance as the guide. The output is a polyline for the map plus a short list of spoken turns, for
> example Katpadi to CMC Hospital gives six instructions."

#### 7. Possible faculty questions
- **Why is the haversine heuristic valid?** No walking path can be shorter than the straight line, so it never
  over-estimates (it is *admissible*), which guarantees the shortest route.
- **Limits?** OSM data for Vellore is sparse: few street names, no pavement/crossing information, no buildings.
- **What if the destination is outside the map?** `MapError` with a clear sentence (HTTP 400).

## B8. File: neurosonic/vision/assistant.py {: .file}

#### 1. Purpose
The provider-independent logic of the optional **online scene description**: consent, rate limits, retries, a circuit
breaker, and a **safety filter** that removes distances and "it is safe" claims before anything is spoken.

#### 2. How the code works (`SceneAssistant.describe`, L286)
1. Checks, in order: enabled → **consent** → provider configured → breaker not open → at most one request per 5 s per
   session (`min_interval_s`) → at most 60 per hour (`hourly_cap`).
2. `prepare_image()` (L174) validates the photo and shrinks it to ≤ 1024 px JPEG, **in memory only**.
3. `build_prompt()` adds the carrying mode and the question; `SYSTEM` (L69) tells the model the rules (positions only
   as left/centre/right, never distances, never "safe").
4. Calls `provider.analyze(req, prompt, SYSTEM, self.per_try_timeout_s)` – always the **full** 30 s attempt. Only a
   quick `ProviderUnavailable` (503/network) is retried once, and only if another full attempt fits in the 45 s budget.
   Timeouts are never retried.
5. On success `compose_speech()` (L121) builds "AI description: …", passing every part through `filter_text()`
   (L99), which drops sentences matching `_BANNED` patterns, and adds "Please check the path yourself." if anything
   was removed. On failure it returns a ready-to-speak text from `TEXT`, e.g. "The online description took too long.
   Local walking guidance continues."
6. Three failures in a row open the breaker for 60 s.

#### 6. Faculty demonstration explanation
> "Online description is optional and off until the user allows it. Even then, the answer is filtered: any sentence
> with a distance or a claim that the path is safe is removed. Walking guidance never depends on this module."

#### 7. Possible faculty questions
- **Why not retry a timeout?** It already used the full time; repeating it only makes the user wait longer. This fix
  came from a real bug where retries got a 4-second deadline that Gemini rejected.
- **Where do 30 s / 45 s come from?** They are assumptions (one live request failed at 25 s), configurable with
  `NEUROSONIC_VISION_TIMEOUT_S` and `NEUROSONIC_VISION_BUDGET_S`.
- **Has it worked live?** No successful live description has been recorded yet; the only approved live test timed out.

## B9. Files: neurosonic/vision/gemini.py, base.py, mock.py {: .file}

#### 1. Purpose
`gemini.py` is the Google Gemini provider; `base.py` defines the provider interface, the JSON reply schema and the
error types; `mock.py` is a fake provider for tests and offline demos.

#### 2. How the code works (gemini.py)
1. `read_key()` (L26) reads `GEMINI_API_KEY` from the environment, or on Windows from the user registry environment.
   The key is never printed, returned or stored; error text is passed through `scrub()`.
2. `_get_client()` (L74) creates `genai.Client(api_key=…, http_options=HttpOptions(retry_options=
   HttpRetryOptions(attempts=1)))` – the SDK's own retries are off, so one call is one request.
3. `analyze()` (L86): `timeout_s = max(timeout_s, self.min_timeout_s)` (minimum **10 s**, because the SDK sends the
   timeout to Google as the server deadline and Google rejects less than 10 s); runs `generate_content` in a thread
   with a hard guard of timeout + 2 s; asks for JSON (`response_mime_type="application/json"`,
   `response_json_schema=SCENE_SCHEMA`, temperature 0.2).
4. `_map_error()` converts HTTP codes: 408/504 → `ProviderTimeout`, 429 → `ProviderRateLimited`, ≥500 →
   `ProviderUnavailable`, others → `Rejected`.
5. `make_provider(name)` (L159) returns a Gemini provider, a `MockProvider`, or `None` for `off`.

#### 6. Faculty demonstration explanation
> "The key stays on the laptop. The provider sends exactly one request per attempt with a deadline of at least ten
> seconds, and converts every error into a clear category so the phone always has something sensible to say."

#### 7. Possible faculty questions
- **Why the mock provider?** Tests and demos can simulate success, 503, timeouts or slow replies with no internet and
  no cost (`NEUROSONIC_VISION_MOCK_SCRIPT`).
- **Which model?** Configurable; default `gemini-3.8-flash` (the owner's choice).
