# 7. Neural text-to-speech with Piper

## 7.1 Problem and choice

Every alert and instruction must be spoken clearly, in an accent familiar to Indian users, without internet,
and on an iPhone.

| Option | Comment |
|---|---|
| Browser `speechSynthesis` | available, but voices and offline behaviour differ per device; kept as the **fallback** |
| Cloud TTS (Google, Azure) | needs internet; excluded |
| **Piper** | **chosen**: fast neural TTS (VITS models exported to ONNX), runs on CPU, offline, many voices including an Indian-English one |

* **Engine:** `piper-tts` 1.8.0 (OHF-Voice/piper1-gpl), **GPL-3.0-or-later**. It bundles espeak-ng for
  phonemisation and uses `onnxruntime` 1.31.1.
* **Voice:** `models/tts/en_IN-spicor/en_IN-spicor.onnx`, from Hugging Face
  `navgurukul-ai-labs/text-to-speech-en-IN-piper`.
  * 63,516,050 bytes; SHA-256 `e19debae…1494`, which matches the Hugging Face LFS hash.
  * **Licence AGPL-3.0.** The licence of its training data ("spicor") is not stated on the model card.
  * Fine-tuned from the Piper LJSpeech base; 22,050 Hz mono, single speaker.

## 7.2 How Piper works (for the viva)

1. **Text → phonemes:** espeak-ng converts the text into phonemes (voice `en-us` rules, per the model config).
2. **Phonemes → IDs:** `phoneme_id_map` in `en_IN-spicor.onnx.json`.
3. **IDs → waveform:** a **VITS** model, an end-to-end neural network. Its text encoder, stochastic duration
   predictor and normalising flow are combined with a HiFi-GAN-style decoder that generates the audio samples
   directly. Its `noise_scale` / `noise_w` add natural variation, which is why two syntheses of the same text
   can differ slightly.
4. The result is written as 16-bit PCM WAV.

## 7.3 Implementation: `neurosonic/tts.py`

* **`PiperTTS._load`** (L65–73): `PiperVoice.load(model)`. It is loaded at start-up by `warm_up` (L75–83), so the
  first request is not slow.
* **`clean`** (L87–93) normalises whitespace and rejects empty text or text over `MAX_CHARS` = 400.
* **`synthesize`** (L95–130) uses a **3-level cache**:
  1. in-memory `OrderedDict` (64 entries);
  2. disk `data/tts_cache/<sha256(voice + text)>.wav` (up to 400 files, oldest removed by `_trim_cache`
     L138–141);
  3. otherwise synthesis under a lock.
  ```python
  key = hashlib.sha256((self.model_path.name + "\0" + text).encode("utf-8")).hexdigest()
  …
  with self._lock:
      voice = self._load()
      buf = io.BytesIO()
      with wave.open(buf, "wb") as w:
          voice.synthesize_wav(text, w)
  ```
* **Errors:** a synthesis exception becomes `TTSError`, which the server returns as HTTP 503
  (`server.py::_dispatch` L133–155). The server never crashes on a bad request.

### Delivery: `server.py::r_tts` (L249–253) and `_send_media` (L255–272)

* `GET /api/tts?text=…` returns `audio/wav`.
* **HTTP Range** is supported (206 Partial Content, 416 when out of range). iOS Safari/WebKit fetches media in
  byte ranges, for example `bytes=0-1` first.
* `Cache-Control: private, max-age=86400`.

### Playback on the phone: `web/js/speech.js`

* `Announcer._neuralUrl` (L216–231) fetches the WAV as a **blob** and creates an object URL (client cache of 40).
  A blob also avoids range-request problems.
* `_playNeural` (L233–258) plays it through **one reusable `<audio>` element**:
  * a timeout of clip length + 4 s, so a stuck clip never blocks the queue;
  * an `_abort` hook for interruption.
* **iOS unlock** (`unlock` L118–135). Inside the user's first tap, it:
  * sets `navigator.audioSession.type = "playback"` (Safari 17+);
  * resumes the WebAudio context;
  * plays a 0.05 s silent WAV (`silentWavBytes` L82–89) on the same `<audio>` element;
  * speaks an empty utterance.

  After this, iOS allows programmatic playback.
* **Fallback:** if neural playback fails, `_playBrowser` (L260–278) uses `speechSynthesis`. The failure is
  shown in Settings and reported to the laptop (`POST /api/voice/report`, printed as
  `[voice] <ip> iPhone/Safari: neural voice FAILED (…)`).

## 7.4 Measured results

| Measurement | Value | Evidence |
|---|---|---|
| Model load | 2.5–4.3 s across the observed start-ups (e.g. 2,542 ms, 3,228 ms, 4,257 ms) | console "Voice: … loaded in N ms", `/api/tts/status` `load_ms` |
| Synthesis of "Hello. This is NeuroSonic. Your voice assistant is working correctly." | 0.20 s for 5.34 s of audio (real-time factor 0.04), 22,050 Hz mono 16-bit, RMS ≈ 5,300 (not silence) | session measurement; `test_acceptance_sentence_is_real_speech_audio` (3–9 s, RMS > 500) |
| Intelligibility (objective, offline) | the Windows speech recogniser transcribed it as "That this is no sunlink your voice assistant is walking quickly" (right sentence structure; "NeuroSonic" is not in its vocabulary) | session check; a rough proxy, not a listening test |
| Range support | 200 / 206 `bytes=0-1` / 206 open range / 416 | `test_tts_endpoint_and_ranges` |
| Offline | 0 network attempts | `test_works_without_internet` |
| Real browser | Test Voice played 5.24 s to `ended`; report PLAYED | `ui_voice_map_cdp.mjs`, `ui_final_cdp.mjs` |
| **iPhone audible playback** | **not yet confirmed** | acceptance test A1 |

## 7.5 Likely questions

* *Why generate audio on the laptop and not on the phone?* Piper runs in Python with onnxruntime on the laptop.
  Running it on the phone would need a WebAssembly or native build (future work). The cost is that speech needs
  the Wi-Fi link.
* *How do you avoid repeating the same synthesis?* The SHA-256 cache key over voice + text, in memory, on disk
  and on the client.
* *What if two alerts arrive at once?* The client queue speaks them one after another by priority. The server
  serialises synthesis with a lock.
