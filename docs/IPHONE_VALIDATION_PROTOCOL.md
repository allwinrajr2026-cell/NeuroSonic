# NeuroSonic: physical validation protocol (iPhone + HP Omen laptop)

**Status:** none of these tests has been performed yet. Results go into `docs/validation_results_template.csv`, one
row per trial. Never fill a row without performing the trial.

**Three kinds of evidence, never mixed:**

| Kind | Where | What it shows |
|---|---|---|
| Laptop benchmark | `docs/PHASE1_GPU_DETECTOR_BENCHMARK.md`, `outputs/benchmarks/` | detector speed and accuracy on recorded images |
| Automated tests | `python -m unittest`, `tests/js/*_cdp.mjs` | logic, API, browser behaviour with a fake camera |
| **Physical iPhone tests** (this document) | your phone, real scenes | whether it works for a person, in the world |

**Safety for every trial:**

* The tester walks with a sighted companion or with their usual mobility aid.
* Vehicles are only observed from a safe place, such as a pavement or a parked position. Nobody steps into traffic.
* NeuroSonic is never relied on.

## 0. Setup (each session)

1. On the laptop (HP Omen, mains power, on the same Wi-Fi as the phone):
   ```bat
   cd F:\Projects\WOAD-Research\implementation
   ..\.venv-gpu\Scripts\python neurosonic_app.py --host 0.0.0.0 --https
   ```
   The console must say `Camera awareness: RF-DETR Nano ... on the NVIDIA GPU ready (cuda; frame interval 200 ms ...)`.
   If it says SSDLite, record "fallback" in every row.
2. On the iPhone, in Safari, open `https://192.168.1.5:8765`. Tap once for sound, then **Settings → Test Voice**.
3. **Home:** the chip must read **"RF-DETR · GPU"**. Press **Start**. Carry the phone chest-mounted, camera forward,
   unless the trial says otherwise.
4. **Logging:**
   * The laptop terminal shows `[awareness]` and `[vision]` lines.
   * `https://127.0.0.1:8765/api/awareness/status` (open it on the laptop) shows `clients`: the phone's IP, frames,
     detector and median processing time. Note these at the start and end of the session.
   * The History tab shows every spoken alert with a timestamp.
5. **Timing:** a second person with a stopwatch, or a screen recording of the phone with sound. Measure from the
   moment the event happens (for example, a person steps into the path) to the start of the spoken alert.

## 1. Scenarios

Each scenario has a code (used in the CSV) and should be repeated **5 times**. Record each trial.

| Code | Scenario | Set-up | Expected behaviour (pass) | Record |
|---|---|---|---|---|
| P1 | Person walks into the path from the side | stationary tester; companion steps into the lower centre from left, then right, 3–5 m ahead | "Caution. A person is moving into your path from the left/right." or "Caution. An object is detected in the walking path."; correct side | message, side correct (y/n), latency (s) |
| P2 | Person approaching head-on | companion walks straight towards the stationary tester | "Caution…" then "Stop. The walking path may be blocked." before the person is within arm's reach. *No "approaching" message exists by design* | messages, latency to "Stop" (s) |
| P3 | Person crossing in front, further away | companion crosses the view about 6–10 m ahead | "A person is crossing in front of you, from left to right." (or no message: acceptable) | message, direction correct |
| V1 | Car passing (observed safely) | tester stands on the pavement, phone towards the road | path or crossing messages for vehicles; no false "Stop" for cars outside the path region | messages, false alarms |
| V2 | Motorcycle / bicycle | as V1 | correct class in Object Description mode; crossing message possible | class correct (y/n) |
| S1 | Static obstacle (chair, bench, parked bicycle) in the path | tester walks slowly towards it | "Caution…" / "Stop…" at some point; **no** "moving into your path" (it does not move) | messages, false event (y/n) |
| S2 | Obstacle outside the path, at the side | object at the left or right edge | no "Stop"; at most "Caution" | false alarm (y/n) |
| W1 | Walking with the phone (chest) through a corridor with people | normal walking pace | alerts still sensible; note any false "moving into your path" caused by walking | false events per minute |
| W2 | Handheld, phone swinging | deliberately unsteady phone | events suppressed (camera motion); path state may say "cannot assess" | false events (count) |
| L1 | Bright daylight outdoors | P1 outdoors | as P1 | |
| L2 | Dim indoor light | P1 in a dim room | as P1, or "I cannot clearly assess the path. Please check carefully." | |
| L3 | Dark / lens covered | cover the lens for 5 s | "I cannot clearly assess the path…", then recovery when uncovered | message, recovery (y/n) |
| B1 | Blur | shake the phone quickly | uncertain rather than "appears clear" | false "clear" (y/n) |
| R1 | Voice-alert responsiveness | any P1 trial | latency from event to start of speech ≤ 2 s target (not a guarantee) | latency (s) |
| R2 | Interruption | start navigation guidance, then trigger P2 | "Stop…" interrupts the navigation sentence, which is repeated afterwards | (y/n) |
| G1 | GPS fix | Navigate → Start location, outdoors | badge "good" or "weak"; accuracy shown | accuracy (m) |
| G2 | Short route walk (with a companion) | destination 200–500 m away in Vellore | turn announcements about 70 m and 25 m ahead; arrival message | missed / wrong turns |
| G3 | Off-route | leave the route by > 40 m | "You appear to be off the route. Recalculating." then a new route | (y/n), time (s) |
| N1 | Wi-Fi drop | switch the laptop's Wi-Fi off for 10 s during awareness | "Camera view is unavailable." / "Connection to the laptop lost." within about 3 s; recovery after reconnecting | messages, recovery time |
| N2 | Internet off, local Wi-Fi on | unplug the router's internet | walking guidance, voice, map and routing keep working; Describe says it is unavailable | (y/n) per feature |
| C1 | Cloud description | Describe (opt-in) with internet | "Looking." → "AI description: …" or a spoken failure; "Still waiting…" after 15 s | time (s), outcome |
| C2 | Cloud slow / unavailable | Describe on a poor connection | guidance continues during the wait; clear failure message | guidance continued (y/n) |
| T1 | 15-minute session | continuous awareness, walking indoors | no crash; frame rate stays about 5 fps (the fps chip); phone temperature and battery drop noted | fps start/end, battery %, issues |

## 2. Recording rules

* Record **every** trial, including failures and missed alerts. A missed alert is the most important result.
* Latency is measured, not estimated. Write "n/a" if it was not measured.
* Note lighting, location (indoor or outdoor) and carrying mode for each row.
* Do not change thresholds during a session. If something is changed, start a new session and note it.

## 3. Summary to compute afterwards

For each scenario:

* the detection rate (alerts / trials);
* the false alarms;
* the median and maximum latency.

Report them separately from the laptop benchmarks and automated tests, together with the number of trials.
