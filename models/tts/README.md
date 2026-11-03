# Local neural voice (text-to-speech)

| | |
|---|---|
| Voice folder | `en_IN-spicor/` |
| Files | `en_IN-spicor.onnx` (63,516,050 bytes, SHA-256 `e19debae94b70ecc9d22603820373c4dc9bfceb4de8675e1138d2072fca11494`, matches Hugging Face LFS), `en_IN-spicor.onnx.json` (Piper config), `MODEL_CARD.md` |
| Source | https://huggingface.co/navgurukul-ai-labs/text-to-speech-en-IN-piper (downloaded 2026-11-02; original file name `en_IN-dataset=spicor-english-base=ljspeech-epochs=1089.onnx`, renamed) |
| What it is | Piper VITS voice, Indian English, single speaker, 22,050 Hz. Fine-tuned from the Piper LJSpeech base (1089 epochs) on a dataset called "spicor". Phonemes come from espeak-ng (`en-us`) |
| **Licence** | **AGPL-3.0** (model card). Fine for local research use. If NeuroSonic is ever offered to others as a network service, AGPL obligations apply (source availability). The licence of the "spicor" training data is **not stated** on the model card; check it before any public release |
| Engine | `piper-tts` 1.8.0 (OHF-Voice/piper1-gpl), **GPL-3.0-or-later**; uses `onnxruntime` 1.31.1 (MIT) and bundles espeak-ng |

## Measured on this laptop (CPU)

* Model load: about 2.5 s at server start.
* The acceptance sentence "Hello. This is NeuroSonic. Your voice assistant is working correctly." takes 0.20 s to synthesise.
* Output: 5.34 s of audio, 16-bit mono 22,050 Hz, RMS about 5,300 (not silence). Real-time factor 0.04.
* Intelligibility, as an independent offline check: Windows' built-in speech recogniser (en-GB dictation) transcribed
  the audio as "That this is no sunlink your voice assistant is walking quickly". That is the right sentence
  structure; "NeuroSonic" is not in the recogniser's vocabulary. This is only a rough check, not a listening test.

## Not available / not tested

* **Tamil:** no Tamil Piper voice was downloaded or tested. Tamil support must not be claimed.
* The voice has not been rated by listeners, in particular by visually impaired users.
