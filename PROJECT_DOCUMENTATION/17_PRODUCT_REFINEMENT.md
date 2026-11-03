# 17. Product refinement (2026-11-02): walking guidance, voice, GPS, iPhone interface

This document describes the changes of the final product-refinement stage. A backup of the implementation before
the changes is in `backups/20261102-134759-before-product-refinement/`. The original WOAD code and checkpoint were not
changed.

## 17.1 Why the change

Before this stage, the camera spoke object names for every confirmed detection ("Person ahead.", "Person on the
left."). In a street this means a stream of names that does not answer the user's real question: *can I keep
walking?* The refinement makes **Walking Guidance** the default. It speaks only about the walking path, and only when
the situation changes. Object names became an optional **Object Description** mode.

## 17.2 Walking-path assessment: `neurosonic/pathguide.py`

### Region

The lower-central trapezoid of the image is used as the approximate walking path (`PATH_POLYGON`). In normalised
coordinates it has its bottom edge from x 0.22 to 0.78 at y 1.0 and its top edge from 0.40 to 0.60 at y 0.45. It is
rasterised once to a 64 × 48 mask (`PATH_MASK`).

### Per frame: `assess_frame`

1. **Quality.** If the frame is `unusable` (mean < 20 or contrast < 6), or its sharpness (variance of the Laplacian
   of the 320 px grey image) is below 20, the frame is **UNCERTAIN**. Calibration on the recorded frames: normal
   frames ≥ 423; Gaussian blur k = 15 → 25, k = 31 → 5; a plain wall → 8.6.
2. **For each detection with confidence ≥ 0.40**, `box_path_overlap` computes:
   * *cover*: the fraction of the path region that the box covers;
   * *inpath*: the fraction of the box that lies inside the region.

   The left/centre/right *side* is taken from the box centre.
3. **BLOCKED_VIEW** applies when either:
   * cover ≥ 0.30 and the object is centred or mostly (≥ 50 %) inside the region; or
   * ≥ 50 % of the box is inside, the box reaches the bottom 10 % of the image, and it is at least half the image
     high.
4. **POSSIBLE_OBSTACLE** applies when cover ≥ 0.06 or inpath ≥ 0.35. Anything else is reported as *at the side*.
5. With no object in the path, a frame that is too dark to claim a clear view (`warn` / mean < 45) is
   **UNCERTAIN**, not clear.

### Over time: `PathGuide.update` (one per phone session)

| State | Needed evidence | Spoken (chest mode) | Speech category |
|---|---|---|---|
| CLEAR_VIEW | 3 of 3 frames clear | "The visible path appears clear. Continue carefully." | info |
| POSSIBLE_OBSTACLE | ≥ 2 of the last 3 frames possible or blocked | "Caution. An object is detected in the walking path." | obstacle |
| BLOCKED_VIEW | ≥ 2 of the last 3 frames blocked | "Stop. The walking path may be blocked." | urgent |
| UNCERTAIN | 2 consecutive uncertain frames | "I cannot clearly assess the path. Please check carefully." | system |
| CAMERA_UNAVAILABLE | no usable frame (client side: camera ended, no picture for 4 s, or 3 failed requests) | "Camera view is unavailable." | system |

**Announcement rules:**

* **Hysteresis.** Without enough evidence the state does not change, so one flickering frame changes nothing.
* **Escalation is immediate.** De-escalation, for example from Stop to Clear, waits until at least 2 s have passed
  since the last announcement.
* **Repeats:**
  * BLOCKED_VIEW gives a reminder ("…may still be blocked") every 8 s while it lasts;
  * UNCERTAIN and CAMERA_UNAVAILABLE are repeated after 30 s;
  * POSSIBLE_OBSTACLE is re-announced only when the *obstruction zones* change (side × level), at most every 4 s.
* **Handheld mode** uses camera-view wording ("…in front of the camera") because the camera may not point along the
  walking direction.

**Design principle: prefer "uncertain" to a false "clear".**

* Clear needs more evidence (3 frames) than a warning (2 of 3).
* Dark or blurred frames can never be clear.
* The clear sentence says *"appears clear … continue carefully"*, never "safe".

### What it cannot do

* It does not estimate distance.
* It cannot see steps, potholes, kerbs, poles, walls or anything outside the 23 COCO obstacle classes.

The thresholds are engineering defaults chosen on recorded frames and synthetic boxes. They have **not** been
validated with users or in Vellore streets (manual test C1).

### Integration: `RGBAwareness.process_frame(..., describe=False)`

* Path guidance always runs.
* The WOAD `AlertEngine` still tracks objects, but its sentences are returned only when `describe=True`, with category
  `description` (never urgent, never interrupting).
* The response includes `path` (state, per-frame level, reason, objects in the path and at the sides, polygon,
  sharpness), so the phone can draw the region and colour the boxes.
* The endpoint is `POST /api/awareness/frame?session=&mode=chest|handheld&describe=0|1`. Path announcements are
  stored in the history with kind `path`.
* Measured cost:
  * the path logic takes 0.43 ms per frame;
  * the whole `process_frame` on a 320 × 240 frame takes a median of 52 ms (p90 70 ms) on the laptop CPU.

## 17.3 Voice

* **Piper speaking style** (`neurosonic/tts.py`, `STYLE`):
  * `length_scale` 1.08 (slightly slower), `noise_scale` 0.6, `noise_w_scale` 0.7 (less random variation);
  * the style is part of the cache key;
  * this is a subjective choice and was not rated by listeners.
* **Speech queue** (`web/js/speech.js`):
  * **Cooldowns per category** (`COOLDOWN_MS`): routine messages such as "clear" wait 20 s before repeating, while
    urgent messages wait 3 s.
  * **Latest wins** (`push(text, category, now, key)`): queued messages with the same key replace each other, so an
    outdated "Caution" is never spoken after the path has become clear.
  * **Pause:** a 250 ms gap between messages (`GAP_MS`).
  * **Descriptions:** the new category `description` (priority 0, maximum age 3 s, no beep, never interrupts).
  * **Prefetch:** `Announcer.prefetch` loads the fixed warning sentences when awareness starts, so the first "Stop"
    does not wait for synthesis and download.
* **No technical words:** messages contain no class numbers, "bounding box", "confidence" or distances. This is
  checked by `test_messages_have_no_technical_terms`.

## 17.4 GPS and navigation

**Fix quality** (`nav.js::assessFix`, pure function):

| Level | Rule | Used for guidance |
|---|---|---|
| good | accuracy ≤ 50 m | yes |
| weak (poor) | accuracy 50–100 m | yes (wider off-route tolerance; spoken warning at most once a minute) |
| inaccurate | accuracy > 100 m | no: "Guidance paused" |
| stale | fix older than 15 s | no |

**Location handling:**

* **GPS loss** (`gpsWatch`): during guidance, no usable fix for 20 s gives "GPS signal lost. Guidance paused…" once,
  and later "GPS signal restored." once.
* **Permission denied:** a spoken explanation with the iPhone settings path, and the badge shows "denied".
* **Location panel:** position, accuracy, fix age and status.

**Re-routing:**

* Off-route detection is unchanged: max(35 m, 1.5 × accuracy) on two consecutive fixes.
* New: re-routing is limited to once per 15 s (`canReroute`).

**Turn instructions** (`maps.py::_steps`, rewritten):

* Boundaries are where the route changes from one OSM way to another. The angle is measured between the direction
  20 m before and 20 m after the junction (`TURN_PROBE_M`), so small wiggles in the geometry are ignored.
* A boundary is kept if the angle is ≥ 30° or a new *named* street begins ("Continue onto Old Palar Bridge").
  Otherwise the parts are merged.
* Steps shorter than 12 m are merged into the next one, with the net turn recomputed.
* "the unnamed road" is no longer spoken.
* Each step has `action`, for example "Turn right onto Vellore - Chittoor Road". The phone uses it for the short
  pre-announcement "In about 60 metres, turn right onto Vellore - Chittoor Road."
* Example (Katpadi → CMC Hospital, 6.3 km): 6 instructions instead of a long list.

**Map** (`mapview.js`):

* The first position inside the map area centres the view at street zoom.
* During guidance the map follows the user. Dragging stops following, and "◎" resumes it.
* The route start and the destination name are drawn.
* The canvas backing store is reset only when the size really changes.

## 17.5 iPhone interface

* **Five screens** in a fixed bottom bar, with a central **Speak** button: Home (awareness), Navigate, History,
  Settings, How it works. The research tools (WOAD replay, image-pair check, event-camera simulation) moved to a
  screen opened from Settings. No functionality was removed.
* **Home:**
  * a large state card (clear / caution / stop / uncertain / unavailable, colour-coded);
  * the camera preview with the walking-path region and boxes;
  * Start and Stop;
  * the Walking guidance / Object description switch;
  * GPS, mode and fps pills.
* **Navigate:**
  * the map with overlay controls;
  * the location panel;
  * search, the route summary, the current instruction, and Preview / Start / Stop;
  * collapsible steps, simulation, saved places and the straight-line fallback.
* **Settings:**
  * voice and Test Voice;
  * Object Description;
  * carrying mode;
  * voice commands;
  * a **permissions** panel (camera, microphone, location, with "Allow" buttons);
  * an **offline status** list (laptop, Piper, Vosk, SSDLite, map, internet not needed);
  * research tools;
  * About.
* **How it works:** 10 topics in simple language, and the architecture diagram (iPhone → app → laptop → engines →
  voice). It states that the app depends on the laptop over a local network and is not standalone.
* **Layout rules:**
  * safe-area insets top, bottom, left and right;
  * 16 px inputs (no iOS focus zoom);
  * touch targets of at least 40 px (most are 44–48 px);
  * fixed heights for the header, alert and state card (no tap-swallowing layout shift);
  * `overflow-x: hidden`.
* **Efficiency:**
  * camera frames are sent at most one at a time and about every 400 ms;
  * no uploads while the page is hidden;
  * a 5 s abort per request;
  * event polling is 1 s (3 s when hidden);
  * the fps is shown on screen.

## 17.6 Verification (2026-11-02)

| Check | Result |
|---|---|
| Full suite `python -m unittest discover -s tests -t .` | **Ran 141 tests, OK**, including 29 Node tests |
| `test_pathguide.py` (20) | states, side vs centre, temporal confirmation, reminders, de-escalation, handheld wording, Object Description on/off, endpoint, history |
| `tests/js/refinement.test.mjs` (12) | GPS good / poor / unusable / stale / denied, GPS loss, reroute limit, pre-announcement wording, off-route + reroute, latest-wins queue, cooldowns, interruption, stale descriptions, map rendering + resize + follow |
| `test_refinement_ui_nav.py` (7) | route steps on real Vellore routes, screens + tab bar, How It Works content, layout rules, no external resources |
| `ui_refine_cdp.mjs` (Chrome, iPhone 17 Pro Max metrics 440 × 956 @3x, touch, iOS UA) | **PASS**: no horizontal overflow on 6 screens; targets ≥ 40 px; content not under the bars; How It Works; map backing store 1248 × 1080 → 2204 × 660 after rotation; GPS good / inaccurate / denied via CDP emulation; simulated route Katpadi → CMC with spoken steps; 0 external requests; 0 JS errors |
| `ui_final_cdp.mjs` (fake camera + microphone) | **PASS**: Walking Guidance spoke "Caution. An object is detected in the walking path." and no object names; after switching, "Bicycle ahead." / "Person ahead."; voice command; interruption; 0 external requests |
| `ui_smoke_cdp.mjs`, `ui_voice_map_cdp.mjs` | **PASS** |

**Not verified:**

* Safari on a physical iPhone;
* outdoor GPS;
* real walking;
* users' opinion of the messages.

See `docs/MANUAL_TESTING.md`.
