# 16. Viva question bank (63 questions with answers)

The answers reference the actual code (paths relative to `implementation/`). ★ marks the ten most important
questions, also listed in `00_INDEX.md`.

---

## A. Python architecture (Q1–Q7)

**Q1 ★. Describe the overall architecture of NeuroSonic in one minute.**
It is a client–server system on a local network:

* **The laptop** runs `neurosonic_app.py`, a Python HTTP(S) server (`neurosonic/server.py`) that hosts:
  * the WOAD detector (`woad/`);
  * an RGB object detector (`neurosonic/awareness.py`);
  * Piper text-to-speech (`tts.py`) and Vosk speech recognition (`voicecmd.py`);
  * an offline map with A* routing (`maps.py`);
  * an SQLite store (`store.py`).
* **The phone** opens a web page (`web/`) that uses its GPS, camera, microphone and speaker, and talks to the
  laptop through a JSON/binary REST API over HTTPS.
* **Internet:** not needed at runtime.

**Q2. Why did you use Python's standard-library HTTP server instead of Flask or FastAPI?**

* It needs no extra dependencies.
* It gave the low-level control needed to fix two real problems:
  * TLS handshakes blocking the server (handshakes are now done per connection in `NeuroSonicHTTPServer.finish_request`, L444–459);
  * byte-range responses for iOS audio (`_send_media`, L255–272).
* Routing is a simple table of paths → methods (L334–343).

**Q3. How are concurrent requests handled?**
`NeuroSonicHTTPServer` extends `ThreadingHTTPServer`, so each connection gets its own thread.

* **Shared engines are protected by locks:**
  * the WOAD model (`DetectionService.model_lock`);
  * Piper (`PiperTTS._lock`);
  * Vosk (`VoiceCommands._lock`);
  * SSDLite (`RGBAwareness._lock`);
  * SQLite (`Store._lock`).
* Each phone gets its own alert engine for camera awareness (`RGBAwareness._engine`, keyed by session).

**Q4. How does the server turn errors into HTTP responses?**
`Handler._dispatch` (L133–155) catches exceptions:

* `ApiError` → its own code (400/404/413/415/416/503);
* `TTSError` → 503;
* `ValueError` / `InvalidInput` → 400;
* anything else → 500, with the stack trace logged.

The server never crashes on a bad request.

**Q5. What happens at start-up?**
`neurosonic_app.py::main` (L28–139):

1. TLS certificates (if `--https`);
2. the SQLite store;
3. the WOAD model (hash-checked);
4. Piper warm-up;
5. the offline map;
6. the Vosk model;
7. SSDLite warm-up;
8. the server, plus the setup page and firewall check, then `serve_forever`.

**Q6. How do you make sure the original WOAD checkpoint is not altered or replaced?**
`woad/model_loader.py::load_model` (L76–130):

* computes the SHA-256 and compares it with `EXP72_BEST_SHA256` (L24);
* checks the network's module tree against `EXPECTED_CHILDREN`.

The original repository file is never written; the app uses a copy in `weights/`.

**Q7. Why does the client poll `/api/events` instead of using WebSockets?**

* Polling every second (`app.js::pollEvents`, L88) works with the standard-library server.
* It is robust to reconnects, and the traffic is tiny.
* Most alerts in the current app are produced *in the response* to the phone's own request (camera frames,
  voice commands), so polling is only needed for the WOAD replay.

## B. Computer vision basics (Q8–Q13)

**Q8. What is letterboxing and why is it used?**

* **What it does** (`woad/ops.py::letterbox`, L21–51): resizes an image to fit 640×640 while keeping its aspect
  ratio, and pads the rest with grey (value 114).
* **Why:** CNN detectors need a fixed input size, and stretching would distort object shapes.
* **Afterwards:** `scale_coords` (L161–174) undoes the scaling and padding for the boxes.

**Q9. Why is a median blur applied only to the depth image?**
The training code did so (`preprocess_depth`, L72–75). Depth from a time-of-flight sensor has salt-and-pepper
speckle, and a 3×3 median filter removes it while keeping edges. Matching the training preprocessing is
essential; removing it makes tests fail.

**Q10. What does non-maximum suppression do?**
A detector proposes many overlapping boxes for one object. NMS:

1. sorts the boxes by score;
2. keeps the best one;
3. removes the others of the same class whose IoU with it is above a threshold (0.45 in the app);
4. repeats.

See `woad/ops.py::non_max_suppression` (L74–158).

**Q11. What is IoU?**
Intersection over Union: the area of overlap of two boxes divided by the area of their union, from 0 to 1. It
is used:

* in NMS;
* to match predictions to ground truth in mAP (≥ 0.5 for AP@0.5);
* to track objects across frames in the alert engine (≥ 0.3).

**Q12. How does the app decide whether an object is left, ahead or right?**
By the horizontal centre of the box: the left third, middle third or right third of the image
(`AlertEngine._bucket`, `woad/alerts.py` L113–115). In handheld mode the words become "in camera view, left /
centre / right".

**Q13. Why do you check image brightness before detection?**
The IR-brightness experiment showed that dark input removes about 73 % of WOAD detections and causes false
alarms. `woad/quality.py` (and `awareness.py::quality` for RGB) marks such frames UNUSABLE, and the app says
"Obstacle detection unavailable" instead of guessing.

## C. CNN and object detection (Q14–Q19)

**Q14. What is a convolutional neural network?**
A network of learned filters (convolutions) that slide over the image to detect local patterns: edges, then
textures, then object parts. Stacking layers with downsampling gives features that describe larger regions.
Detection heads then predict classes and boxes from those features.

**Q15. What is the difference between single-stage and two-stage detectors?**

* **Two-stage** (e.g. Faster R-CNN): first propose regions, then classify each one. Accurate but slower.
* **Single-stage** (YOLO, SSD): predict classes and boxes for a fixed grid of anchors in one pass. Faster, which
  suits real-time and wearable use.

WOAD (YOLOv5-based) and SSDLite are both single-stage.

**Q16. What is an anchor box?**
A pre-defined box shape at each feature-map position. The network predicts an offset from the anchor and a class
score. WOAD's YOLOv5 head uses 3 anchors per position at 3 scales: (80² + 40² + 20²) × 3 = 25,200 candidate
boxes per image, which is the output shape (B, 25200, 8).

**Q17. What do the 8 numbers per WOAD prediction mean?**
x, y, w, h (box), objectness, and 3 class scores (person, Ebike, Car).

**Q18. What is mAP?**
Mean Average Precision:

1. For each class, the precision–recall curve is computed by sorting detections by confidence.
2. AP is the area under that curve (101-point interpolation in the original YOLOv5 code, `woad/metrics.py`).
3. mAP is the mean over classes.
4. mAP@0.5 counts a detection as correct at IoU ≥ 0.5; mAP@0.5:0.95 averages over IoU thresholds 0.5–0.95.

**Q19. What is MobileNetV3 and why is it fast?**
A CNN designed for phones. Its main tricks:

* **depthwise-separable convolutions:** one filter per channel, then a 1×1 convolution to mix channels;
* inverted residual blocks;
* squeeze-and-excitation channel attention;
* the hard-swish activation.

The result is far fewer multiply-adds than ordinary convolutions.

## D. YOLO / WOAD versus SSDLite (Q20–Q25)

**Q20 ★. Why can't you use the WOAD model with the phone camera?**
WOAD was trained on two inputs from a special sensor: a near-infrared image and a colour-mapped depth image from
a Synexens CS30. A phone camera gives an ordinary RGB image and no depth. Feeding that would be out of
distribution, and the results would be meaningless (blanking IR alone already removes all detections).
Therefore a separate RGB detector (SSDLite) is used for the phone camera, and WOAD runs on recorded IR + depth
frames.

**Q21. What is cross-modal fusion in WOAD?**
In `woad/arch/yolo.py::_forward_once` (L165–223):

1. IR and depth each pass through their own first layers.
2. At layer 2 both feature maps are average-pooled to 8×8.
3. They become 128 tokens with a positional embedding.
4. 8 transformer blocks with self-attention (8 heads, 64 dimensions) let IR tokens attend to depth tokens and
   vice versa.
5. The result re-weights each stream's features.
6. The streams are concatenated and passed to the YOLOv5s backbone and head.

**Q22. Why SSDLite and not YOLO for RGB?**
SSDLite320-MobileNetV3 comes with torchvision, which was already installed, so only 14 MB of weights were
needed. It is small (3.4 M parameters) and fast on CPU (~40–55 ms per frame). The stock YOLOv5s TFLite model in
the repository would have needed TensorFlow (~400 MB) to run in Python on Windows. The trade-off is lower
accuracy (COCO mAP 21.3), which is documented.

**Q23 ★. What accuracy does your system have?**
Be precise about what each number is:

* **WOAD:** the authors report mAP@0.5 = 0.669 on their own data (training plot), but we could not reproduce it
  because that data is not published. Our own measurement on the published dataset gives person AP@0.5 = 0.218
  (val) and 0.173 (train), cross-dataset.
* **SSDLite:** COCO mAP 21.3 per torchvision; not measured on Vellore streets.
* **Voice:** 8/8 fixed commands and 10/24 spoken destinations on synthetic speech.

**Q24. How did you verify that your WOAD re-implementation is correct?**
`tools/verify_equivalence.py` runs the original `models/yolo.py` in a separate process on the same inputs; the
maximum output difference is 0.0. Tests also check the input order (swapping leaves 8 % of the confidence) and
use golden detections.

**Q25. Why is the WOAD part of the app a "replay"?**
The CS30 sensor is not connected. The replay feeds recorded sensor frames (`demo_data/detec_test`) through the
exact pipeline a live sensor would use: quality gate → detector → alert engine → speech
(`service.py::ReplayRunner`).

## E. Vosk and speech recognition (Q26–Q31)

**Q26. Why Vosk?**
It runs fully offline on the laptop CPU, has an Indian-English model (`vosk-model-small-en-in-0.4`), supports a
restricted command grammar, and is Apache-2.0. Browser speech recognition is online in Chrome and unavailable in
Chrome on iOS.

**Q27. How does the audio get from the phone to Vosk?**
`web/js/recorder.js::recordUtterance` (L65–100):

1. records the microphone with a `ScriptProcessorNode`;
2. stops after ~1 s of silence following speech (`EndOfSpeech`, L42–62) or at 6 s;
3. downsamples to 16 kHz (`downsample`, L9);
4. encodes a 16-bit WAV (`encodeWav`, L21).

`app.js::listenOnce` (L817–841) then POSTs it to `/api/voicecmd`.

**Q28 ★. Why do you run two recognisers on the same audio?**
`VoiceCommands.transcribe` (L184–196):

* The **grammar** recogniser can only output command words. It reliably detects *which command* was said, but
  cannot output place names.
* The **free** recogniser outputs any vocabulary word, needed for destinations, but often mangles the command
  itself ("navigate to Katpadi" → "they took cut body").

`parse_intent` combines the strengths of both.

**Q29. How do you find a place when the recogniser misspells it?**
`resolve_place` (L199–222):

1. saved places first;
2. then the map's text search;
3. then **sound-alike** scoring: `phonetic` keys merge similar consonants and drop vowels, so "katpadi" and
   "cut body" both become `ktpt`.

**Q30. How accurate is it?**
On synthetic speech: 8/8 fixed commands, and the correct destination first in 10/24 utterances. Because
destinations are unreliable, the app speaks the chosen place and starts guidance only after "start navigation".
Real voices are untested.

**Q31. Why does the app stop speaking before recording?**
`listenOnce` calls `voice.stop()` so that the microphone does not record NeuroSonic's own voice and misinterpret
it as a command.

## F. Piper and neural TTS (Q32–Q36)

**Q32. How does Piper generate speech?**

1. espeak-ng converts text to phonemes.
2. The phonemes are mapped to IDs.
3. A **VITS** neural network turns the IDs directly into a waveform. VITS is an end-to-end model with a text
   encoder, a duration predictor, a normalising flow and a GAN-trained decoder.
4. The model runs with ONNX Runtime on CPU.

**Q33. How fast is it?**
The acceptance sentence (5.34 s of audio) took 0.20 s to synthesise: a real-time factor of 0.04 on the laptop
CPU. The model loads in 2.5–4.3 s at start-up.

**Q34. How does the audio play on an iPhone?**
`speech.js::_playNeural` (L233–258):

* the phone fetches `/api/tts?text=…` as a blob and plays it in one reusable `<audio>` element;
* iOS requires the first playback inside a user tap, so `unlock()` (L118–135) plays a silent WAV on the first
  tap;
* the server supports HTTP byte ranges for WebKit.

*Physical iPhone playback is still pending confirmation.*

**Q35. What happens if the neural voice fails?**
The error is shown in Settings, reported to the laptop (`/api/voice/report`), and the same sentence is spoken
with the browser's built-in `speechSynthesis` (`_playBrowser`, L260–278).

**Q36 ★. How do you prevent overlapping or outdated announcements?**
`speech.js::SpeechQueue` (L18–75):

* a priority queue (urgent > system > obstacle > navigation/motion > info);
* the same text is not repeated within 4 s;
* messages older than their maximum age are dropped (an obstacle warning after 4 s);
* only one `<audio>` element plays at a time;
* an urgent or obstacle warning **interrupts** a routine message, which is replayed once (`shouldInterrupt`
  L61, `requeue` L68).

## G. OpenStreetMap (Q37–Q40)

**Q37. What is OpenStreetMap and how is its data structured?**
A free world map built by volunteers. Its data has **nodes** (points with coordinates), **ways** (ordered lists
of nodes, e.g. a street) and **relations**, all described by key=value tags such as `highway=residential`. The
licence is ODbL, which requires attribution.

**Q38. How did you obtain the Vellore data?**
Three Overpass API queries for the bounding box 12.86–13.00 °N, 79.07–79.21 °E: streets with nodes, background
features, and named places. Buildings failed with HTTP 502 and are not included. The raw files are in
`datasets/osm/vellore/`; provenance and SHA-256s are in `maps/vellore/manifest.json`.

**Q39. How did you turn OSM data into a routable graph?**
`tools/build_offline_map.py::build` (L72–190):

* every walkable `highway` way (`walkable`, L51–58) is split into edges between consecutive nodes;
* each edge is weighted by its haversine length.

Result: 31,439 nodes and 34,939 edges; 99.2 % in one connected component.

**Q40. How is the map displayed without tiles?**
`web/js/mapview.js::MapView` draws the 1 MB vector `map.json` on a canvas with an equirectangular projection
(`_xy`, L68). It supports pan and zoom, a dashed coverage box and the OSM attribution. No internet is needed.

## H. A* search (Q41–Q45)

**Q41 ★. Explain A\* and your heuristic.**
A* expands nodes in order of f(n) = g(n) + h(n), where g is the known distance from the start and h estimates
the remaining distance. Our h is the haversine straight-line distance to the destination
(`maps.py::_astar`, L184–205), implemented with a binary heap (`heapq`).

**Q42. Why is your heuristic admissible?**
No walking path can be shorter than the straight great-circle line between two points, so h never
over-estimates. It is also consistent (triangle inequality), so A* returns the optimal path, the same as
Dijkstra.

**Q43. How did you verify that A\* is correct?**
The test compares A* with an independent Dijkstra on random node pairs (`test_route_is_shortest_path`). The
lengths are identical; in an ad-hoc run on 40 pairs the maximum difference was 0.000 m. A* averaged 9.5 ms vs
13.0 ms for Dijkstra.

**Q44. What if the start is not on a road?**
`OfflineMap.route` (L140–182):

* snaps to the nearest graph node (`nearest_node`, a vectorised NumPy search);
* if that node is on a disconnected island (e.g. the paths inside Vellore Fort), it uses the nearest node of the
  main network and adds a spoken note;
* beyond 250 m (600 m for islands), it refuses with an explanation.

**Q45. How are turn instructions generated?**
`_steps` (L222–313) groups consecutive edges by street name and bearing. At each change, `turn_word` (L41–51)
turns the bearing difference into "continue straight" (< 25°), "bear" (< 60°), "turn" (< 135°) or "sharp turn".
The distance and a major-road warning are added from OSM tags.

## I. GPS and route recalculation (Q46–Q50)

**Q46. How does the app get the location?**
The browser Geolocation API, `navigator.geolocation.watchPosition` with `enableHighAccuracy` (`app.js`,
`startLocation` L173). It needs HTTPS. Errors (permission denied, no signal, timeout) are spoken.

**Q47 ★. How do you detect that the user has left the route, and what happens then?**
`nav.js::followRoute` (L116–159) projects the position onto the route polyline (`projectOnPolyline`, L73).

* If the distance is more than max(35 m, 1.5 × GPS accuracy) on **two consecutive** fixes, it says "You appear
  to be off the route. Recalculating."
* `app.js::followActiveRoute` (L402) then requests a new route from the current position (`planRoute`).

**Q48. When are instructions spoken?**
Each step's position along the route is precomputed (`prepareRoute`):

* about 70 m before a step: "In about 60 metres: turn left onto …";
* at 25 m: the instruction itself;
* arrival: within max(15 m, accuracy capped at 40 m) of the end.

Each step is spoken at most twice; steps already passed are skipped.

**Q49. How do you handle an old GPS position?**
Each fix is checked by `assessFix`: fixes older than 15 s or less accurate than 100 m are not used, and a 2 s timer
(`app.js` L224–230) announces "GPS signal lost. Guidance paused…" after 20 s without a usable fix during guidance. The app never presents an old position as current.

**Q50. How did you test navigation without walking in Vellore?**
With a clearly labelled **simulated position** that moves 20 m along the route per click (`pointAtAlong`). The
browser E2E test walked Katpadi → CMC Hospital in 264 simulated steps with spoken instructions and arrival. A
real walk has **not** been done.

## J. REST APIs (Q51–Q53)

**Q51. List the main API endpoints.**

* `/api/status`, `/api/events`, `/api/replay/*`, `/api/detect` (WOAD);
* `/api/awareness/frame` (camera);
* `/api/tts` (voice), `/api/voicecmd` (commands);
* `/api/map/info|data|search`, `/api/route` (navigation);
* `/api/history`, `/api/stats`, `/api/places` (SQLite).

See `10_API_REFERENCE.md`, which has real captured responses.

**Q52. Why are audio and images uploaded as raw bodies instead of JSON?**
`/api/voicecmd` (WAV) and `/api/awareness/frame` (JPEG) use raw bodies with a checked `Content-Type`
(`_raw_body`, L91–100). That avoids base64's 33 % size overhead and the encoding work on the phone, which matters
at 2.5 frames per second. The older `/api/detect` uses base64 JSON for convenience with file uploads.

**Q53. What status codes does the API use?**
200, 204 (no frame yet), 206 (byte range), 400, 404, 413, 415, 416, 500 and 503, all with a JSON
`{"error": …}` body.

## K. HTTPS and offline architecture (Q54–Q57)

**Q54 ★. Is the application fully offline on the iPhone?**
No. It needs **no internet**, but the iPhone must reach the laptop over local Wi-Fi, because the models run on
the laptop. If the laptop is unreachable, the app says so and can only use the phone's built-in voice. A
standalone phone app is future work.

**Q55. Why does the app need HTTPS on a local network?**
Browsers allow camera, microphone and GPS only on secure origins. NeuroSonic creates a local certificate
authority and a server certificate with the laptop's IP in subjectAltName and the serverAuth usage
(`tls.py::ensure_certificates`, L86–130). iOS requires these extensions.

**Q56. What was wrong when the iPhone page stayed loading, and how did you fix it?**
Three causes:

1. **The Windows firewall** blocked incoming connections on a Public network. `netcheck.py` now detects this
   and prints the fix.
2. **The certificate** lacked subjectAltName/serverAuth. A proper local CA was added.
3. **The server** performed TLS handshakes in `accept()`, so one stalled phone connection froze everything.
   Handshakes now run per connection.

All three are covered by tests in `tests/test_mobile_access.py`.

**Q57. How did you test "offline"?**
`tests/_offline.py::no_internet` blocks any non-loopback connection or DNS lookup in-process. Piper, Vosk,
SSDLite, the map and routing all run under it with 0 attempts. The browser E2E tests block internet DNS in
Chrome and log every request (0 external). A test with the network physically unplugged is still pending.

## L. Evaluation and testing (Q58–Q59)

**Q58 ★. How is the project tested?**

* 204 tests (`unittest`, including 32 Node tests), all passing on 2026-11-02 after Sprint 1;
* seven browser end-to-end scripts in headless Chrome, using fake camera and microphone media;
* an equivalence check against the original model;
* mutation checks.

See `14_TESTING_AND_RESULTS.md`.

**Q59. What does your testing *not* prove?**
Real-device behaviour: iPhone audio, microphone and camera; real GPS walking; real human voices; real street
video; and usability with visually impaired users. Synthetic-speech results are biased, because Piper's own
voice was used.

## M. Limitations and future improvements (Q60)

**Q60 ★. What are the main limitations, and what would you do next?**

* **Limitations:**
  * the phone depends on the laptop;
  * the RGB detector is generic and unvalidated, with no distance;
  * WOAD needs a sensor we don't have, and is weak on new scenes;
  * spoken place names are unreliable;
  * OSM data is sparse;
  * nothing has been physically verified.
* **Next steps:**
  1. the iPhone and street acceptance tests;
  2. a Vellore dataset to measure and fine-tune detection (including steps, kerbs, poles);
  3. better place-name recognition;
  4. connecting the CS30 for live WOAD with distances;
  5. on-device inference for a standalone app;
  6. a user study.

## N. Walking guidance and product refinement (Q61–Q63)

**Q61 ★. Why does the camera no longer say "Person ahead" all the time?**

* Walking with a stream of object names is tiring and does not answer the real question: can I keep walking?
* Walking Guidance (the default) speaks only the state of the walking path, and only when it changes:
  clear, caution, stop, cannot assess, or camera unavailable.
* Object names remain available as the optional Object Description mode. See `17_PRODUCT_REFINEMENT.md`.

**Q62 ★. How is "the walking path" decided, and how do you avoid a false "clear"?**

* The lower-central trapezoid of the image is the approximate path. For every detected box, the fraction of the
  path region it covers and the fraction of the box inside the region are computed. A large or centred overlap
  gives *blocked*; a smaller overlap gives *possible obstacle*; objects outside the region are *at the side*.
* Clear needs 3 good frames in a row, while a warning needs only 2 of the last 3.
* Dark, covered or blurred frames (variance of the Laplacian < 20) are *uncertain*, never clear.
* The sentence is "The visible path *appears* clear. Continue carefully." It means "nothing recognised", not
  "safe": steps, kerbs, potholes and poles are invisible to the detector.

**Q63. How does the app deal with bad GPS?**

* Each fix is classified:
  * good: ≤ 50 m;
  * weak: 50–100 m, used with a wider off-route tolerance;
  * inaccurate: > 100 m, not used, "Guidance paused";
  * stale: older than 15 s, not used.
* During guidance, 20 s without a usable fix gives "GPS signal lost. Guidance paused…", and later "GPS signal
  restored."
* Re-routing happens at most once per 15 s.
* All of this is unit-tested and checked with Chrome's GPS emulation, but not yet outdoors (test M3).
