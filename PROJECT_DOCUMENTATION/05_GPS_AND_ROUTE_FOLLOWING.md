# 5. GPS location acquisition and route following

All of this runs **in the browser on the phone**; the server is only called to (re)compute routes.

## 5.1 Getting the position: `web/js/app.js` (GPS section, L153–230)

* **Problem:** obtain a continuous, honest position, and say clearly when it is missing, inaccurate or old.
* **Technology:** the W3C Geolocation API (`navigator.geolocation.watchPosition`). On phones it uses GNSS (GPS)
  plus Wi-Fi/cell assistance.
  * Browsers only allow it on **secure origins** (HTTPS or localhost). That is why the phone uses
    `https://<laptop-ip>:8765` (document 12).
* **Code** (`startLocation` L173, `onGeoError` L188):
  ```js
  watchId = navigator.geolocation.watchPosition(onFix, onGeoError, { enableHighAccuracy: true, maximumAge: 3000, timeout: 20000 });
  // onGeoError: code 1 -> "Location permission denied. Navigation needs location. Allow it in Settings › Apps › Safari › Location."
  //             code 2 -> "Location unavailable: no GPS signal. Move to an open area. Still trying."
  ```
* **`onFix`** (L204–216) stores `{lat, lon, accuracy, t}`. Unless a simulated position is active, it calls
  **`onPosition`** (L219–223), the single entry point for every position:
  * `mapView.setPosition()` draws the dot and the accuracy circle;
  * `updateCoverage()` speaks a message if the user leaves the offline map area;
  * then either `followActiveRoute()` (route guidance) or `updateGuidance()` (straight-line fallback).
* **Fix quality** (refined 2026-11-02, `nav.js::assessFix`): every fix is classified good (≤ 50 m), weak
  (50–100 m), inaccurate (> 100 m, not used) or stale (older than 15 s, not used). Only usable fixes reach
  `onPosition`; the location panel shows position, accuracy, fix age and status. A 2 s timer (L223–229) updates the
  fix age and runs `gpsWatch`: during guidance, 20 s without a usable fix speaks "GPS signal lost. Guidance
  paused…", and "GPS signal restored." afterwards. An old position is never presented as current.
  See `16_PRODUCT_REFINEMENT.md` §16.4.
* **Insecure page:** if `window.isSecureContext` is false, "Location needs HTTPS or localhost" is spoken (L174).

## 5.2 Straight-line fallback guidance: `web/js/nav.js::guidance` (L42–63)

Used when there is no offline route, for example outside the Vellore box or when a coordinate is typed in.

* **Calculation:** `distanceM` (L7) is the haversine distance; `bearingDeg` (L13) the initial bearing;
  `compass` (L20) maps it to one of 8 compass words.
* **When it speaks:**
  * at the start;
  * when the distance changes by ≥ 50 m;
  * every 30 s;
  * on arrival within max(15 m, GPS accuracy capped at 50 m).
* It adds "GPS accuracy is low, about N metres" when the accuracy is worse than 50 m.

## 5.3 Following an offline route: `web/js/nav.js`

### Projection onto the route: `projectOnPolyline` (L73–87)

* **Coordinates:** points are converted to local flat metres (`toXY` L67: x = lon·111 320·cos(lat₀),
  y = lat·110 540), which is accurate enough within a city.
* **Per segment:** for each segment A→B it computes the orthogonal projection of the position P, clamped to the
  segment (parameter t ∈ [0, 1]).
* **Result:** the distance to the route and **`along`**, the metres from the route start.

### Preparing the route: `prepareRoute` (L108–112)

For every step that has a start point `at`, it stores the step's `along` position on the polyline. Following
then reduces to comparing two numbers: `step.along − user.along`.

### The decision function: `followRoute` (L116–157)

The function is pure (no side effects), so it can be unit-tested.

```js
if (toEnd <= Math.max(arriveM, Math.min(accuracy, 40))) { … "You have arrived near …" }
if (pr.distance > Math.max(offRouteM, accuracy * 1.5)) {
  s.offCount += 1;
  if (s.offCount >= 2) { … return { texts: ["You appear to be off the route. Recalculating."], offRoute: true, … } }
}
…
if (ahead <= nowM && s.announced[i] !== "now") { s.announced[i] = "now"; texts.push(st.text); break; }
if (ahead <= preM && !s.announced[i]) { s.announced[i] = "pre"; texts.push(`In about ${formatDistance(ahead)}: …`); break; }
```

| Rule | Value | Purpose |
|---|---|---|
| pre-announcement | step 70 m ahead (`preM`) | "In about 60 metres: turn left onto …" |
| announcement | step 25 m ahead (`nowM`) | the instruction itself, once |
| already passed | step more than 10 m behind | marked as done, never spoken late |
| arrival | within max(15 m, min(accuracy, 40 m)) of the end | "You have arrived near X" |
| off-route | farther than max(35 m, 1.5 × accuracy) from the route on **2 consecutive** fixes | avoids re-routing on one noisy GPS fix; a less accurate fix gets a wider tolerance |

### Re-routing: `app.js::followActiveRoute` (L402–419)

* **Trigger:** when `followRoute` returns `offRoute: true`, the client calls `planRoute(false)`
  (L353–382) → `POST /api/route` from the *current* position.
* **Result:** it replaces `activeRoute` and speaks "New route: …".
* **No overlap:** a `recalculating` flag stops overlapping requests.

### Spoken output

* The texts go to `voice.say(text, "navigation")`. Navigation has priority 1: obstacle and urgent warnings
  interrupt it, and an interrupted instruction is replayed once (`speech.js` `requeue` L68).
* **"repeat instruction":** the last navigation text is stored in `lastNavText` (app.js L23–27) for the voice
  command "repeat instruction".

## 5.4 Simulated position (testing without walking)

* **Buttons** (`app.js` L339–350):
  * "Simulate at map centre" sets a purple, clearly labelled simulated position;
  * "Move 20 m along route" advances it using `pointAtAlong(poly, along + 20)` (`nav.js` L90–105).
* **Purpose:** the full guidance chain can be demonstrated on the laptop. It is **simulation**, not GPS
  verification.

## 5.5 Evidence

| Evidence | Type |
|---|---|
| `tests/js/web_logic.test.mjs`: projection; pre-announce / announce / arrive; off-route needs 2 fixes and respects accuracy; `pointAtAlong` always advances; straight-line guidance timing and the poor-accuracy message | automated (Node) |
| `tests/js/ui_voice_map_cdp.mjs`: Katpadi → CMC Hospital, 264 simulated steps, spoken steps, arrival | browser E2E (simulated position) |
| Real GPS walk in Vellore | **not done** (acceptance test M3 in `docs/FEATURE_STATUS.md`) |

## 5.6 Limitations

* **GPS accuracy:** phone GPS is typically 5–20 m in cities and worse between tall buildings. That is coarser
  than a pavement.
* **Compass words:** directions are compass words ("north-east") plus turn words relative to the *route*. The
  phone's compass / heading is not used, so "turn left" assumes the user walks along the route direction.
* **Background on iOS:** browsers on iOS suspend JavaScript when the screen locks. Continuous guidance in the
  background needs a native app (future work).
