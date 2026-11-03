# 10. API reference

**Implementation:** `neurosonic/server.py`. Routing tables: `GET` and `POST` dictionaries in `make_handler`
(L392–402). Every response below was **captured from the running server on 2026-11-02**:

* `python neurosonic_app.py --port 8786`;
* the requests used real demo images, synthetic speech and real map queries;
* long arrays are shortened to 3 items + "...", and long strings are cut.

**General rules:**

* JSON requests and responses are UTF-8.
* Errors come back as `{"error": "<message>"}` (`_dispatch` L133–155):

  | Code | Cause |
  |---|---|
  | **400** | invalid input (`ApiError`, `ValueError`, `InvalidInput`) |
  | **404** | unknown path |
  | **413** | body too large (JSON 20 MB, `MAX_BODY` L46; WAV 2 MB; JPEG 3 MB) |
  | **415** | wrong Content-Type for binary uploads |
  | **416** | invalid byte range |
  | **503** | engine not configured, or a voice-engine failure (`TTSError`) |
  | **500** | unexpected error (logged) |
* Static files: any other GET path is served from `web/` (`_static` L161–169). Paths outside `web/` give 404.
* Caching: `Cache-Control: no-store`, except audio (`private, max-age=86400`) and map data
  (`private, max-age=3600`).
* There is **no authentication**. The server is meant for a trusted local network (see document 12).

## 10.1 Status and events

### `GET /api/status`: `r_status` L172–175

```json
{"app": "NeuroSonic", "engine": "WOAD exp72 cross-modal detector",
 "model": {"names": ["person","Ebike","Car"], "sha256": "da043ff2e1edd393fcd329dddbac58676f1305c14f2eb084f928439d7950f8aa",
           "num_params": 7521992, "device": "cpu", "checkpoint_date": "2023-04-05T21:10:40.468663"},
 "replay_sets": [{"name": "detec_test", "available": true, "description": "600 real IR+depth frames (published by the WOAD authors)"},
                 {"name": "reconstructed_val", "available": true, "description": "187 degraded frames rebuilt from exp72 validation plots"},
                 {"name": "sensor_recording", "available": true, "description": "raw CS30 recording - too dark for the model (shows input-quality warnings)"}],
 "replay": {"running": false}, "last_event_id": 0}
```

### `GET /api/events?since=<id>`: `r_events` L177–183

* Returns the alert events with id > `since`, from the in-memory `EventLog` (`service.py` L68–96, last 300).
* `since` must be an integer, otherwise 400 `{"error": "since must be an integer"}`.

```json
{"events": [{"id": 1, "time": 1793606268.88, "source": "replay", "kind": "object", "text": "E-bike detected ahead.",
             "priority": 12, "data": {"class_name": "Ebike", "position": "ahead", "count": 1, "max_confidence": 0.9526,
             "boxes_xyxy": [[220.0, 206.0, 294.0, "..."]], "track_ids": [5]}, "frame_id": "0000060710.png"},
            {"id": 2, "...": "...", "text": "2 people detected ahead.", "priority": 11}],
 "last_event_id": 2}
```

## 10.2 WOAD replay and single-pair detection

### `POST /api/replay/start`: `r_replay_start` L185–188

* **Body:** `{"set": "detec_test" | "reconstructed_val" | "sensor_recording", "fps": 0.5–10, "start": int, "loop": bool}`.
* Only server-known sets can be played (`REPLAY_SETS`, `service.py` L27); there are no client-supplied paths.
* **Response:** the replay state, as in the next entry.

### `GET /api/replay/state`: `r_replay_state` L194–195

```json
{"running": true, "set": "detec_test", "fps": 4.0, "frames": 230, "frame_index": 13, "frame_id": "0000060821.png",
 "segment": 6, "quality": {"status": "ok", "reasons": [], "ir_mean": 147.4, "ir_std": 69.1, "depth_invalid": 0.619},
 "detections": [{"class_id": 1, "class_name": "Ebike", "confidence": 0.9411, "box_xyxy": [217.0, 143.0, 473.0, "..."]},
                {"class_id": 0, "class_name": "person", "confidence": 0.3291, "box_xyxy": [500.0, 0.0, 578.0, "..."]}],
 "available": true, "seq": 14, "error": null, "inference_ms": 179, "loops": 0}
```

### `POST /api/replay/stop`: `r_replay_stop` L190–192

Returns the final state with `"running": false`.

### `GET /api/replay/frame.jpg`: `r_replay_frame` L197–201

* The latest annotated IR | depth panel as `image/jpeg` (138,809 bytes in the capture).
* Returns 204 if there is no frame yet.

### `POST /api/detect`: `r_detect` L203–210 → `DetectionService.detect_upload` (`service.py` L213–234)

* **Body:** `{"ir_base64": "<PNG/JPEG base64 or data URL>", "depth_base64": "..."}`.
* **Response** (detec_test frame 0000060683):

```json
{"quality": {"status": "ok", "reasons": [], "ir_mean": 145.2, "ir_std": 66.6, "depth_invalid": 0.679},
 "image_size": {"width": 640, "height": 480},
 "detections": [{"class_id": 1, "class_name": "Ebike", "confidence": 0.9251, "box_xyxy": [395.0, 140.0, 468.0, "..."]},
                {"class_id": 1, "class_name": "Ebike", "confidence": 0.7863, "box_xyxy": [191.0, 186.0, 379.0, "..."]},
                {"class_id": 1, "class_name": "Ebike", "confidence": 0.5677, "box_xyxy": [571.0, 117.0, 622.0, "..."]}],
 "alerts": ["E-bike detected ahead.", "2 E-bikes detected on the right."],
 "timing_ms": {"inference": 186.4, "nms_and_scaling": 0.9},
 "annotated_jpeg_base64": "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBD..."}
```

* **Errors:** bad base64 → 400 "images must be base64 encoded"; undecodable image → 400 "IR image could not be
  decoded".

## 10.3 Alerts, history, statistics, saved places (SQLite)

| Endpoint | Handler | Body / params | Response |
|---|---|---|---|
| `POST /api/alerts` | `r_alerts` L212–218 | `{"source": "eventsim"\|"navigation", "kind": "motion"\|"navigation"\|"system", "text": "...", "position": ...}` | the stored event, e.g. `{"id": 5, "source": "eventsim", "kind": "motion", "text": "Motion ahead.", "priority": 5, "data": {"position": "ahead"}, ...}` |
| `GET /api/history?limit=N` | `r_history` L220–222 | limit 1–1000 (default 100) | `{"history": [{"id": 5, "created": 1793606272.22, "source": "eventsim", "kind": "motion", "text": "Motion ahead.", "class_name": null, "position": "ahead", "confidence": null, "frame_id": null}, ...]}` |
| `POST /api/history/clear` | `r_history_clear` L224–227 | `{}` | `{"ok": true}` |
| `GET /api/stats` | `r_stats` L229–230 | — | `{"total": 5, "objects_by_class": {"Ebike": 3, "person": 1}, "by_kind": {"motion": 1, "object": 4}, "by_source": {"eventsim": 1, "replay": 2, "upload": 2}}` |
| `GET /api/places` | `r_places` L232–237 | — | `{"places": [{"id": 1, "name": "Home", "lat": 12.93, "lon": 79.14, "created": 1793606272.25}]}` |
| `POST /api/places` | `r_places` | `{"name": "Home", "lat": 12.93, "lon": 79.14}` | `{"id": 1, "places": [...]}`; invalid name or coordinates → 400 |
| `POST /api/places/delete` | `r_places_delete` L239–243 | `{"id": 1}` | `{"places": [...]}`; unknown id → 404 |

## 10.4 Voice (Piper text-to-speech)

### `GET /api/tts/status`: `r_tts_status` L246–247 → `PiperTTS.info`

```json
{"engine": "piper", "engine_version": "1.8.0", "engine_licence": "GPL-3.0-or-later", "voice": "en_IN-spicor",
 "voice_licence": "AGPL-3.0 (navgurukul-ai-labs/text-to-speech-en-IN-piper)", "language": "en-IN",
 "model_present": true, "loaded": true, "available": true, "error": null, "sample_rate": 22050,
 "espeak_voice": "en-us", "synthesised": 0, "cache_hits": 1, "last_ms": null, "load_ms": 4257}
```

### `GET /api/tts?text=<url-encoded text>`: `r_tts` L249–253, `_send_media` L255–272

| Request | Captured response |
|---|---|
| `text=Hello. This is NeuroSonic. Your voice assistant is working correctly.` | **200** `audio/wav`, 233,516 bytes, `Accept-Ranges: bytes`, `Cache-Control: private, max-age=86400` |
| same + `Range: bytes=0-1` (iOS probe) | **206**, 2 bytes, `Content-Range: bytes 0-1/233516` |
| range beyond the end | **416** (`test_tts_endpoint_and_ranges`) |
| empty `text` | **503** `{"error": "voice engine: empty text"}` |

### `POST /api/voice/report` and `GET /api/voice/reports`: L243–259

* **Body:** `{"engine": "neural"|"browser", "ok": bool, "error": "...", "text": "...", "duration": s, "user_agent": "...", "via": "host"}`.
* **Response:** `{"ok": true}`. The server also prints, for example,
  `[voice] 192.168.1.7 iPhone/Safari: neural voice PLAYED: "Hello. This is NeuroSonic…"`.
  This is how a phone's playback is visible on the laptop.

## 10.5 Offline map and routing

### `GET /api/map/info`: `r_map_info` L298–299 → `OfflineMap.info`

```json
{"available": true, "region": "vellore", "bbox": {"south": 12.86, "west": 79.07, "north": 13.0, "east": 79.21},
 "attribution": "© OpenStreetMap contributors (ODbL 1.0)", "osm_timestamp": "2026-11-02T06:32:02Z",
 "graph_nodes": 31439, "places": 813, "main_network_share": 0.992,
 "not_included": ["buildings (Overpass download failed: HTTP 502 'server at capacity'; mirror unreachable)"]}
```

### `GET /api/map/data`: `r_map_data` L301–309

* `maps/vellore/map.json`, gzip-compressed if the client accepts it: **282,381 bytes gzip → 1,052,137 bytes**.
* Keys: `region, bbox, attribution, osm_timestamp, roads{major 219, medium 125, minor 6095, foot 271 lines},
  water, waterline, green, landuse, rail`. Coordinates are `[lon, lat]`.

### `GET /api/map/search?q=<text>&lat=&lon=`: `r_map_search` L311–316 → `OfflineMap.search`

```json
{"results": [{"name": "CMC Hospital", "name_en": null, "name_ta": null, "kind": "public_transport=platform",
              "lat": 12.92555, "lon": 79.133377, "distance_m": 4837},
             {"name": "CMC Hospital Blood Bank", "kind": "healthcare=blood_donation", "distance_m": 4960, "...": "..."},
             {"name": "CMC Eye Hospital", "kind": "public_transport=platform", "distance_m": 6254, "...": "..."}]}
```

### `POST /api/route`: `r_route` L318–325 → `OfflineMap.route` (`maps.py` L140–182)

* **Body:** `{"from": {"lat": 12.9690, "lon": 79.1356}, "to": {"lat": 12.9248, "lon": 79.1355}}`.

```json
{"distance_m": 5628, "duration_s": 4690,
 "polyline": [[12.969, 79.1356], [12.968808, 79.135755], [12.968448, 79.135766], "..."],
 "steps": [{"text": "Head south on the unnamed road for 40 metres.", "at": [12.968808, 79.135755], "distance_m": 40,
            "street": null, "highway": "residential", "turn": null},
           {"text": "Turn left onto the unnamed road, then continue for 80 metres.", "at": [12.968448, 79.135766],
            "distance_m": 85, "street": null, "highway": "residential", "turn": "turn left"}, "..."],
 "snap_m": {"start": 27, "destination": 11}, "notes": [], "major_road_m": 5122,
 "source": "offline OSM walking graph", "attribution": "© OpenStreetMap contributors (ODbL 1.0)"}
```

* **Errors:**
  * destination outside the box → 400 `{"error": "The destination is outside the offline map area (vellore)."}`;
  * malformed body → 400 `{"error": "from/to must be {lat, lon}"}`;
  * too far from any path, or no connection → 400 with an explanation.

## 10.6 Voice commands (Vosk)

### `GET /api/voicecmd/status`: `r_voicecmd_status` L328–329 → `VoiceCommands.info`

```json
{"available": true, "engine": "vosk 0.3.45 (Apache-2.0)", "model": "vosk-model-small-en-in-0.4", "language": "en-IN",
 "offline": true, "error": null, "help": "You can say: navigate to, followed by a place. ...",
 "recognised": 0, "last_ms": null, "load_ms": 322}
```

### `POST /api/voicecmd?lat=&lon=`: `r_voicecmd` L331–346 → `VoiceCommands.handle` (`voicecmd.py` L224–241)

* **Body:** raw WAV (16 kHz, mono, 16-bit, ≤ 8 s), `Content-Type: audio/wav`.
* **Example 1**, synthetic speech "navigate to home" with a saved place "Home":

```json
{"heard": "navigate to home", "heard_commands": "navigate to", "heard_free": "navigate to home",
 "intent": "navigate", "query": "home",
 "places": [{"id": 1, "name": "Home", "lat": 12.93, "lon": 79.14, "match": "saved place", "kind": "saved place"}]}
```

* **Example 2**, synthetic speech "navigate to Katpadi Junction". The recogniser misheard it, and sound-alike
  matching still found the place:

```json
{"heard": "it took out by the junction", "heard_commands": "navigate", "heard_free": "it took out by the junction",
 "intent": "navigate", "query": "it took out by the junction",
 "places": [{"name": "Katpadi Junction", "name_ta": "காட்பாடி சந்திப்பு", "kind": "public_transport=station",
             "lat": 12.972239, "lon": 79.136426, "match": "sound-alike", "score": 0.84},
            {"name": "Katpadi Junction- Chittor Bus Stand", "match": "sound-alike", "score": 0.76, "...": "..."},
            {"name": "ICICI Bank", "match": "sound-alike", "score": 0.67, "...": "..."}]}
```

* **Errors:**
  * wrong Content-Type → 415 `{"error": "Content-Type must be one of ['application/octet-stream', 'audio/wav', 'audio/x-wav']"}`;
  * invalid or too-short audio → 400.
* **Intents:** `navigate, search, start_navigation, stop_navigation, repeat, status, awareness_on, awareness_off,
  help, test_voice, unknown`. `help` and `unknown` add a `message`.

## 10.7 Live camera awareness (SSDLite)

### `GET /api/awareness/status`: `r_awareness_status` L374–375 → `RGBAwareness.info`

```json
{"available": true, "model": "SSDLite320-MobileNetV3-Large (torchvision, COCO)",
 "weights": "ssdlite320_mobilenet_v3_large_coco-a79551df.pth",
 "licence": "BSD-3-Clause (torchvision); COCO annotations CC BY 4.0", "coco_box_map": 21.3,
 "classes": ["Bench", "Bicycle", "Bus", "..."], "distance": "not available (single RGB camera)",
 "modes": ["chest", "handheld"], "error": null, "loaded": true, "frames": 1, "last_ms": 62, "load_ms": 197}
```

### `POST /api/awareness/frame?session=<id>&mode=chest|handheld`: `r_awareness_frame` L377–390 → `RGBAwareness.process_frame`

* **Body:** raw JPEG, `Content-Type: image/jpeg`.
* **Example:** the second frame of the same session; alerts need 2 of 3 frames.

```json
{"width": 640, "height": 480,
 "quality": {"status": "ok", "reasons": [], "ir_mean": 145.2, "ir_std": 66.6, "depth_invalid": null},
 "detections": [{"class_id": 1, "class_name": "Person", "confidence": 0.9445, "box_xyxy": [227.1, 173.7, 358.3, "..."]},
                {"class_id": 2, "class_name": "Bicycle", "confidence": 0.86, "box_xyxy": [224.9, 251.4, 376.0, "..."]},
                {"class_id": 1, "class_name": "Person", "confidence": 0.6733, "box_xyxy": [402.7, 142.3, 468.7, "..."]}],
 "events": [{"kind": "object", "priority": 13, "text": "Bicycle ahead.",
             "data": {"class_name": "Bicycle", "position": "ahead", "count": 1, "max_confidence": 0.86,
                      "max_area_frac": 0.0803, "...": "..."}, "urgent": false, "...": "..."},
            {"kind": "object", "priority": 12, "text": "Person ahead.",
             "data": {"class_name": "Person", "position": "ahead", "max_area_frac": 0.0928, "...": "..."}, "urgent": false}],
 "available": true, "inference_ms": 77, "mode": "chest"}
```

* **Naming quirk:** the quality block reuses the WOAD `QualityReport`, so for an RGB frame `ir_mean`/`ir_std`
  hold the frame's grey-level mean/std, and `depth_invalid` is `null`.
* **Errors:** `mode=pocket` → 400 `{"error": "mode must be one of ['chest', 'handheld']"}`; empty body → 400;
  undecodable JPEG → 400.

## 10.8 Phone setup server (HTTPS mode only)

`make_setup_server` (L469–506) runs on **plain HTTP, port + 1** (default 8766):

* `GET /` returns the setup page, with the CA fingerprint and the app URL;
* `GET /neurosonic-ca.crt` returns the CA certificate (`application/x-x509-ca-cert`);
* everything else returns 404. The setup server exposes **no** API (`test_setup_server_serves_only_page_and_ca`).

## Online scene description (Sprint 1, 2026-11-02)

Handlers `r_vision_status` and `r_vision_describe` in `neurosonic/server.py`. The logic is in
`neurosonic/vision/assistant.py::SceneAssistant`; the full description is in `../docs/ONLINE_VISION.md`. The
responses below were captured with the **mock provider** (`--vision-provider mock`), because the single approved
live Gemini request timed out.

### `GET /api/vision/status`

The key is never included; `configured` is only true/false.

```json
{"available": true, "enabled": true, "configured": true, "provider": "mock", "model": "mock-vision-1",
 "problem": null, "breaker": "closed", "retry_after_s": 0, "requests_this_hour": 2, "hourly_cap": 60,
 "min_interval_s": 5.0, "requires_internet": true, "requires_consent": true, "stores_images": false,
 "limits": "positions are left/centre/right only; no distances; never confirms that a path is safe",
 "requests": 2, "ok": 1, "provider_calls": 3, "failures": {"unavailable": 1}, "last_latency_ms": 953,
 "last_error": "unavailable: 503 UNAVAILABLE. The model is overloaded. Please try again later.", ...}
```

### `POST /api/vision/describe?session=&mode=chest|handheld&consent=1&q=<question>`

The body is a JPEG or PNG of up to 3 MB. It is processed in memory and never stored.

* Without `consent=1` (HTTP 200):
  ```json
  {"ok": false, "code": "consent", "text": "Online scene description is off until you allow sending camera images to the online service.", ...}
  ```
* Success with `q=What is on the left?`:
  ```json
  {"ok": true, "code": "ok",
   "text": "AI description: Regarding your question: A street with parked cars and a few people walking on the left side. I can see person on the left, car on the right and motorcycle in the centre. Possible hazards: A motorcycle appears to be moving in the centre of the view. Objects far away are hard to identify.",
   "objects": [{"name": "person", "position": "left", "note": "walking towards the camera"}, ...],
   "hazards": ["A motorcycle appears to be moving in the centre of the view."], "image_quality": "good",
   "filtered_sentences": 0, "question": "What is on the left?", "provider": "mock", "model": "mock-vision-1",
   "attempts": 1, "notice": "AI-generated description. It may be wrong and does not confirm that any path is safe."}
  ```
* Provider outage (two 503s; one retry), HTTP 200:
  ```json
  {"ok": false, "code": "unavailable", "text": "Online scene description is unavailable right now. Local walking guidance continues.", "attempts": 2, "latency_ms": 1109, ...}
  ```
* Errors:
  * 400: empty, unreadable or too small image;
  * 413: more than 3 MB;
  * 415: wrong `Content-Type`;
  * 503: the server was started without a vision assistant.
