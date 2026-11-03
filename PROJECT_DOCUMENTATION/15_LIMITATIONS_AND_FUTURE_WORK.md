# 15. Known limitations and future development

## 15.1 Limitations (current state, 2026-11-02)

### Architecture

1. **Server-dependent phone.** All models run on the laptop; the phone is a browser client over local Wi-Fi.
   Without the laptop there is no detection, no neural voice, no recognition and no routing. "Offline" means
   *no internet*, not *standalone phone*.
2. **No authentication** on the API; it is only for trusted networks.
3. **iOS stops JavaScript when the screen is locked**, so continuous background guidance needs a native app.

### Perception

4. **WOAD needs the Synexens CS30 near-IR + depth sensor**, which is not connected. In the app, WOAD runs on
   *recorded* frames only.
5. **WOAD accuracy on new scenes is low:** person AP@0.5 0.17–0.22 cross-dataset. Its 0.669 mAP cannot be
   verified.
6. **The RGB camera detector is generic** (SSDLite320, COCO mAP 21.3):
   * it is not validated on Indian streets or for assistive use;
   * it cannot see steps, kerbs, holes, poles or walls;
   * it gives **no distance**;
   * the "Caution" rule (≥ 25 % of the image, centre third) is an unvalidated heuristic.
7. **Handheld mode** changes only the wording. Device orientation sensors are not used.
8. **The event-camera simulation** is a frame-differencing demo, not a real event camera or obstacle detector.

### Voice

9. **Spoken place names are often misheard:** 10/24 correct first on synthetic speech, with heuristics tuned on
   those samples. Fixed commands work (8/8 synthetic); real voices are untested.
10. **Push-to-talk only;** there is no wake word.
11. **Licences:** the Piper voice is AGPL-3.0 and Piper is GPL-3.0+. Tamil TTS is not available.

### Navigation

12. **OSM data gaps:**
    * few named streets, so "the unnamed road" is common;
    * no pavements, crossings or traffic data;
    * buildings missing;
    * the coverage is a 15 × 15 km box.
13. **No pedestrian-specific costs.** Major roads are only reported, not avoided.
14. **GPS accuracy** (typically 5–20 m) is coarser than a pavement. The compass heading is not used.
15. **No real walking test.** Route following was only simulated.

### Evaluation and validation

16. **No physical verification** on the iPhone, in the street, or with visually impaired users.

## 15.2 Future development (prioritised)

| Priority | Work | Addresses |
|---|---|---|
| 1 | Run the pending acceptance tests: iPhone Test Voice (A1), voice command (V1), camera awareness (C1), physical offline test (O1), short real walk with a sighted companion (M3) | 16, 1 |
| 2 | Collect a small Vellore dataset (phone video + labels) and **measure** the RGB detector; replace or fine-tune it (e.g. a YOLO-family model for pedestrians, two-wheelers, cows, poles, kerbs, steps); add ground-hazard classes | 6 |
| 3 | Larger or custom speech model: add Vellore place names to a Vosk grammar/lexicon, or use Whisper small with a place-name prompt; real-user recordings | 9 |
| 4 | Connect the CS30 sensor (SDK capture bridge) to run WOAD live; recover the SDK colormap and exposure settings; metric distance from raw 16-bit depth | 4, 5 |
| 5 | Standalone phone: a native or PWA app with on-device inference (ONNX/TFLite/Core ML), Piper on device, a local map package; background location and audio | 1, 3 |
| 6 | Pedestrian routing costs (footways preferred, major roads penalised), crossings; a larger region; OSM buildings when Overpass is available | 12, 13 |
| 7 | Device heading (compass) for "turn left now", relative to the user's body; orientation-aware handheld mode | 7, 14 |
| 8 | Authentication (pairing code) and HTTPS-only setup; licence review before distribution | 2, 11 |
| 9 | Usability study with visually impaired users; tune alert thresholds and wording | 16 |
