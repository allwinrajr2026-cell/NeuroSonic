# Stage 2: replay source, input-quality check and alert logic

Status: implemented and tested (2026-11-02). Text alerts only: speech is Stage 4, and live sensor input
is Stage 3.

```
ReplaySource ──► InputQualityChecker ──► WOADDetector (skipped if input unusable) ──► AlertEngine ──► transcript
 (woad/sources.py)  (woad/quality.py)        (woad/detector.py)                       (woad/alerts.py)
```

Run it:

```bat
python woad_replay.py --source demo_data/detec_test --segment-gap 10
python woad_replay.py --source demo_data/detec_test --segment-gap 10 --from-results outputs/demo_detec_test/results.json
```

## Components

**Replay source** (`woad/sources.py`, `ReplaySource`):

* Pairs IR and depth by filename and orders frames by the number in the name.
* Timestamps are synthetic (`index / fps`), so a replay is deterministic.
* `--segment-gap N` starts a new clip when the filename number jumps by more than N. The alert
  engine then resets tracking, so no object is carried across a cut.
* Unreadable files are passed on as error frames, not skipped.
* A live CS30 source (Stage 3) will yield the same `Frame` objects.

**Input-quality check** (`woad/quality.py`). Thresholds come from the per-frame IR statistics of all
local data sets:

| Rule | detec_test (600) | exp72 val recon (187) | labelled VOCdetiv (1,651) | raw CS30 recording (501) |
|---|---|---|---|---|
| OK | 100 % | 100 % | 89.4 % | 1.4 % |
| WARN: IR mean < 100 or std < 40 | 0 % | 0 % | 7.4 % | 56.1 % |
| UNUSABLE: IR mean < 40 or std < 10 | 0 % | 0 % | 3.2 % | 42.5 % |

The check also covers depth (UNUSABLE if more than 95 % of pixels are invalid) and IR/depth size
mismatch (WARN).

Why it matters: the brightness experiment (EVALUATION.md section 8) showed that dark input removes
detections and creates false "person" alarms. UNUSABLE frames are not sent to the detector.

This check is a coarse guard. A frame that passes can still be out of distribution.

**Alert engine** (`woad/alerts.py`, `AlertEngine`). Default `AlertConfig` values:

| Rule | Default | Purpose |
|---|---|---|
| `alert_conf` | 0.40 | Detections below this are never announced. The detector itself runs at 0.25. |
| Position | thirds of the IR frame, by box centre | "on the left" / "ahead" / "on the right". **"ahead" = middle of the camera view, not a distance or collision claim.** |
| Confirmation | 2 of the last 3 frames (IoU tracks ≥ 0.3) | Suppresses single-frame flicker. |
| `repeat_s` | 15 s | A still-present object is re-announced. A change of position is announced immediately. |
| `cooldown_s` | 5 s | Other objects of the same class and position are covered by a recent message. |
| Per frame | at most 2 messages | Same class and position are merged ("2 people detected ahead"). Order: Car > E-bike > person, then larger box. Deferred groups follow in the next frames. |
| Unavailable | after 1 s of unusable input or unreadable frames, or 2 s without any frame (`tick()` watchdog) | "Obstacle detection unavailable: <reason>." While unavailable, **no object alerts**. |
| Resumed | after 1 s of usable input | "Obstacle detection resumed." |
| Low-quality notice | WARN frames, at most every 30 s | "Camera image quality is low. Detections may be unreliable." |

Messages are fixed templates filled only from the class name and position of detections **present
in the current frame**. A randomised test checks this invariant. Events carry a `priority`: system
100/90/50, objects 10 + class priority. Stage 4 will use it to merge alerts with navigation speech.

## Results (2026-11-02)

| Replay | Frames / clips | Quality | Alerts |
|---|---|---|---|
| `demo_data/detec_test`, `--segment-gap 10`, 5 fps (`outputs/replay_detec_test_live`) | 600 / 240 | 600 OK | 46 object alerts (about 1 per 2.6 s of replay), 0 system |
| same with `--from-results` (`outputs/replay_detec_test_cached`) | | | **byte-identical transcript** to the live-model run |
| raw CS30 recording (`outputs/replay_sensor_recording`) | 501 / 1 | 7 OK, 281 WARN, 213 UNUSABLE | 0 object alerts; 18 system alerts (7 unavailable/resumed cycles, 4 low-quality notices) |

Example transcript lines (detec_test):

```
[    74.8s  #374  0000060711.png] 2 people detected ahead.
[    86.8s  #434  0000061198.png] Car detected on the left.
```

The full transcript is `outputs/replay_detec_test_live/transcript.txt`.

## Tests (`tests/test_alerts.py`, 18 tests)

* Flicker suppression and single announcement.
* Wording for all positions and classes.
* Confidence threshold, repetition timing, position change.
* Merging, priority and per-frame limit.
* "No alert without a current detection" invariant (300 random frames).
* Unavailable → resumed and silence while unavailable; read errors.
* Low-quality rate limit, stall watchdog, segment reset, config validation.
* Quality levels on synthetic and real frames.
* Replay ordering, segments, timestamps and error frames.
* **Deterministic CLI transcript** with the real model: two runs, identical output.

## Limitations and open questions

1. **detec_test is not a continuous stream.**
   * Its 600 frames form 240 clips (median length 1 frame).
   * Of the 89 clips with a detection ≥ 0.40, 27 produced an alert. 32 are single-frame clips, which
     cannot meet a 2-of-3 confirmation by design; the others had a detection in only one frame.
   * Alert rates on a real 10–15 fps stream will differ, and **need a continuous recording**
     (Stage 3 hardware).
2. **The default values are engineering guesses, not validated with visually impaired users.**
   This covers thresholds, timing and wording. Confirmation trades speed for fewer false alerts:
   2 of 3 frames at 5 fps adds 0.2–0.4 s of delay.
3. **Unavailable/resumed flapping.** On the dark recording the state switched 7 times in 100 s.
   Options: a longer resume time, or a minimum time between state messages. This should be decided
   together with user testing.
4. **Alerts inherit the model's errors.** Missed people, false "Car" boxes and bicycles called
   "E-bike" all pass straight through. The engine only reduces flicker and repetition; it cannot
   add accuracy.
5. **No distance or urgency.** Box size is used only for ordering. Distance would need raw depth
   (Stage 3).
