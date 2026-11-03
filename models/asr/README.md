# Offline voice commands (speech recognition)

| | |
|---|---|
| Model | `vosk-model-small-en-in-0.4/` (Indian English, "for mobile Vosk applications"), 55 MB unpacked |
| Download | https://alphacephei.com/vosk/models/vosk-model-small-en-in-0.4.zip, 37,573,330 bytes, 2026-11-02. `7z t` OK; SHA-256 in `vosk-model-small-en-in-0.4.zip.sha256` |
| Engine | `vosk` 0.3.45 (pip, Windows wheel), Apache-2.0. Model: Apache-2.0 (Alpha Cephei) |
| Runs | on the laptop. The phone sends a short 16 kHz WAV (push-to-talk); no internet is used |

## How it is used (`neurosonic/voicecmd.py`)

Two recognisers run on every utterance:

* a **grammar** restricted to command words (reliable for "start navigation", "stop", "repeat", …);
* **free dictation**, used for destination names.

Place names are then matched to the offline map with text and sound-alike matching. The user's saved places
are checked first.

## Measured (2026-11-02, synthetic speech: the Piper voice with noise off, not human speakers)

| Test | Result |
|---|---|
| 8 fixed commands (start/stop navigation, repeat, start/stop awareness, help, test voice, where am I) | 8/8 intents correct (`tests/test_final_integration.py`) |
| Earlier run with random-noise Piper speech, 15 commands | 13/15 (missed "status" heard as "stardust", "search for VIT") |
| 24 spoken destination commands (12 Vellore places × "navigate to" / "search for") | correct place first **10/24**, in the top 3 **11/24**. Local names are often misheard ("Katpadi" → "cut body", "Bagayam" → "bargain"). The heuristics were tuned on these same 24 samples, so the true accuracy is probably lower |
| Through a real browser (Chrome fake microphone) | "navigate to Katpadi Junction", heard as "navigate took out body junction", resolved to Katpadi Junction |

**Consequence in the app:** a spoken destination is only *proposed*. NeuroSonic says the chosen place and the
alternatives, plans the route, and starts guidance only after "start navigation". Typed search and saved places
remain the reliable ways. Recognition of real users' voices, accents and street noise has **not** been tested.
