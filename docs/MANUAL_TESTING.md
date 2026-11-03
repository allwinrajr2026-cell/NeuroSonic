# NeuroSonic: manual testing guide

**Status (2026-11-02):** none of the tests below has been carried out on a physical iPhone or outdoors. Everything
in `docs/FEATURE_STATUS.md` marked T2 or E2E was verified only automatically or in desktop Chrome with emulated
iPhone metrics, fake camera and microphone, and emulated GPS. Record the result of each test here (date, device, iOS
version, tester, PASS/FAIL, notes).

**Safety rule for every outdoor test:** the tester walks with their usual mobility aid or with a sighted companion.
NeuroSonic is never relied on for safety during testing.

## 0. Setup (once)

1. Laptop and iPhone on the same Wi-Fi network. Allow the Windows firewall rule for Python on that network (see
   `PROJECT_DOCUMENTATION/12_HTTPS_NETWORK_IPHONE.md`).
2. Start the app on the laptop:
   ```bat
   cd F:\Projects\WOAD-Research\implementation
   ..\.venv\Scripts\python neurosonic_app.py --host 0.0.0.0 --https
   ```
3. On the iPhone, open `http://<laptop-ip>:8766` once and install and trust the NeuroSonic local CA certificate.
   Then open `https://<laptop-ip>:8765` in Safari.
4. Tap the screen once, so iOS allows sound. Turn the ring/silent switch to ring and raise the volume.

## 1. Interface (iPhone Safari): test U1

| # | Step | Expected |
|---|---|---|
| U1.1 | Open each tab: Home, Navigate, History, Settings, How it works | no sideways scrolling; nothing hidden under the Safari toolbar, the home indicator or the tab bar |
| U1.2 | Rotate to landscape and back on Navigate | map redraws at the new size, not stretched |
| U1.3 | Tap every button with a thumb | each reacts on the first tap; no mis-taps on neighbouring buttons |
| U1.4 | VoiceOver on: swipe through Home | state, Start, Stop, the mode switch and Speak are announced with sensible names |
| U1.5 | How it works | 10 topics and the architecture diagram are readable without zooming |

## 2. Voice: test V1

| # | Step | Expected |
|---|---|---|
| V1.1 | Settings → Test Voice | Indian-English neural voice; laptop console shows `[voice] … neural voice PLAYED` |
| V1.2 | Stop the laptop server, then Test Voice | message that the laptop is unreachable; device voice used as the fallback |
| V1.3 | Start guidance (simulated) and trigger an obstacle (point the camera at a person close ahead) | "Stop…" interrupts the navigation sentence; the sentence is replayed afterwards |
| V1.4 | Listen for 2 minutes with awareness on in a static scene | no repeated identical messages (a blocked-path reminder at most every 8 s while blocked) |

## 3. Camera walking guidance: test C1 (chest-mounted, then handheld)

Carry the phone chest-mounted with the rear camera facing forward. Use a quiet place with a companion.

| # | Scene | Expected spoken message (Walking Guidance) |
|---|---|---|
| C1.1 | Empty corridor or pavement, good light | after about 1–2 s: "The visible path appears clear. Continue carefully." (once) |
| C1.2 | Companion stands a few metres directly ahead | "Caution. An object is detected in the walking path." |
| C1.3 | Companion stands close, filling the lower centre | "Stop. The walking path may be blocked."; reminder "…may still be blocked" if it persists |
| C1.4 | Companion stands well to the side | no caution; state stays clear (may show the person at the side) |
| C1.5 | Cover the lens / very dark room | "I cannot clearly assess the path. Please check carefully." |
| C1.6 | Wave the phone fast (motion blur) | uncertain rather than clear |
| C1.7 | Switch the camera off in another app / deny the camera | "Camera view is unavailable." |
| C1.8 | Switch to Object Description, repeat C1.2 and C1.4 | object names with side ("Person ahead.", "Person on the right.") in addition to path messages |
| C1.9 | Handheld mode | messages talk about "the camera view", never "the walking path" or "ahead" |

Record any **false clear** (clear spoken while an object recognised by the detector was in the path region) as a
FAIL. Note objects that were *not* recognised (poles, kerbs, steps): these are known limitations, not bugs, but
they must be documented.

## 4. GPS and navigation: tests M3 and G1 (outdoors, Vellore map area)

| # | Step | Expected |
|---|---|---|
| G1.1 | Navigate → Start location; allow location | badge "good" or "weak"; position and accuracy shown; map centres on the blue dot |
| G1.2 | Deny location (Settings › Apps › Safari › Location: Never), reload, Start location | spoken "Location permission denied…", badge "denied" |
| G1.3 | Indoors with poor GPS | "weak" (> 50 m) or "inaccurate" (> 100 m, guidance paused) |
| M3.1 | Search a nearby destination, Preview, Start | route on the map; first instruction spoken |
| M3.2 | Walk the route | turn pre-announcements about 70 m before and the instruction about 25 m before each turn |
| M3.3 | Deliberately leave the route by > 40 m | after two fixes: "You appear to be off the route. Recalculating." then "New route…" (at most once per 15 s) |
| M3.4 | Enter a building or underpass for > 20 s | "GPS signal lost. Guidance paused…" and later "GPS signal restored." |
| M3.5 | Arrive | "You have arrived near …" |

Record GPS accuracy values, wrong turn instructions and street names that were missing or wrong.

## 5. Offline and network: test O1

| # | Step | Expected |
|---|---|---|
| O1.1 | Disconnect the router from the internet (keep the Wi-Fi) | everything still works: voice, commands, map, route, camera |
| O1.2 | Turn the laptop Wi-Fi off during awareness | within about 3 s: "Camera view is unavailable."; after the connection returns, "Connection to the laptop restored." |

## 6. Voice commands: test A1

Say each command after tapping Speak: "start awareness", "stop awareness", "status", "repeat instruction",
"navigate to CMC hospital", "start navigation", "stop navigation", "help". Record what was heard
(`mic-status` line) and whether the action was correct.

## 6b. Online scene description: test S1 (needs internet on the laptop)

| # | Step | Expected |
|---|---|---|
| S1.1 | Home → Describe (first time) | consent text shown and spoken; **no photo sent** until Allow |
| S1.2 | Allow → point the camera at a street | "Looking." then "AI description: …" within the time budget, or a spoken failure message |
| S1.3 | Type "Is there a bus stop?" → Describe | answer to the question, or "cannot answer from the photo" |
| S1.4 | Say "describe surroundings" | same as S1.2 |
| S1.5 | Unplug the laptop's internet, Describe | "Online scene description is unavailable right now. Local walking guidance continues."; walking guidance keeps speaking |
| S1.6 | Settings → untick the consent box → Describe | consent request again; no photo sent |
| S1.7 | Check History | text only; no photos |

Record the latency and any description that claims safety, gives distances or invents objects (FAIL).

## 7. Automated checks before a manual session

```bat
..\.venv\Scripts\python -m unittest discover -s tests -t .
:: with the app running on port 8799 (127.0.0.1):
node tests\js\ui_refine_cdp.mjs http://127.0.0.1:8799 "C:/Program Files/Google/Chrome/Application/chrome.exe"
..\.venv\Scripts\python tools\make_e2e_media.py --out e2e_media
node tests\js\ui_final_cdp.mjs http://127.0.0.1:8799 "C:/Program Files/Google/Chrome/Application/chrome.exe" e2e_media\fake_mic.wav e2e_media\fake_cam.y4m
```

## 8. Results log

| Date | Test | Device / iOS | Tester | Result | Notes |
|---|---|---|---|---|---|
| — | — | — | — | not yet performed | — |
