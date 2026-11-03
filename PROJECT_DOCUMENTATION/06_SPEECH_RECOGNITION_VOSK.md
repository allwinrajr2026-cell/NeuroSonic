# 6. Offline speech recognition with Vosk

## 6.1 Problem and choice of technology

The user must be able to control NeuroSonic by voice, without internet.

| Option | Why not chosen / chosen |
|---|---|
| Browser Web Speech API (`SpeechRecognition`) | in Chrome it sends audio to Google's servers (online); not available in Chrome on iOS |
| Whisper (OpenAI) | accurate, but large and slow on a laptop CPU for push-to-talk |
| **Vosk** (Kaldi-based, Alpha Cephei) | **chosen**: fully offline, small models, runs on CPU, an Indian-English model exists, supports a restricted *grammar* for commands, Apache-2.0 |

* **Model:** `models/asr/vosk-model-small-en-in-0.4` (Indian English, "for mobile Vosk applications"). The zip is
  37,573,330 bytes; 55 MB unpacked.
* **Engine:** `vosk` 0.3.45 (pip).

## 6.2 How Kaldi/Vosk recognition works

1. **Features:** the audio (16 kHz mono) is cut into ~25 ms frames, and acoustic features (MFCC-like, plus
   i-vectors for speaker adaptation; see the `ivector/` folder of the model) are computed.
2. **Acoustic model** (`am/`): a neural network gives, for each frame, the probabilities of phonetic states.
3. **Decoding graph** (`graph/`): a weighted finite-state transducer (HCLG). It combines the phonetic context
   (H, C), the pronunciation lexicon (L) and the language model (G). A beam search finds the most probable word
   sequence.
4. **Grammar mode:** when a JSON word list is given, the language model is restricted to those words. The
   recogniser can then only output command words (plus `[unk]`), which makes commands much more robust.

## 6.3 Pipeline in NeuroSonic

### Phone side: `web/js/recorder.js`

* `recordUtterance` (L65–100):
  1. `getUserMedia({audio})`.
  2. A `ScriptProcessorNode` (4,096 samples) collects Float32 blocks. It was chosen because it works in iOS
     Safari.
  3. Each block's RMS level goes to `EndOfSpeech.push` (L48).
* **`EndOfSpeech`** (L42–62):
  * Before speech starts, the background noise level is learned (exponential average).
  * Speech means level > max(0.01, 3 × noise).
  * Recording stops after ≥ 250 ms of speech followed by 1,000 ms of quiet, or at 6 s.
* **Conversion:** `downsample` (L9) averages to 16 kHz; `encodeWav` (L21) writes a 16-bit PCM WAV.
* **Upload:** `app.js::listenOnce` (L817–841) stops any speech first, so the app does not record itself, then
  sends `POST /api/voicecmd?lat&lon` with `Content-Type: audio/wav`.

### Laptop side: `neurosonic/voicecmd.py`

* **`read_wav16k`** (L127–138) validates mono / 16-bit / 16 kHz / ≤ 8 s.
* **`VoiceCommands.transcribe`** (L184–196) runs **two recognisers** on the same audio:
  ```python
  for grammar in (json.dumps(COMMAND_WORDS), None):
      rec = KaldiRecognizer(model, 16000, grammar) if grammar else KaldiRecognizer(model, 16000)
      rec.AcceptWaveform(pcm16k)
      out.append(json.loads(rec.FinalResult()).get("text", ""))
  ```
  * The **grammar** pass (`COMMAND_WORDS` L24) reliably catches *which command* was said.
  * The **free** pass gives the remaining words, needed for place names that are not in the grammar.
* **`parse_intent`** (L74–124) maps the two texts to an intent:
  * `navigate` / `search` (with a query);
  * `start_navigation`, `stop_navigation`, `repeat`, `status`, `awareness_on`, `awareness_off`, `help`,
    `test_voice`, `unknown`.
  * It tolerates known mishearings: "why am i" → status. The free recogniser often mangles the word
    "navigate", so the grammar result decides the intent.
* **`resolve_place`** (L199–222) turns the spoken name into candidate places:
  1. the user's **saved places** (score ≥ 0.75), since names like "home" are ordinary words;
  2. the offline map's text search (`OfflineMap.search`);
  3. **sound-alike** matching (`place_score` L62–71) over all 813 names, trying the query with 0–4 leading
     words dropped, at a 10 % penalty per dropped word.
* **`place_score`** = max of:
  * the text similarity (`difflib.SequenceMatcher`);
  * the similarity of **phonetic keys** (`phonetic` L45–59: spelled-out letters → letters, similar consonants
    merged, vowels dropped). For example, "katpadi" and "cut body" both become `ktpt`;
  * a prefix match.
* **`handle`** (L224–241) returns `{heard, heard_commands, heard_free, intent, query, places, message}`.

### Back on the phone: `app.js::runIntent` (L842–879)

* A **navigate/search** command calls `chooseDestination(best)`. It speaks "Destination: X" (with "best guess"
  for sound-alike matches) plus the alternatives, then plans the route.
* **Guidance only starts after the user says "start navigation".** A misheard place is therefore heard and
  corrected, never followed silently.

## 6.4 Measured results (2026-11-02; synthetic speech from the Piper voice, not human speakers)

| Test | Result | Evidence |
|---|---|---|
| 8 fixed commands (deterministic Piper speech, noise off) | 8/8 correct intents | `tests/test_final_integration.py::test_fixed_commands_from_speech` (passes with ≥ 7) |
| 15 commands, random-noise Piper speech (earlier run) | 13/15 ("status" → "stardust", "search for VIT" missed) | session measurement |
| 24 spoken destinations (12 Vellore places × 2 phrasings) | correct place first 10/24, in the top 3 11/24 | session measurement; heuristics tuned on these same samples, so true accuracy is probably lower |
| Through a real browser (Chrome fake microphone) | "navigate to Katpadi Junction", heard "navigate took out body junction", resolved to Katpadi Junction, route planned, waited for "start navigation" | `tests/js/ui_final_cdp.mjs` PASS |
| With internet blocked | works, 0 network attempts | `TestVoiceCommands.test_offline` |
| Recognition time | about 0.6 s for both passes on one utterance (one measurement) | session measurement |
| Real human voices, accents, street noise, iPhone microphone | **not tested** | acceptance test V1 pending |

## 6.5 Limitations

* The small model does not know Tamil place names ("Bagayam" → "bargain", "Sathuvachari" → "nah we get to
  start"). Fixed commands are reliable; spoken destinations are not.
* Push-to-talk only; there is no wake word.
* Vosk runs on the laptop, so voice commands need the phone ↔ laptop connection.
