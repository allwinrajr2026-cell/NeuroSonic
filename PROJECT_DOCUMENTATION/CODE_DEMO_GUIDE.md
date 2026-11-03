# CODE_DEMO_GUIDE: what to open during the faculty demonstration

All paths are relative to `F:\Projects\WOAD-Research\implementation\`. The line numbers come from
`SYMBOL_INDEX.md`, generated from the code on 2026-11-02. In VS Code, use `Ctrl+P` to open a file and `Ctrl+G`
to jump to a line.

## 0. Before the panel arrives (5 minutes earlier)

```bat
cd F:\Projects\WOAD-Research\implementation
:: 1. tests are green (about 1.5 minutes)
..\.venv\Scripts\python -m unittest discover -s tests -t .
:: 2. start the app on the laptop (browser demo):
..\.venv\Scripts\python neurosonic_app.py
::    or for a phone on the same Wi-Fi (needs the one-time firewall rule + CA install, see 12_HTTPS_NETWORK_IPHONE.md):
..\.venv\Scripts\python neurosonic_app.py --host 0.0.0.0 --https
```

* **Start-up check:** the console must show the following lines as ready:
  * "Voice: Piper 1.8.0 - en_IN-spicor";
  * "Offline map: vellore …";
  * "Voice commands: offline Vosk … ready";
  * "Camera awareness: SSDLite320-MobileNetV3 (COCO) ready".
* **Browser:** open `http://127.0.0.1:8765` in Chrome. Tap once anywhere (sound unlock).
* **If the port is busy:** "ERROR: cannot listen … is the app already running?" means an old instance is still
  running. Stop it first.

## 1. Architecture and start-up (1 minute)

| Open | Show |
|---|---|
| `PROJECT_DOCUMENTATION/02_SYSTEM_ARCHITECTURE.md` | the Mermaid deployment diagram: laptop = engines, phone = thin client |
| `neurosonic_app.py` L28–139 (`main`) | the order of loading: TLS → Store → `DetectionService` → `PiperTTS.warm_up` → `OfflineMap` → `VoiceCommands.warm_up` → `RGBAwareness.warm_up` → `make_server` |
| `neurosonic/server.py` L392–402 | the `GET`/`POST` routing tables: every API endpoint in 10 lines |

## 2. Research foundation: WOAD (1 minute)

| Open | Show / say |
|---|---|
| `woad/arch/yolo.py` L165–223 (`Model._forward_once`) | two streams (`model1` depth stem L166–167, IR through `self.model`); fusion at `i == 2` (L175): 0.5/0.5 gate, 8×8 pooling to tokens, `pos_emb`, `trans_blocks`, re-weighting, concatenation |
| `woad/arch/yolo.py` L131–148 (`SelfAttention.forward`) | Q·Kᵀ/√d, softmax, ·V: cross-modal attention |
| `woad/model_loader.py` L90–93 | SHA-256 check of the checkpoint |
| `woad/preprocess.py` L62–75 | IR resize + letterbox; depth `medianBlur(3)` + letterbox |
| `docs/EVALUATION.md` §4 | honest accuracy: person AP@0.5 0.218 (cross-dataset); the 0.669 cannot be reproduced |

## 3. Obstacle alerts (1 minute)

| Open | Show / say |
|---|---|
| `woad/alerts.py` L33–62 (`AlertConfig`) | thresholds: `alert_conf` 0.40, `confirm_hits`/`confirm_window` 2/3, cooldown 5 s, repeat 15 s |
| `woad/alerts.py` L140–249 (`AlertEngine.process`) | the unavailable/resume logic, IoU tracking, 2-of-3 confirmation, left/ahead/right, merging "2 people detected ahead" |
| `neurosonic/awareness.py` L145–156 (`detect`) | SSDLite on a 320 px frame; only obstacle classes; score ≥ 0.40 |
| `neurosonic/pathguide.py` (`assess_frame`, `PathGuide.update`) | walking-path region, side vs centre, 2-of-3 / 3-of-3 confirmation, "prefer uncertain to a false clear"; **not a distance** |
| `neurosonic/awareness.py` L50–53 (`MODES`) | chest vs handheld wording |

## 4. Voice output (1 minute)

| Open | Show / say |
|---|---|
| `neurosonic/tts.py` L95–130 (`synthesize`) | SHA-256 cache key; memory → disk → Piper; lock |
| `neurosonic/server.py` L251–268 (`_send_media`) | HTTP 206 byte ranges for iOS |
| `web/js/speech.js` L4–14 | priorities, maximum ages, cooldowns, pause, interrupting categories |
| `web/js/speech.js` L61–74 (`shouldInterrupt`, `requeue`) | urgent warnings interrupt navigation speech; the step is replayed once |
| `web/js/speech.js` L118–135 (`unlock`) | the iOS audio unlock inside the first tap |

## 5. Voice commands (1 minute)

| Open | Show / say |
|---|---|
| `web/js/recorder.js` L42–62 (`EndOfSpeech`) | adaptive noise threshold; stop after 1 s of silence |
| `neurosonic/voicecmd.py` L184–196 (`transcribe`) | **two** Vosk recognisers: grammar + free |
| `neurosonic/voicecmd.py` L74–124 (`parse_intent`) | intents; the grammar decides "navigate" |
| `neurosonic/voicecmd.py` L45–71 (`phonetic`, `place_score`) | "katpadi" and "cut body" both → `ktpt` |
| `web/js/app.js` L832–869 (`runIntent`) | a destination is only *proposed*; guidance starts after "start navigation" |

## 6. Navigation (1 minute)

| Open | Show / say |
|---|---|
| `tools/build_offline_map.py` L51–58 (`walkable`) | which OSM ways are walkable |
| `neurosonic/maps.py` L184–205 (`_astar`) | the whole A* in 22 lines; haversine heuristic; `heapq` |
| `neurosonic/maps.py` L140–182 (`route`) | snapping, island handling (Vellore Fort), distance and duration |
| `neurosonic/maps.py` L41–51 (`turn_word`) | bearing difference → "bear / turn / sharp turn" |
| `web/js/nav.js` L116–159 (`followRoute`) | pre-announce at 70 m, announce at 25 m, off-route on 2 fixes > max(35 m, 1.5 × accuracy), arrival |
| `web/js/app.js` L173–200 (`startLocation`, `onGeoError`) and `web/js/nav.js` `assessFix` | `watchPosition`, spoken GPS errors, fix quality |

## 7. Phone connectivity (30 seconds, if asked)

| Open | Show / say |
|---|---|
| `neurosonic/server.py` L417–455 (`NeuroSonicHTTPServer`) | per-connection TLS handshake (fixes the iPhone hang); exclusive port bind |
| `neurosonic/tls.py` L86–130 (`ensure_certificates`) | local CA; server certificate with subjectAltName + serverAuth (iOS rules) |
| `neurosonic/netcheck.py` L24–57 | firewall/Public-network check; prints the fix, never changes it |

## 8. Tests (30 seconds)

| Open | Show / say |
|---|---|
| terminal output of the test run | `Ran 204 tests … OK` |
| `tests/test_voice_and_map.py` (`test_route_is_shortest_path`) | A* checked against an independent Dijkstra |
| `tests/test_final_integration.py` (`test_fixed_commands_from_speech`) | Piper speech → Vosk → intents (8/8 measured) |
| `tests/_offline.py` | the "no internet" guard used by the offline tests |
| `tests/js/ui_final_cdp.mjs` | the browser E2E: fake microphone/camera, interruption, 0 external requests |

---

## Five-minute live demonstration sequence

Have `CODE_DEMO_GUIDE.md` and the browser side by side.

| Time | Action in the app | What to say |
|---|---|---|
| 0:00–0:30 | Show the console start-up lines | "Everything runs locally on this laptop: WOAD, the RGB detector, Piper voice, Vosk recognition, the Vellore map. No internet is used." |
| 0:30–1:00 | **Settings → 🔊 Test Voice** | It speaks "Hello. This is NeuroSonic. Your voice assistant is working correctly." in the Indian-English Piper voice. Point at the speaking indicator and the console line `[voice] … PLAYED`. |
| 1:00–2:00 | **Settings → Open research tools → WOAD replay → ▶ Start** (detec_test, 4 fps) | Recorded near-IR + depth frames from the original sensor go through quality gate → WOAD → alert engine. Spoken alerts such as "E-bike detected ahead." Say why it's a replay (no CS30 sensor). |
| 2:00–3:00 | **Navigate tab** → search "CMC Hospital" → choose → open "Testing without walking" → "Simulate at map centre" (pan to Katpadi first) → **▶ Start guidance** → "Move 20 m along route" a few times | Offline map (dashed coverage box), A* route drawn, spoken first step, pre-announcement "In about … metres: turn …". Say clearly: **simulated position**. |
| 3:00–3:45 | Tap **🎤 Speak** and say "status" (and, if quiet, "start navigation" / "repeat instruction") | Vosk on the laptop, offline. The status report covers location, map, route, camera and voice. Mention that place names are often misheard, so they are confirmed. |
| 3:45–4:30 | **Home → ▶ Start**, point the laptop webcam at a person, then tap **Object description** | Walking Guidance speaks path states only ("Caution. An object is detected in the walking path." / "Stop. The walking path may be blocked."); the shaded trapezoid is the path region. Object Description adds "Person ahead.". Point out: not WOAD, no distance, not validated; clear means "nothing recognised". End on **How it works** (laptop dependence). |
| 4:30–5:00 | Show the terminal `Ran 204 tests … OK` and `PROJECT_DOCUMENTATION/14_TESTING_AND_RESULTS.md` | Tested vs simulated vs physically verified: the iPhone and street tests are still pending. |

**If something fails live:** say what the app itself reports. For example, "Voice error" falls back to the
device voice, and "Obstacle detection unavailable: IR image too dark" is the quality gate working. Then switch
to the matching browser E2E result in `14_TESTING_AND_RESULTS.md`.
