# NeuroSonic: integrated prototype app

NeuroSonic is becoming a **voice-first, offline-capable assistive navigation and environmental-awareness
system** for people with visual impairments, built incrementally on the WOAD research implementation. Today it
is a mobile-first web app served from the laptop. It provides:

* a **local neural voice** (Piper, Indian English) generated on the laptop and played on the phone, with the
  browser voice as fallback;
* an **offline map of Vellore** with offline place search and **walking routes with spoken turn-by-turn
  guidance**;
* WOAD obstacle detection on recorded IR + depth data, with alerts;
* browser GPS, local history, and an optional webcam event-camera simulation.

What is verified, and where, is listed in [`FEATURE_STATUS.md`](FEATURE_STATUS.md), including the acceptance
tests still pending on the iPhone. The product direction and priorities are in
[`ARCHITECTURE_AND_ROADMAP.md`](ARCHITECTURE_AND_ROADMAP.md).

> **Assistive research prototype.** It can miss obstacles and give false alarms; measured person recall on
> unfamiliar scenes is low (docs/EVALUATION.md). It detects only person / E-bike / car, and nothing like steps,
> poles, kerbs or holes. **Not a replacement for a cane, guide dog or human assistance.**

## Start

```bat
cd F:\Projects\WOAD-Research\implementation
..\.venv\Scripts\python neurosonic_app.py
:: open http://127.0.0.1:8765 in a browser on this laptop
```

**Phone on the same Wi-Fi:** see [Phone access](#phone-access-iphone--android) below. The short
version is to run the start command, fix the firewall once, and install the local CA once:

```bat
..\.venv\Scripts\python neurosonic_app.py --host 0.0.0.0 --https
```

## Phone access (iPhone / Android)

### Diagnosis of the "iPhone stays loading" report (2026-11-02)

Three independent causes were found by inspection and reproduction:

1. **Server: one stalled TLS handshake froze the whole HTTPS server.**
   * The cause: the listening socket was TLS-wrapped, so every handshake ran inside `accept()` on the
     main thread.
   * Reproduced: with one idle TCP connection open, every other HTTPS request timed out after 8 s,
     then worked again once it closed.
   * Phones trigger this all the time, through speculative pre-connects and connections held
     while a certificate warning is shown.
   * **Fixed:** handshakes now run per connection in worker threads with a 10 s timeout, and idle
     requests time out after 60 s (`NeuroSonicHTTPServer`).
2. **Certificate rejected by iOS.**
   * The old certificate had only a Common Name and was marked CA:TRUE. It had no
     subjectAltName and no serverAuth extended key usage.
   * Since iOS 13, Apple requires both (and a validity of ≤ 825 days); connections to servers
     that violate this fail.
   * **Fixed:** `neurosonic/tls.py` creates a local CA plus a server certificate with SAN
     (LAN IP, 127.0.0.1, localhost, host name), serverAuth, CA:FALSE and 397-day validity. The
     phone trusts the CA once; browser security is not disabled.
3. **Windows Firewall dropped the phone's connections** (this also explains why plain HTTP failed
   the same way).
   * The laptop's Wi-Fi network is classified **Public**, the firewall is on, and **no inbound
     rule** allows Python or the app's ports.
   * Connections from the laptop to itself are not filtered, which is why the laptop works.
   * Changing this needs an administrator, so the app **does not** change it. At start-up it
     detects the situation and prints the exact commands.

Also fixed:

* Explicit MIME types for all assets.
* iOS audio/speech unlock on the first tap.
* No `??` or `?.` syntax, so older iOS WebKit can parse the scripts.
* A visible message if the scripts fail to start.

### One-time setup

1. **Firewall.** In PowerShell, *Run as administrator*. Home or trusted Wi-Fi only:
   ```powershell
   Set-NetConnectionProfile -InterfaceAlias "WiFi" -NetworkCategory Private
   New-NetFirewallRule -DisplayName "NeuroSonic LAN" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765,8766 -RemoteAddress LocalSubnet -Profile Private
   ```
   To undo:
   ```powershell
   Remove-NetFirewallRule -DisplayName "NeuroSonic LAN"
   Set-NetConnectionProfile -InterfaceAlias "WiFi" -NetworkCategory Public
   ```
2. **Start the app:**
   ```bat
   ..\.venv\Scripts\python neurosonic_app.py --host 0.0.0.0 --https
   ```
   * It prints the phone URL, the setup URL (port 8766) and the CA fingerprint.
   * The start-up check should no longer print `!` warnings.
3. **iPhone, in Safari** (iOS installs certificate profiles only from Safari):
   1. Open `http://<laptop-ip>:8766` and tap *Download the NeuroSonic certificate*, then *Allow*.
   2. Settings → General → VPN & Device Management → *NeuroSonic Local CA* → Install.
   3. Settings → General → About → Certificate Trust Settings → enable *NeuroSonic Local CA*.
   4. Compare the fingerprint shown under "More Details" with the one printed by the laptop.
4. **Open `https://<laptop-ip>:8765`** in Safari or Chrome. No certificate warning should appear.
   * Allow Location and Camera when asked.
   * Chrome on iOS also needs iOS Settings → Chrome → Location (While Using) and Camera.
   * Tap once anywhere so iOS enables sound.

`data/tls/` keeps the CA private key. The CA is reused across restarts, and the server certificate is
re-issued automatically if the laptop's IP changes, so the phone stays set up. Keep `data/` private.
Remove the profile from the phone when you no longer need it.

If it still does not load:

* Phone and laptop must be on the **same** Wi-Fi.
* Disconnect any VPN (a HotspotShield adapter is installed on this laptop).
* Some routers enable "client/AP isolation" on guest networks.
* Check that the URL uses the IP printed by the app.

No new Python packages are needed (standard library HTTP server and SQLite). The UI uses no
external CDN or fonts. Everything except the optional OpenStreetMap link works without internet.

## Features and status

| Feature | Status | How it works |
|---|---|---|
| Mobile-first responsive UI (refined 2026-11-02) | ✅ Chrome iPhone emulation · ⏳ Safari on a real iPhone | compact bottom bar: **Home** (awareness), **Navigate**, central **🎤 Speak**, **History**, **Settings**, **How it works**; research tools (WOAD replay, image pair, event-camera simulation) open from Settings; safe-area insets; touch targets ≥ 40 px; `aria-live` alert banner; badges for GPS, voice, laptop connection and internet |
| **How It Works** tab | ✅ | 10 topics in simple language + architecture diagram (iPhone → app → laptop → detection / speech recognition / routing → voice); states that the phone depends on the laptop over a local network |
| Permissions + offline status | ✅ Chrome · ⏳ iPhone | Settings shows camera / microphone / location permission state with "Allow" buttons, and which engines are available on the laptop |
| WOAD detection, replay | ✅ working | server replays `detec_test` (or `reconstructed_val`, or the dark sensor recording) in real time through quality check → detector → alert engine; annotated IR \| depth frame, detections and quality shown live |
| WOAD detection, single pair | ✅ working | upload an IR + colour-depth pair; returns detections, alert text, annotated image |
| Live CS30 sensor | ⏳ **not implemented** | needs the sensor (roadmap Stage 3). The phone camera is **not** used for WOAD: the model needs IR + depth |
| **GPU perception** (2026-11-03) | ✅ laptop, fake camera · ⏳ iPhone | from `..\.venv-gpu`: RF-DETR Nano on the NVIDIA GPU (SSDLite CPU fallback), tracking with camera-motion compensation, spoken entering / crossing events, 200 ms frame interval. Details: [`NEUROSONIC_FINAL_TECHNICAL_DOCUMENTATION.md`](NEUROSONIC_FINAL_TECHNICAL_DOCUMENTATION.md) |
| **Live phone-camera awareness: Walking Guidance** (default) | ✅ recorded frames / Chrome fake camera · ⏳ iPhone/streets | Home → *Start* (or say "start awareness"). The phone sends a small JPEG about every 400 ms (one request at a time, none while the page is hidden). SSDLite320-MobileNetV3 (COCO, mAP 21.3) detects objects; `neurosonic/pathguide.py` compares them with the lower-central walking-path region and speaks only state changes: "The visible path appears clear. Continue carefully." / "Caution. An object is detected in the walking path." / "Stop. The walking path may be blocked." / "I cannot clearly assess the path. Please check carefully." / "Camera view is unavailable." Clear needs 3 good frames; warnings 2 of 3; dark or blurred images are never clear. **Not WOAD, not validated, no distance**; it cannot see steps/kerbs/holes/poles |
| **Online scene description** (Sprint 1, cloud, opt-in) | ✅ mock provider in Chrome · ⚠ live Gemini request timed out · ⏳ iPhone | Home → *Describe* (optional question) or say "describe surroundings": one photo goes from the laptop to the cloud model (default `gemini-3.8-flash`) and the answer is spoken as "AI description: …". Off until allowed; no images stored; no distances or safety claims; failures spoken ("…unavailable right now. Local walking guidance continues."). Details: [`ONLINE_VISION.md`](ONLINE_VISION.md) |
| **Object Description** (optional) | ✅ | switch on Home or Settings: object names with side ("Person on the left.") are spoken in addition, never interrupting |
| **Carrying modes** | ✅ | Settings → chest (walking-path wording, "Person ahead") or handheld ("…in front of the camera", "Person in camera view, left", never "ahead") |
| Neural voice (primary) | ✅ laptop browser · ⏳ **iPhone not yet verified** | the laptop synthesises WAV with Piper 1.8.0 + `en_IN-spicor` voice (`/api/tts`, cached, HTTP Range for iOS). The phone fetches it as a blob and plays it through one `<audio>` element unlocked by the first tap. **Test Voice** speaks "Hello. This is NeuroSonic. Your voice assistant is working correctly." Speaking indicator + error status in Settings. Each playback result is reported to the laptop console (`[voice] … PLAYED`) |
| **Offline voice commands** | ✅ laptop browser · ⏳ iPhone | the big **🎤 Speak** button (every screen) records until you stop talking. The laptop recognises it offline (Vosk, Indian English) and runs: *navigate to / search for <place>*, *start / stop navigation*, *repeat instruction*, *start / stop awareness*, *status*, *help*, *test voice*. Fixed commands are reliable; **spoken place names are often misheard**, so the chosen place is spoken back and guidance waits for "start navigation" |
| Voice alerts / fallback | ✅ working | priority queue (urgent > system > obstacle > motion/navigation); **urgent and obstacle warnings interrupt routine speech**, and the interrupted instruction is re-played once; no overlap, de-duplication, stale messages dropped (obstacle 4 s, navigation 15 s); if the neural voice fails or is unavailable, the browser's `speechSynthesis` speaks instead; voice/rate/volume settings stored in the browser |
| Audio tones | ✅ working | short WebAudio tones, simple stereo pan left/centre/right by alert position, different pitch for system/obstacle/motion. This is **not** 3-D spatial audio |
| GPS location | ✅ working (browser) | `watchPosition`, accuracy display. Permission denied, no signal, timeout and insecure page are reported and spoken. Fixes older than 30 s pause guidance (an old position is never shown as current) |
| Offline map (Vellore) | ✅ laptop browser | `maps/vellore` (OSM, 12.86–13.00 °N, 79.07–79.21 °E) drawn on a canvas, with no tiles or internet: roads by class, water, green, rail; dashed coverage box; spoken message when outside the area. Buildings not included (download failed) |
| Offline place search | ✅ | 813 names (places + named streets), `/api/map/search` |
| Offline walking route + turn-by-turn voice | ✅ simulated walk · ⏳ real walk | A* on the OSM walking graph (`neurosonic/maps.py`); steps with turn direction, street name, distance and a major-road warning; while walking: "In about 60 metres: turn left…", then "Turn left…"; off-route after 2 fixes → recalculation; arrival. A labelled **simulated position** lets you test on the laptop |
| Destination + straight-line guidance | ✅ basic (fallback) | saved places (SQLite) or typed coordinates → distance and compass direction, used when no offline route exists (e.g. outside Vellore) |
| Online walking route link | 🔗 optional | "Open a walking route in OpenStreetMap" (needs internet) |
| Voice destination input / phone carrying modes / facing direction | ⏳ **not implemented** | see FEATURE_STATUS.md |
| Event-camera simulation | ✅ working (demo) | webcam → 160×120 grey → frame differencing (ON/OFF events, DVS-style image) → motion per left/middle/right third → "Motion ahead." etc. with a 2-frame confirmation, 4 s cooldown and a "whole image changing" guard. **Clearly labelled as a simulation, not the WOAD model, not obstacle detection.** Frames never leave the browser |
| History + statistics | ✅ working | every alert (replay, upload, event sim, navigation) stored in local SQLite `data/neurosonic.sqlite3`; History tab with per-class and per-source counts; clear button |
| Installable PWA / native Android | ⏳ not implemented | no manifest or service worker yet; works as a normal mobile web page |

## Architecture

```
phone / laptop browser (web/)                              neurosonic_app.py (Python, laptop)
 ├─ app.js      UI, polling, glue                         ├─ neurosonic/server.py   HTTP(S) API + static files
 ├─ speech.js   SpeechQueue + Announcer:                  ├─ neurosonic/tts.py      Piper neural voice → WAV (cached)
 │              neural <audio> playback, browser fallback ├─ neurosonic/maps.py     offline map: search, A* walking routes
 ├─ nav.js      straight-line guidance + route following  ├─ neurosonic/service.py  WOAD detection: replay + upload
 ├─ mapview.js  offline canvas map                        ├─ neurosonic/store.py    SQLite (alerts, places)
 └─ eventsim.js frame differencing (demo)                 └─ neurosonic/tls.py, netcheck.py   phone HTTPS + firewall check
                                   data: models/tts/en_IN-spicor (voice) · maps/vellore (OSM package) · weights/best.pt (WOAD)
```

API summary is in the `neurosonic/server.py` docstring. Main endpoints:

* `/api/status`, `/api/events?since=`, `/api/replay/{start,stop,state,frame.jpg}`, `/api/detect`, `/api/alerts`
* `/api/history`, `/api/stats`, `/api/places`
* `/api/tts`, `/api/tts/status`, `/api/voice/report(s)`
* `/api/map/{info,data,search}`, `/api/route`

What needs internet: **nothing**, except the optional OpenStreetMap link. The voice, map, search, routing,
detection and history all run from local files. This was tested with network access blocked, not with the
network physically disconnected (FEATURE_STATUS.md, test O1).

Safety behaviour:

* Object alerts come only from the alert engine, i.e. from current detections at confidence
  ≥ 0.40. They are confirmed over frames for replay; a single upload needs no confirmation.
* Unusable input gives "Obstacle detection unavailable: …".
* If the server is unreachable, the page says and speaks "Obstacle detection unavailable: app
  server not reachable".
* Client-side alerts (event sim, navigation) are logged but never re-spoken from the server.

## Tests

`python -m unittest discover -s tests -t .` runs **141 tests** (2026-11-02, all OK). Added in the product
refinement: `tests/test_pathguide.py` (20), `tests/test_refinement_ui_nav.py` (7) and
`tests/js/refinement.test.mjs` (12 Node tests); `ui_refine_cdp.mjs` checks the interface at iPhone size
(see `PROJECT_DOCUMENTATION/16_PRODUCT_REFINEMENT.md`). The earlier 114 tests were:

* 64 existing tests;
* `tests/test_final_integration.py` (15):
  * the intent parser; fixed voice commands from speech (8/8); saved-place resolution;
  * bad-audio rejection; voice commands with the internet blocked;
  * camera awareness: detection and 2-frame confirmation on real frames, handheld wording, dark frames,
    the "Caution" heuristic, bad input, offline;
  * the new API endpoints;
* `tests/test_voice_and_map.py` (14):
  * the Piper acceptance sentence is real audio (5.3 s, 22.05 kHz, non-silent); cache and limits;
  * voice and routes work with all non-local network access blocked (`tests/_offline.py`, which is itself tested);
  * map coverage and search; A* equals Dijkstra; island and outside-area handling;
  * `/api/tts` with HTTP Range (200/206/416); map and route endpoints; voice reports;
* `tests/test_mobile_access.py` (11): an idle connection must not block HTTPS clients (fails on the old server); certificates meet the iOS rules and verify by IP and host name; the CA is kept and the server certificate re-issued when the IP changes; MIME types across the whole module graph; LAN binding; the setup page serves only the CA; the firewall check (mocked); no `??` or `?.` syntax;
* `tests/test_app.py` (8): a real server on a free port; status, upload detection, bad input,
  places CRUD and validation, client alerts and stats, error codes, path-traversal rejection,
  replay stream with frames and alert events;
* `tests/test_web_js.py`: runs `tests/js/web_logic.test.mjs` (15 Node tests: speech queue,
  navigation maths and guidance, route following, frame differencing, motion alerter, the silent
  unlock WAV). Skipped if Node.js is missing.

**Voice + map end-to-end in a real browser** (app must be running; Chrome cannot resolve any internet host
during the test):

```bat
node tests/js/ui_voice_map_cdp.mjs http://127.0.0.1:8765 "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

Result on 2026-11-02: **PASS**.

* A real tap on Test Voice played the acceptance sentence in the neural voice (5.24 s to `ended`). The server
  logged it as PLAYED.
* The map loaded; search found CMC Hospital; guidance from a simulated start at Katpadi gave spoken
  turn-by-turn steps over 264 simulated 20 m steps and announced arrival.
* All 144 requests went to the local app, with 0 external requests and 0 JavaScript errors.
* Because the simulation moves about 600 times faster than walking, most instructions are dropped as stale.
  That is intended: an outdated instruction is never spoken.

Bugs this end-to-end test found and fixed:

* The first tap changed the header badge text and therefore the layout, so the Test Voice click was
  swallowed. The header and alert now have fixed heights.
* The map canvas was sized while its tab was hidden, which made it blurry. A `ResizeObserver` fixes it.
* The search box was unreadable (white on white).
* The simulated walk got stuck on long route segments.
* On Windows a second NeuroSonic instance could bind the same port silently (SO_REUSEADDR), and a stale old
  instance then answered requests (new endpoints returned 404). The port is now bound exclusively, so a second
  start fails with "is the app already running?" (`test_second_instance_cannot_share_the_port`).

Manual UI smoke test with a real headless Chrome and its fake camera (app must be running):

```bat
node tests/js/ui_smoke_cdp.mjs http://127.0.0.1:8765 "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

Result on 2026-11-02: PASS.

* The camera ran and produced event pixels, with motion in the middle third.
* "Motion ahead." alerts reached the SQLite history.
* There was no horizontal overflow at phone width and no JavaScript errors.
* Replay alerts were spoken and stored.

**Final integration end-to-end in a real browser** (`tests/js/ui_final_cdp.mjs`). It uses Chrome's fake
microphone and camera; create the media with `python tools/make_e2e_media.py --out <dir>`.

Result on 2026-11-02: **PASS**, checking all of the following:

* Test Voice played.
* An urgent warning interrupted a navigation message, which was then re-played.
* The spoken command "navigate to Katpadi Junction" (heard as "navigate took out body junction") set the right
  destination and planned a route, and guidance waited for "start navigation".
* The fake camera's people produced a spoken "Person …" alert.
* 0 external requests and 0 JavaScript errors.

Not tested here: a real phone (**including whether the iPhone actually speaks, hears commands and streams camera
frames**), real GPS movement, audible
output (headless has no speakers), Safari/iOS, and a physically disconnected network.

## Known limitations

* Detection quality is the WOAD model's (see EVALUATION.md). The app adds no accuracy. No obstacle detection
  runs on the phone's camera.
* The neural voice runs on the laptop: the phone must reach the laptop over Wi-Fi. If it can't, the phone
  falls back to its own voice. iOS needs one tap before any audio plays (a welcome message confirms sound).
* Routes come from OSM street data only: no pavements, crossings, traffic or obstacles; many unnamed streets.
  Phone GPS accuracy is typically 5–20 m in cities. Real walking guidance has not been field-tested.
* Licences: Piper is GPL-3.0+, the voice model is AGPL-3.0, OSM data is ODbL (attribution shown).
  See `models/tts/README.md` and `maps/vellore/README.md`.
* `data/` holds the local database and the self-signed TLS key. Keep it private and do not
  commit it.
