# NeuroSonic: online scene description (Sprint 1, 2026-11-02)

The product direction is now **online-first AI environmental intelligence**. Sprint 1 adds the first milestone:

**Phone camera → laptop backend → cloud vision model → scene description → existing Piper voice.**

Local walking guidance, voice commands, the offline map, routing and GPS handling are unchanged. They do **not**
depend on the cloud.

## 1. Rules (decided by the project owner)

1. **Opt-in on first use.** No camera photo is sent until the user taps **Allow** (Home) or ticks the Settings
   checkbox. The phone sends `consent=1`, and the backend refuses without it, so both sides enforce the rule.
   Consent can be withdrawn at any time.
2. **On demand only.** One still photo is sent per request (Describe button, a typed question, "describe
   surroundings" or a spoken question). Video frames are never streamed to the cloud.
3. **No images are stored.**
   * The photo is decoded, resized to at most 1024 px and re-encoded in memory, then sent and discarded.
   * The history keeps only the spoken text and metadata (provider, model, latency, outcome).
   * Logs contain no image data.
4. **The API key stays on the backend.** It is read from `GEMINI_API_KEY`. On Windows, if the server was started from
   a terminal that does not see the variable, it falls back to the user's registry environment.
   * The key is never sent to the phone, never returned by an endpoint, never logged and never written to a file.
   * Error messages are scrubbed of key-like strings.
5. **No safety claims.**
   * The prompt forbids distances and "safe" / "clear" / "no obstacles" statements. A filter on the reply removes
     any such sentence and then adds "Please check the path yourself."
   * Every answer starts with "AI description:".
   * Cloud hazards are spoken as "Possible hazards".
6. **Failures are spoken clearly** and always end with "Local walking guidance continues". Examples:
   "Online scene description is unavailable right now…", "The online description took too long…".

## 2. Architecture

```
web/js/app.js  describeScene(question)
   captureStill(): one JPEG (≤ 1024 px) from the running awareness camera, or a briefly opened camera
   POST /api/vision/describe?session&mode&consent=1&q=…   (30 s client timeout)
        │
neurosonic/server.py  r_vision_describe → SceneAssistant.describe()     (one worker thread per request)
        │
neurosonic/vision/assistant.py  SceneAssistant          provider-independent
   consent / enabled / configured checks
   circuit breaker: 3 failures → paused for 60 s → one trial request
   rate limits: 1 request per 5 s per phone session; 60 per hour
   prepare_image (memory only) · build_prompt · SYSTEM rules
   every attempt gets the full per-attempt timeout (default 30 s, never shrunk); total budget 45 s;
   at most 1 retry, only for a quick 503 / 5xx / network error and only if a full attempt still fits;
   a timed-out request (incl. 504 DEADLINE_EXCEEDED) is never repeated
   compose_speech: "AI description: …", ≤ 400 chars, safety filter
        │
neurosonic/vision/base.py   VisionProvider interface · SCENE_SCHEMA (JSON) · typed errors · scrub()
neurosonic/vision/gemini.py GeminiProvider (google-genai): JSON output, SDK retries off (1 call = 1 request),
                            deadline never below 10 s (the SDK sends it as X-Server-Timeout),
                            SDK timeout + hard guard thread, error mapping (5xx→unavailable, 429, 4xx→rejected,
                            timeouts, network errors)
neurosonic/vision/mock.py   MockProvider: scripted outcomes (ok, 503, timeout, 429, rejected, bad, unsafe, dark, slowN)
        │
web/js/speech.js  category "scene": priority 1 (below "Stop" / "Caution", which interrupt it), kept 30 s in the queue,
                  2 s cooldown, no beep
```

**Changing the provider.** Replacing Gemini means writing one class with `configured()`, `problem()` and
`analyze(request, prompt, system, timeout_s)` that returns the `SCENE_SCHEMA` object, then registering it in
`make_provider`.

## 3. Endpoints

| Endpoint | Result |
|---|---|
| `GET /api/vision/status` | `available, enabled, configured, provider, model, problem, breaker, retry_after_s, requests_this_hour, hourly_cap, min_interval_s, attempt_timeout_s, budget_s, max_retries, requires_internet: true, requires_consent: true, stores_images: false`, request counters, `last_error` (scrubbed). Never contains the key. |
| `POST /api/vision/describe?session=&mode=chest\|handheld&consent=1&q=<question ≤ 300 chars>` | Body is a JPEG or PNG of up to 3 MB. A successful call returns HTTP 200 with `{ok: true, text, summary, answer, objects:[{name, position: left/centre/right/unknown, note}], hazards, uncertainty, image_quality, filtered_sentences, provider, model, latency_ms, attempts, notice}`. |

`/api/vision/describe` responds as follows in other cases:

* **Provider or permission problems:** HTTP 200 with `{ok: false, code, text}`, where `text` is ready to speak.
  The codes are `consent`, `disabled`, `not_configured`, `paused`, `rate_limited`, `hourly_cap`, `unavailable`,
  `timeout`, `provider_rate_limited`, `rejected`, `bad_response` and `error`.
* **Bad input:** 400 (bad image, too small or empty), 413 (too large) or 415 (wrong type).
* **Vision not configured:** 503.

## 4. Configuration

| Setting | Default |
|---|---|
| `--vision-provider gemini\|mock\|off` or `NEUROSONIC_VISION_PROVIDER` | `gemini` |
| `--vision-model` or `NEUROSONIC_VISION_MODEL` | `gemini-3.8-flash` |
| `GEMINI_API_KEY` (laptop only) | required for Gemini |
| `NEUROSONIC_VISION_TIMEOUT_S` | `30` s per attempt; raised to the provider minimum (Gemini 10 s) if lower |
| `NEUROSONIC_VISION_BUDGET_S` | `45` s for the whole request incl. the retry; never shorter than one attempt |
| `NEUROSONIC_VISION_MOCK_SCRIPT=ok,503,slow20,…` | tests and demos with the mock provider only |

```bat
:: normal start (Gemini, needs internet on the laptop for scene description only)
..\.venv\Scripts\python neurosonic_app.py --host 0.0.0.0 --https
:: demonstration without internet / without Gemini
..\.venv\Scripts\python neurosonic_app.py --vision-provider mock
```

## 5. Voice commands

* "describe surroundings", "what is around me" and "what is in front of me" map to `describe_scene`.
* Questions starting "is there…", "can you see…", "what is…", "where is…" or "how many…" (at least 3 words) map to
  `ask_scene`.
* Both are checked only after all existing commands, so "where am I" is still *status*.
* Free-form questions depend on Vosk's free dictation, which is weak for unusual words. The question box on Home
  is the reliable way to ask.

## 6. Verification (2026-11-02)

| Check | Result |
|---|---|
| `tests/test_vision.py`: 40 tests, mock provider and fake Gemini client only, inside the no-internet guard | OK |
| `tests/js/vision.test.mjs`: 3 Node tests (scene speech category) | OK |
| Full suite `python -m unittest discover -s tests -t .` | **Ran 182 tests, OK (1 skipped: the opt-in live test)**, 32 Node tests inside (after the deadline fix) |
| `tests/js/ui_vision_cdp.mjs` (Chrome, iPhone size, fake camera, mock provider scripted ok → 503 → 503) | **PASS**. Consent requested before any upload (0 uploads); after Allow, "AI description: …" spoken; question passed through; simulated outage spoken as "Online scene description is unavailable right now. Local walking guidance continues."; walking guidance kept running during the outage; withdrawing consent stopped uploads; history text only; no horizontal overflow; 0 external browser requests; 0 JS errors |
| `tests/js/ui_vision_slow_cdp.mjs` (mock provider answering after 20 s) | **PASS**: "Still waiting for the online description. Local walking guidance continues." at 15.2 s, description at 20.2 s, 50 camera frames analysed during the wait (≈ 2.5 per second, unchanged), walking-guidance state stayed available |
| The four earlier browser tests (smoke, voice + map, refine, final) | **PASS** |
| **The one approved live Gemini request** (`tests/test_vision_live.py`, `NEUROSONIC_LIVE_VISION=1`; `test_street.jpg`, 943 × 830, a Street View screenshot of a Vellore road with map-interface overlays) | 2026-11-02 22:07 IST, model `gemini-3.8-flash`, **1 request, no retry: no reply within 25 s (ReadTimeout after 25.9 s), code `timeout`**. The spoken fallback was "The online description took too long. Local walking guidance continues." The record is in `data/vision_live_result.json` (no key, no image). **No successful cloud description has been obtained yet.** |

### Deadline fix after the iPhone test (2026-11-02, later)

Errors seen on the iPhone: `504 DEADLINE_EXCEEDED`, `400 INVALID_ARGUMENT … Manually set deadline 4s is too short.
Minimum allowed deadline is 10s`, and failures after 2 attempts.

**Root cause.** Two things combined:

* The SDK sends the per-attempt timeout to Google as the server deadline (`X-Server-Timeout = ceil(seconds)`).
* `SceneAssistant` gave a retry only the leftover budget: 15 s minus about 10 s minus the backoff, which is about
  4 s. The 12 s first attempt was also too short for the model (504).

The SDK's own retries were already off (`HttpRetryOptions(attempts=1)`); the second attempt came from SceneAssistant.

**Fix:**

* No call is ever made with a deadline below 10 s (`GeminiProvider.min_timeout_s`).
* Every attempt gets the full per-attempt timeout (default 30 s).
* A timeout (incl. 504) is never retried.
* A quick 503 / 5xx / network error gets the one existing retry, only if a full attempt still fits in the 45 s budget.
* Both values are configurable (`NEUROSONIC_VISION_TIMEOUT_S`, `NEUROSONIC_VISION_BUDGET_S`).
* The phone waits 60 s, and says once after 15 s: "Still waiting for the online description. Local walking guidance
  continues."
* The circuit breaker (3 failures → 60 s pause) and the rate limits (5 s per session, 60 per hour) are unchanged.

**Tests.** `TestTimeoutPolicy` has 9 tests. They use the real SDK header function, a fake clock and a provider that
behaves like the observed service, with no network. They failed 11 times against the old code (9 failures, 2 errors)
and pass with the fix. The fix has **not** been checked against the real service: no live request was made after it.

### Server fix found during this sprint

* **Symptom:** an intermittent `ConnectionAbortedError` in the endpoint tests (`[WinError 10053]`).
* **Cause:** when a handler rejected an upload *before reading its body* (415 wrong type, 503 feature not
  configured), the server closed a socket that still held unread data. Windows then sends a reset, and the client
  saw "connection aborted" instead of the error response. This also affected the existing `/api/awareness/frame`
  and `/api/voicecmd` endpoints.
* **Fix:** `neurosonic/server.py::_drain_unread_body` reads the unread body (up to 4 MB) before any error response
  is sent; a larger body closes the connection.
* **Regression test:** `test_error_responses_arrive_even_with_unread_bodies`. It failed in 2 of 4 runs without the
  fix and passed 20 of 20 runs with it.

## 7. Limitations and open points

* **The cloud path has not produced a real description yet.** The single allowed live request timed out, so
  description quality, latency and the actual response format of `gemini-3.8-flash` are unknown.
* **Time limits are assumptions.** 30 s per attempt and 45 s in total were chosen because one live request
  already failed at 25 s; they are not measurements. If the service needs longer, requests still end with
  "took too long". The values should be set from real measurements, which needs approval for more live
  requests. Waiting up to 45 s for an answer is long for a user; walking guidance continues meanwhile.
* **The cause of the timeout is unknown.** It could be overload (the service has recently returned many 503s and
  timeouts), the image, or the model name. An unknown model normally returns a fast 404, but this was not verified.
* **Not tested on a real iPhone or outdoors.** The photo is captured at ≤ 1024 px, and the photo-to-speech delay
  on the phone is unmeasured.
* **Privacy.** Photos of bystanders go to Google when the user asks. Google's data-use terms depend on the account
  tier and should be checked by the project owner.
* **No authentication on the local network.** Anyone on the same Wi-Fi who opens the page can use the quota. The
  per-session rate limit and the hourly cap of 60 limit this.
* **AI answers can be wrong** (missed or invented objects), even after filtering. They are spoken as descriptions,
  never as safety information, and never take over local "Stop" warnings.
