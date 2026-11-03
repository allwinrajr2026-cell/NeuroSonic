# NeuroSonic: user guide and demonstration instructions

> **Live demo video:** [https://drive.google.com/file/d/1yJS2f8_ee3ZwV55mkA9e1c6mm9f5xkYd/view?usp=sharing](https://drive.google.com/file/d/1yJS2f8_ee3ZwV55mkA9e1c6mm9f5xkYd/view?usp=sharing)

NeuroSonic is an assistive **research prototype**:

* It is **not** a safety device and not a replacement for a cane, guide dog or human assistance.
* It sees only what the phone camera sees, in front. It is not 360-degree vision.
* It gives no distances.

## 1. Screens

| Screen | What it does |
|---|---|
| **Home** | camera walking guidance. Start / Stop; the state card (Path appears clear / Caution / Stop / Cannot assess / Camera unavailable); a switch between **Walking guidance** (only changes are spoken) and **Object description** (object names with left / centre / right); chips for GPS, carrying mode, fps and **detector** ("RF-DETR · GPU" or "SSDLite · CPU"); online scene description (opt-in) |
| **Navigate** | offline Vellore map, GPS panel (accuracy, fix age), destination search, route preview and guidance, simulated walk for indoor demos, saved places |
| **Speak** (centre button) | voice commands: "start awareness", "stop awareness", "status", "navigate to …", "start navigation", "stop navigation", "repeat instruction", "describe surroundings", "help" |
| **History** | every spoken alert, with its time (text only, no images) |
| **Settings** | voice and Test Voice, Object Description, carrying mode (chest / handheld), permissions, offline status, research tools |
| **How it works** | plain-language explanation and limitations |

## 2. What the voice says

| Message | Meaning |
|---|---|
| "The visible path appears clear. Continue carefully." | no *recognised* object in the lower-central path region for a few frames. **Not "safe".** |
| "Caution. An object is detected in the walking path." | a recognised object overlaps the path region |
| "Caution. A person is moving into your path from the left." | a tracked person (or vehicle or animal) moved into the path region by itself, with the camera's own motion compensated |
| "A bicycle is crossing in front of you, from left to right." | a tracked object crossed the view further ahead |
| "Stop. The walking path may be blocked." | an object fills a large part of the path region (urgent; interrupts other speech) |
| "I cannot clearly assess the path. Please check carefully." | image too dark or blurred |
| "Camera view is unavailable." | no picture, or the laptop cannot be reached |
| "AI description: …" | online description (Gemini); may be wrong; never a safety statement |

## 3. Demonstration (about 6 minutes)

1. **Laptop:**
   * start from `.venv-gpu` (`publication/INSTALLATION_AND_DEPLOYMENT.md` §3);
   * show the console line "RF-DETR Nano … on the NVIDIA GPU ready";
   * keep the console visible.
2. **iPhone:**
   * open the app and tap once for sound;
   * **Settings → Test Voice**;
   * Home: point out the **"RF-DETR · GPU"** chip.
3. **Home → Start**, phone held at chest height, camera forward:
   * a colleague walks into view from one side → "Caution. A person is moving into your path from the left/right.";
   * the colleague stands close in front → "Stop. The walking path may be blocked.";
   * point out the fps chip (about 5) and the status line (detector ms, camera → answer ms).
4. **Object description:** switch it on and point at a chair or a bicycle: "Chair on the left."
5. **Navigate:**
   * search "CMC Hospital" → Preview → Start;
   * open "Testing without walking" → Simulate at centre → Move 20 m a few times: spoken turns.
6. **Speak:** "status", then "describe surroundings". Say that the description needs internet and permission, and
   may be slow or unavailable.
7. **How it works**, then the limitations: no distances; misses steps, kerbs and holes; needs the laptop; not
   field-validated.

## 4. Good practice

* Chest-mounted, camera forward, gives the most meaningful directions. Handheld messages refer to "the camera view".
* Keep the Safari page open. iOS stops the camera when the screen locks.
* Keep the laptop on mains power during use.
