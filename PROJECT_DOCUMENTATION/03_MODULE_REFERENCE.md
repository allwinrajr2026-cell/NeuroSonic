# 3. Module reference (Python and JavaScript)

Line numbers come from `SYMBOL_INDEX.md`, generated from the code on 2026-11-02. Paths are relative to
`F:\Projects\WOAD-Research\implementation\`.

Each module is described with the same headings: **Problem**, **Why this technology**, **Input → output**,
**Main algorithm**, **Key functions/classes**, **Execution flow**, **Talks to** and **Excerpt**. Modules whose algorithms have their own document (map, GPS, Vosk, Piper, SSDLite, WOAD)
are summarised here and covered in depth in documents 04–09.

---

## A. Server side (laptop, Python)

### A1. `neurosonic_app.py`: application entry point

* **Problem:** start every engine in the right order, with clear status lines, so the operator sees immediately
  what is available.
* **Why:** a single command (`python neurosonic_app.py --host 0.0.0.0 --https`) is easy to demonstrate.
* **Input → output:**
  * Input: command-line flags.
  * Output: a running HTTP(S) server, plus console lines "Voice: …", "Offline map: …", "Voice commands: …",
    "Camera awareness: …".
* **Key functions:** `main` L28–139.
* **Execution flow:** see `02_SYSTEM_ARCHITECTURE.md` §2.2. A failed bind prints
  `ERROR: cannot listen on …: … (is the app already running?)` and returns exit code 2.
* **Talks to:** `neurosonic.server`, `service`, `store`, `tts`, `maps`, `voicecmd`, `awareness`, `tls`,
  `netcheck`.

### A2. `neurosonic/server.py`: HTTP(S) server and REST API

* **Problem:** serve the web app and a JSON/binary API to phones on the LAN, robustly, over HTTPS.
* **Why the standard library:** `http.server.ThreadingHTTPServer` needs no third-party framework. It also gives
  the low-level control that was needed to fix two real bugs: TLS handshakes blocking the server, and
  silent port sharing on Windows.
* **Input → output:**
  * Input: HTTP requests.
  * Output: static files from `web/`, JSON, `audio/wav` (with byte ranges), `image/jpeg`.
* **Main algorithm:** a table-driven dispatcher. `GET` and `POST` dictionaries map paths to handler methods
  (L392–402). `_dispatch` (L133–159) turns exceptions into status codes:
  * `ApiError` → its own code;
  * `TTSError` → 503;
  * `ValueError` or `InvalidInput` → 400;
  * the client disconnecting during the reply → the connection is closed quietly (no response, no traceback);
  * anything else → 500.
* **Key functions/classes:**

  | Name | Lines | Role |
  |---|---|---|
  | `make_handler` | L62–409 | builds the request-handler class around the service objects |
  | `Handler._raw_body` | L91–100 | reads binary uploads (WAV/JPEG) with size and Content-Type checks |
  | `Handler._body` | L102–113 | reads JSON bodies |
  | `Handler._static` | L134–142 | serves static files; rejects path traversal; sets explicit MIME types (`STATIC_TYPES` L49) |
  | `Handler._send_media` | L228–245 | HTTP Range support (206/416) for iOS audio |
  | `NeuroSonicHTTPServer` | L421–459 | performs the TLS handshake per connection in the worker thread (`finish_request` L444–459); exclusive bind on Windows (`server_bind` L435–438) |
  | `make_server` | L435–439 | constructs the server |
  | `make_setup_server` | L442–479 | plain-HTTP page serving only the CA certificate |
* **Execution flow:**
  1. `accept()` returns a plain socket.
  2. A worker thread calls `finish_request`: TLS wrap (10 s handshake timeout), then the `Handler`.
  3. `do_GET`/`do_POST` → `_dispatch` → route method → `_json`/`_send`.
* **Talks to:** every engine object passed to `make_handler` (`service`, `store`, `tts`, `offline_map`,
  `voicecmd`, `awareness`).
* **Excerpt** (L417–432):
  ```python
  def finish_request(self, request, client_address):
      if self.ssl_context is None:
          return super().finish_request(request, client_address)
      request.settimeout(self.handshake_timeout)
      try:
          tls = self.ssl_context.wrap_socket(request, server_side=True)
      except (ssl.SSLError, OSError):
          return  # failed, rejected or timed-out handshake: drop only this connection
  ```

### A3. `neurosonic/service.py`: WOAD detection service

* **Problem:** run the WOAD model for (a) a background **replay** of recorded IR+depth frames and (b) single
  uploaded pairs, and publish alert events to clients.
* **Why:** one model instance shared under a lock (`model_lock`), because PyTorch inference on CPU is not
  re-entrant-safe for concurrent requests.
* **Input → output:**
  * Replay: a set name and fps go in; annotated JPEG frames, state and events come out.
  * Upload: IR and depth bytes go in; detections, quality, alert texts and an annotated JPEG come out.
* **Key classes:**

  | Name | Lines | Role |
  |---|---|---|
  | `decode_image` | L41–56 | the same input rules as `woad.preprocess.read_image` |
  | `EventLog` | L68–96 | ring buffer of events with increasing ids; persists to SQLite |
  | `ReplayRunner(threading.Thread)` | L99–161 | `run` L124–161: quality → detector → `AlertEngine.process` → render → paced by fps |
  | `DetectionService` | L164–234 | `start_replay` L184–195, `detect_upload` L213–234 |
* **Talks to:** `woad.detector.WOADDetector`, `woad.quality.InputQualityChecker`, `woad.alerts.AlertEngine`,
  `woad.sources.ReplaySource`, `store.Store`.
* **Excerpt** (`ReplayRunner.run`, abridged):
  ```python
  q = svc.checker.check(frame.ir, frame.depth)
  if err is None and q.status != UNUSABLE:
      with svc.model_lock:
          dets = svc.detector.detect_arrays(frame.ir, frame.depth)["detections"]
  events = self.engine.process(time=..., detections=dets, quality=q, segment_start=frame.segment_start, error=err)
  ```

### A4. `neurosonic/store.py`: SQLite store

See `11_DATA_STORAGE.md`.

* **Key items:** `SCHEMA` L6; `Store.add_alert` L47–58, `history` L60–64, `stats` L66–74, `add_place` L82–93,
  `delete_place` L99–103.
* **Validation:** a whitelist for `source`/`kind` (`ALLOWED_SOURCES` L28), latitude/longitude range checks and
  SQL CHECK constraints.

### A5. `neurosonic/tts.py`: Piper neural text-to-speech

See `07_TEXT_TO_SPEECH_PIPER.md`.

* **Key items:** `PiperTTS.synthesize` L95–130, `clean` L87–93, `_load` L65–73, `warm_up` L75–83, `info` L43–52.

### A6. `neurosonic/voicecmd.py`: Vosk voice commands

See `06_SPEECH_RECOGNITION_VOSK.md`.

* **Key items:**
  * `parse_intent` L74–124;
  * `phonetic` L45–59 and `place_score` L62–71;
  * `VoiceCommands.transcribe` L184–196, `resolve_place` L199–222, `handle` L224–241.

### A7. `neurosonic/maps.py`: offline map, search, A* routing

See `04_OFFLINE_MAP_AND_ROUTING.md`.

* **Key items:**
  * `OfflineMap.__init__` L59–90 (graph and connected components);
  * `search` L111–137, `route` L140–182, `_astar` L184–205, `_steps` L222–313.

### A8. `neurosonic/awareness.py`: live RGB camera awareness

See `08_RGB_OBJECT_DETECTION_SSDLITE.md`.

* **Key items:** `RGBAwareness.detect`, `quality`, `_session` (alert engine + `PathGuide` per phone session),
  `process_frame` (walking-path state always, object descriptions only with `describe=True`); `OBSTACLE_CLASSES`,
  `MODES`. Line numbers: `SYMBOL_INDEX.md`.

### A8b. `neurosonic/pathguide.py`: walking-path assessment (2026-11-02 refinement)

See `16_PRODUCT_REFINEMENT.md`. `assess_frame` turns detections, quality and sharpness into one frame level;
`PathGuide.update` confirms it over frames (clear 3/3, warnings 2/3, uncertain 2 consecutive) and decides what is
spoken; `box_path_overlap` measures a box against the trapezoid `PATH_POLYGON`.

### A9. `neurosonic/tls.py` and `neurosonic/netcheck.py`: phone connectivity

See `12_HTTPS_NETWORK_IPHONE.md`.

* **Key items:** `ensure_certificates` L86–130, `lan_ips` L36–55, `server_ssl_context` L133–137,
  `windows_report` L24–57.

---

## B. WOAD research package (Python)

### B1. `woad/model_loader.py`: safe checkpoint loading

* **Problem:**
  * The original checkpoint pickles whole Python classes from modules named `models.yolo` / `models.common`.
  * Loading it must not import the broken original training code.
  * It must refuse a wrong or altered file.
* **Main algorithm:**
  1. Compute the SHA-256 and compare it with `EXP72_BEST_SHA256` (L24).
  2. `_legacy_module_aliases` (L46–61) temporarily maps `models.*` to the vendored `woad.arch` classes.
  3. `torch.load(..., weights_only=False)`.
  4. Check the module tree against `EXPECTED_CHILDREN` (L26).
  5. `.float().eval()`; freeze the parameters.
* **Key functions:** `load_model` L76–130, `sha256` L34–42, `select_device` L64–73.
* **Excerpt** (L91–93):
  ```python
  if verify_hash and weights.resolve() == DEFAULT_WEIGHTS.resolve() and digest != EXP72_BEST_SHA256:
      raise CheckpointError(f"Checkpoint {weights} has SHA-256 {digest}, expected exp72 best.pt "
  ```

### B2. `woad/arch/yolo.py` and `woad/arch/common.py`: the network

See `09_WOAD_MODEL.md`.

* `Model._forward_once` L165–223 contains the cross-modal fusion.
* `myTransformerBlock` L85–103 and `SelfAttention` L106–148 implement the transformer.
* `Detect` L37–82 is the YOLO head.
* `common.py` holds `Conv` L22–34, `C3` L50–61, `SPPF` L64–79 and `Concat` L82–89.

### B3. `woad/preprocess.py`: training-faithful input pipeline

* **Problem:** the model only works if the inputs are prepared exactly as during training.
* **Main algorithm:**
  * **IR:** resize the long side to 640 (INTER_AREA when shrinking), then letterbox to 640×640 with padding
    value 114.
  * **Depth:** `medianBlur(3)`, then letterbox.
  * **Both:** BGR→RGB, CHW, /255.
* **Key functions:** `read_image` L36–53 (rejects 16-bit and single-channel depth), `preprocess_ir` L62–69,
  `preprocess_depth` L72–75, `prepare_pair` L87–96, `load_pair` L99–100.
* **Excerpt** (L72–75):
  ```python
  def preprocess_depth(depth_bgr, img_size=IMG_SIZE):
      d = cv2.medianBlur(depth_bgr, 3)
      d, _, _ = letterbox(d, img_size, auto=False)
      return d
  ```

### B4. `woad/ops.py`: letterbox, NMS, coordinate mapping

* `letterbox` L21–51 and `non_max_suppression` L74–158 are the original YOLOv5 versions.
* `scale_coords` L161–174 maps boxes from 640×640 back to the original image.
* `box_iou` L64–71.

### B5. `woad/detector.py`: `WOADDetector`

* **Problem:** a simple API around loading, preprocessing, the forward pass, NMS and box mapping.
* **Key methods:** `raw_forward` L45–47 (calls `model(ir, depth)`), `detect_prepared` L49–72, `detect_arrays`
  L74–75, `detect_files` L77–84.
* **Output:** a list of `{class_id, class_name, confidence, box_xyxy}` in original IR pixel coordinates, plus
  timings.

### B6. `woad/alerts.py`: `AlertEngine` (shared by all alert sources)

* **Problem:** detectors produce many flickering boxes per second. A blind user needs a few correct, stable,
  non-repetitive spoken messages, and must be told when detection is unavailable.
* **Main algorithm** (`process` L140–249):
  1. **Input check:** if the input is unusable or missing, after `unavailable_after_s` say "Obstacle detection
     unavailable: <reason>" (`_go_unavailable` L124–129). After `resume_after_s` of good input, say "resumed".
  2. **Filter:** keep detections with confidence ≥ `alert_conf` (0.40).
  3. **Track:** greedy IoU matching, per class, of detections to existing `_Track`s (IoU ≥ 0.30). Each track
     keeps a hit history over the last `confirm_window` (3) frames.
  4. **Confirm:** a track is confirmed when it has ≥ `confirm_hits` (2) hits.
  5. **Position:** box centre in the left third, middle third or right third.
  6. **Repetition control:** re-announce only if the position changes, or after `repeat_s` (15 s). Within
     `cooldown_s` (5 s), same class + position messages are treated as already covered.
  7. **Merge and rank:** e.g. "2 people detected ahead", ordered by class priority and box size, at most 2
     messages per frame.
* **Key classes:** `AlertConfig` L33–62 (all thresholds, wording), `AlertEvent` L66–77, `_Track` L80–88,
  `AlertEngine` L99–249, `tick` L132–137 (stall watchdog).
* **Talks to:**
  * Fed by `service.ReplayRunner` (WOAD), `service.detect_upload` and `awareness.RGBAwareness` (SSDLite).
  * Results go to clients as events.

### B7. `woad/quality.py`: input quality gate

* **Problem:** the brightness experiment showed that darkening input removes about 73 % of WOAD detections and
  produces false "person" alarms (`docs/EVALUATION.md` §8).
* **Algorithm** (`InputQualityChecker.check` L55–82), on IR mean and standard deviation:
  * **UNUSABLE:** mean < 40, std < 10, or more than 95 % of depth pixels invalid;
  * **WARN:** mean < 100 or std < 40;
  * otherwise **OK**.
* **Output:** `QualityReport(status, reasons, ir_mean, ir_std, depth_invalid)` (L37–48).

### B8. `woad/sources.py`, `woad/replay.py`, `woad/pairing.py`

* **`ReplaySource`** (`sources.py` L42–88): yields `Frame` objects (L25–34) with synthetic timestamps
  (index/fps) and clip *segments* detected from filename-number gaps.
* **`run_replay`** (`replay.py` L7–34): the offline replay pipeline used by `woad_replay.py`.
* **`pair_directories`** (`pairing.py` L46–77): pairs IR and depth files by exact filename, with clear errors
  for unpaired files.

### B9. `tools/build_offline_map.py`: offline map builder

See `04_OFFLINE_MAP_AND_ROUTING.md`.

* `build` L72–190: raw Overpass JSON → `map.json`, `graph.json`, `places.json`, `manifest.json`.
* `walkable` L51–58: the walking filter.

---

## C. Client side (browser, JavaScript ES modules in `web/js/`)

### C1. `app.js`: application glue (657 lines)

* **Problem:** connect the UI, sensors, server API, speech and navigation into one voice-first flow.
* **Sections (line numbers):**

  | Section | Lines | Content |
  |---|---|---|
  | settings and voice | L10 | `DEFAULTS` (incl. `describe`), `Announcer`, `lastNavText` |
  | screens | L42 | `showTab` (also opens the research-tools screen) |
  | server / network status | L60 | `init`, `pollEvents` (every 1 s; 3 s while hidden) |
  | WOAD replay (research tools) | L106 | — |
  | single-pair upload (research tools) | L137 | — |
  | GPS | L153 | `renderGps` L160, `startLocation` L173, `onGeoError` L188, `onFix` L204, `onPosition` L219, loss timer L224–230 |
  | saved places + straight-line fallback | L232 | `updateGuidance` |
  | offline map, search, route | L287 | `loadMap` L292, `runSearch` L326, `chooseDestination` L342, `planRoute` L353, `followActiveRoute` L402, simulated position L421–434 |
  | event-camera simulation (research tools) | L436 | — |
  | history | L481 | `loadHistory` |
  | camera awareness: Walking Guidance | L498 | `setPathState`, `cameraUnavailable`, `startAwareness` L541, `awarenessStep` L580, `drawAwareness` L638, `setDescribe` |
  | status report | L783 | `statusReport` L784 |
  | voice commands | L803 | `checkVoiceCommands` L806, `listenOnce` L817, `runIntent` L842 |
  | permissions + offline status | L872 | `checkPermissions`, `askMedia`, `renderOffline` |
  | settings UI | L926 | `updateVoiceBadge` L934, `checkVoiceEngine` L953, Test Voice handler L982 |
* **Communication:** `api()` (L32) wraps `fetch` for JSON. Binary uploads (WAV, JPEG) use `fetch` directly.

### C2. `speech.js`: speech queue and announcer

* **Problem:** speak the most important message first, never overlap, never speak outdated warnings, cut off
  routine speech for urgent warnings, and work on iOS.
* **Main algorithm:**
  * `SpeechQueue` (L18) is a priority queue (`PRIORITY` L4: urgent 4 > system 3 > obstacle 2 >
    motion/navigation 1 > info 0).
  * **De-duplication:** the same text is dropped within 4 s (`push` L34).
  * **Stale-dropping:** `next` (L47) skips items older than `MAX_AGE_MS` (L8).
  * **Interruption:** `shouldInterrupt` (L61) and `requeue` (L68), so an interrupted routine message is
    replayed once.
  * The `Announcer` (L93) plays the neural voice through one `<audio>` element (`_playNeural` L233), falling
    back to `speechSynthesis` (`_playBrowser` L260).
  * `unlock()` (L118) runs inside the first tap to satisfy iOS.
* **Excerpt** (L61–65):
  ```js
  shouldInterrupt(current, category) {
    if (!current || !INTERRUPTING[category]) return false;
    const p = category in PRIORITY ? PRIORITY[category] : 0;
    return p > current.priority;
  }
  ```

### C3. `nav.js`: navigation mathematics

* **Content:**
  * `distanceM` L7 (haversine), `bearingDeg` L13, `compass` L20, `parseCoords` L30;
  * `guidance` L42 (straight-line fallback);
  * `projectOnPolyline` L73, `pointAtAlong` L90, `prepareRoute` L108, `followRoute` L116.
* All functions are pure, so they are unit-tested in Node. See `05_GPS_AND_ROUTE_FOLLOWING.md`.

### C4. `mapview.js`: offline map renderer

* **Content:**
  * `MapView` (L7) draws `map.json` on a `<canvas>`.
  * **Projection:** equirectangular around the map centre (`_xy` L68: x = Δlon·111 320·cos(lat)/mpp,
    y = −Δlat·110 540/mpp).
  * **Interaction:** drag, pinch, wheel (`_bind` L80); `ResizeObserver` for canvases created in hidden tabs.
  * **Drawing** (`_draw` L145): coverage box, layers, route, destination, position, scale bar, OSM attribution.

### C5. `recorder.js`: push-to-talk capture

* **Content:**
  * `recordUtterance` (L65): `getUserMedia(audio)` → `ScriptProcessorNode`, chosen because iOS supports it.
  * `EndOfSpeech` (L42): learns background noise, threshold = max(0.01, 3×noise); ends after 1 s of quiet once
    ≥ 250 ms of speech has been heard, or at 6 s.
  * `downsample` (L9) to 16 kHz by averaging; `encodeWav` (L21) to 16-bit PCM WAV.
* See `06_SPEECH_RECOGNITION_VOSK.md`.

### C6. `eventsim.js`: event-camera simulation (demonstration only)

* **Problem:** show the idea of an event camera (pixels reporting brightness *changes*) with an ordinary webcam.
* **Algorithm:**
  1. `toGray` (L5) converts each frame to grey.
  2. `diffEvents` (L12) marks ON/OFF events where |Δ| > threshold and returns the event fraction per
     left/middle/right third.
  3. `MotionAlerter` (L32) needs 2 consecutive frames above 4 % and has a 4 s cooldown, plus a guard that
     reports "whole image changing" when all thirds exceed 25 %.
* **Status:** clearly labelled in the UI as **not** obstacle detection and **not** the WOAD model.
