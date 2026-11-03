## E1. File: web/index.html {: .file}

#### 1. Purpose
The single web page of the app. It defines all screens, buttons, status badges and the spoken-alert banner, and loads
`style.css` and the JavaScript module `app.js`.

#### 2. How it is organised
- `<meta name="viewport" content="…, viewport-fit=cover">` lets the page use the whole iPhone screen (notch area).
- **Header:** status badges `b-gps`, `b-voice`, `b-det` (laptop server), `b-net` (internet).
- **Alert banner** `#alert` with `role="status" aria-live="assertive"` – screen readers (VoiceOver) read new alerts.
- **Screens** (`<section class="tab">`): `tab-detect` (Home: camera, path-state card, Start/Stop, detector chip,
  Object Description switch, Describe surroundings), `tab-nav` (Navigate: map, search, route, guidance, location
  panel), `tab-hist` (History), `tab-set` (Settings: Test Voice, carrying mode, consent, permissions, offline status),
  `tab-how` (How it works), `tab-sim` (Research tools: WOAD replay, image-pair upload, event-camera simulation).
- **Bottom bar** `<nav class="tabs">`: Home, Navigate, the central **Speak** button, History, Settings, How it works.

#### 6. Faculty demonstration explanation
> "The whole interface is one HTML page with six screens. Only one is visible at a time; `app.js` switches them. The
> alert banner is an ARIA live region, so VoiceOver can read every alert too."

#### 7. Possible faculty questions
- **Why a web app and not a native iOS app?** No App Store build was needed, it works in Safari, and all AI runs on
  the laptop. A native app (with LiDAR) is future work.
- **Is it accessible?** Large buttons (min 48 px height), high contrast, ARIA labels and a live region. Not yet tested
  with VoiceOver users.

## E2. File: web/style.css {: .file}

#### 1. Purpose
Mobile-first, high-contrast dark theme for the iPhone.

#### 2. Key parts
- `:root` colour variables (`--bg #0b1020`, `--ok` green, `--warn` orange, `--bad` red, `--accent` yellow).
- Safe-area variables `env(safe-area-inset-*)` keep content clear of the notch and home indicator.
- Touch targets: `button { min-height: 48px }`, map controls 44 px.
- Path-state card colours: `.pathstate.clear` green, `.caution` orange, `.stop` red background, `.unavailable` dashed.
- `@media (min-width: 900px)` for the laptop browser; `prefers-reduced-motion` respected.

#### 6. Faculty demonstration explanation
> "The design is for a phone held in one hand or worn on the chest: big buttons, strong colours that match the spoken
> state – green, orange, red – and nothing hidden under the iPhone's notch."

## E3. File: web/js/app.js {: .file}

#### 1. Purpose
The main frontend program (1,015 lines). It connects the screens, the phone's sensors (camera, microphone, GPS), the
laptop API, the speech queue and navigation into one voice-first flow.

#### 2. How the code works
1. Imports `Announcer` (speech.js), navigation maths (nav.js), `MapView`, `recordUtterance`, event-simulation code.
2. Loads settings from `localStorage` with `DEFAULTS` (L13): neural voice, chest mode, `describe: false`,
   `cloudConsent: false`.
3. `api(path, body)` (L32): a small `fetch` wrapper – GET without body, POST with JSON; throws on HTTP errors.
4. `init()` (L66) calls `/api/status`; `pollEvents()` (L88) asks `/api/events?since=` every 1 s (3 s when hidden)
   and announces WOAD replay events; it also says "Connection to the laptop lost / restored".
5. Status checks on start-up: `/api/awareness/status` (L812), `/api/tts/status`, `/api/map/info`,
   `/api/vision/status`.
6. **Camera awareness:** `startAwareness()` (L541) → `scheduleFrame()` → `awarenessStep()` (L580) repeatedly (see
   Part 9 for line-by-line). `drawAwareness()` (L638) draws the path trapezoid and boxes on an overlay canvas.
7. **Voice commands:** `listenOnce()` (L817) records and posts WAV to `/api/voicecmd`; `runIntent()` (L842) acts on
   the intent (navigate → choose destination and plan route, then wait for "start navigation"; status; repeat; …).
8. **Navigation:** `runSearch()` (`/api/map/search`), `planRoute()` (L353, `/api/route`), `onPosition()` (L219) for
   each GPS fix, `followActiveRoute()` (L402) speaks instructions and re-routes when off route.
9. **History:** `loadHistory()` (L486) loads `/api/stats` and `/api/history?limit=100`.
10. **Online description:** `describeScene(question)` (L737) sends one photo only if consent was given.

#### 3. Important functions

| Function | What it does | Talks to |
|---|---|---|
| `api()` L32 | JSON fetch helper | every JSON endpoint |
| `showTab()` L43 | switch screens, load data for History/Navigate/Settings | DOM |
| `startAwareness()` / `stopAwareness()` L541/L567 | open/close rear camera, start/stop frame loop | `getUserMedia` |
| `awarenessStep()` L580 | capture → JPEG → POST → speak results | `/api/awareness/frame` |
| `renderDetector()` L518 | the "RF-DETR · GPU" / "SSDLite · CPU" chip | response `detector` |
| `listenOnce()`, `runIntent()` L817/L842 | voice command round trip | `/api/voicecmd` |
| `planRoute()`, `followActiveRoute()` L353/L402 | route planning and following | `/api/route`, nav.js |
| `describeScene()` L737 | opt-in cloud description | `/api/vision/describe` |

#### 6. Faculty demonstration explanation
> "This file is the glue on the phone. When I press Start it opens the rear camera, and every 200 milliseconds it
> sends one small JPEG to the laptop, never more than one at a time. The answer contains the path state and any
> sentences to speak, which go to the speech queue. The same file handles voice commands, the map and history."

#### 7. Possible faculty questions
- **Why polling for events instead of WebSockets?** The standard-library server does not support WebSockets easily;
  polling once per second is tiny traffic and survives reconnects. Camera results come back directly in each reply.
- **What if the laptop does not answer?** Each frame request is cancelled after 5 s (`AbortController`); after 3
  failures the app says "Camera view is unavailable".
- **Why 320 px frames?** Small enough for fast upload over Wi-Fi; RF-DETR Nano works at 384 px input anyway.
- **Does the phone store images?** No; each frame is drawn to an off-screen canvas, sent, and replaced.

## E4. File: web/js/speech.js {: .file}

#### 1. Purpose
The speech system: a **priority queue** so the most important message is spoken first, nothing overlaps, outdated
warnings are dropped, and urgent warnings interrupt routine speech. Plays the Piper voice, with the browser voice as
fallback.

#### 2. How the code works
1. `PRIORITY` (L4): urgent 4 > system 3 > obstacle 2 > motion/navigation/scene 1 > info/description 0.
2. `SpeechQueue.push(text, category, now, key)` (L34): skip a sentence said within its `COOLDOWN_MS`; a `key` (e.g.
   `"path"`) makes newer path messages replace older queued ones ("latest wins"); keep at most 6 items sorted by
   priority.
3. `next(now)` (L47) drops items older than `MAX_AGE_MS` (an obstacle warning older than 4 s is not spoken).
4. `Announcer.say()` (L156) pushes the message, plays a short beep (panned left/right), and if a more important
   message arrives while speaking, `interrupt()` stops the current one; an interrupted navigation message is
   re-queued once (`requeue`, L68).
5. `_pump()` (L174) plays the next item: `_playNeural()` fetches `/api/tts?text=` and plays it through one `<audio>`
   element; on failure `_playBrowser()` uses `speechSynthesis`. A 250 ms gap (`GAP_MS`) separates messages.
6. `unlock()` (L118) must run inside the first tap – iOS only allows audio started by a user gesture.
7. `prefetch()` (L211) downloads the fixed warning audio in advance.

#### 6. Faculty demonstration explanation
> "Speech is the user's only output, so it must be prioritised. 'Stop' interrupts a navigation instruction, which is
> then repeated once. Old warnings are dropped because a four-second-old obstacle warning is misleading."

#### 7. Possible faculty questions
- **What happens if Piper is unavailable?** The phone's own voice is used automatically.
- **Why does the user have to tap once?** iOS blocks audio that was not started by a tap; `unlock()` plays a silent
  clip during that tap.

## E5. File: web/js/nav.js {: .file}

#### 1. Purpose
Pure navigation maths (no screen code), so it can be unit-tested in Node.js.

#### 2. Key functions
- `distanceM()` (haversine distance), `bearingDeg()`, `compass()`, `formatDistance()`.
- `assessFix(fix, now)` with `GPS_LIMITS = {staleMs: 15000, poorM: 50, unusableM: 100}`: fixes older than 15 s or
  worse than 100 m are not used.
- `gpsWatch()`: after 20 s without a good fix during guidance → "GPS signal lost. Guidance paused…".
- `projectOnPolyline()`, `prepareRoute()`, `followRoute()` (L116): pre-announce a turn about 70 m ahead, say it at
  25 m, declare "off route" after 2 fixes more than 35 m (or 1.5× accuracy) away, "arrived" within 15 m.
- `canReroute()`: at most one re-route every 15 s.

#### 6. Faculty demonstration explanation
> "Route following projects each GPS position onto the route line, then decides whether to pre-announce a turn, say it
> now, report arrival, or recalculate because the user left the route."

## E6. Files: web/js/mapview.js, recorder.js, eventsim.js {: .file}

#### 1. Purpose and how they work
- **mapview.js** – `MapView` draws the offline `map.json` on a `<canvas>` with an equirectangular projection
  (x = Δlon·111,320·cos(lat), y = −Δlat·110,540 metres), supports drag/pinch/zoom, and draws the route, destination,
  position, scale bar and OpenStreetMap attribution. It redraws sharply for the device pixel ratio.
- **recorder.js** – `recordUtterance()` records from the microphone, `EndOfSpeech` stops after about 1 s of quiet
  (or 6 s maximum), `downsample()` converts to 16 kHz and `encodeWav()` builds a 16-bit mono WAV for Vosk.
- **eventsim.js** – a *demonstration only* "event camera" simulation: `diffEvents()` marks pixels whose brightness
  changed by more than a threshold, and `MotionAlerter` says "Motion on the left/ahead/right". It is labelled in the UI
  as not WOAD and not obstacle detection, and lives under Research tools.

#### 6. Faculty demonstration explanation
> "The map is drawn by our own small renderer, so it works offline. The recorder produces exactly the audio format the
> offline recogniser needs. The event-camera simulation is only a demonstration of the idea."

#### 7. Possible faculty questions
- **Why not Google Maps or Leaflet tiles?** They need internet; our own canvas renderer uses the local map file.
- **Why 16 kHz?** The Vosk model is trained on 16 kHz audio.
