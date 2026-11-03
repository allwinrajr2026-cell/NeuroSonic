# 18. Online scene description (Sprint 1, 2026-11-02)

Full technical description: `../docs/ONLINE_VISION.md`. Backup taken before the sprint:
`backups/20261102-214436-before-sprint1-online-vision/`. The original WOAD code and checkpoint were not changed.

## 18.1 What was built

* **`neurosonic/vision/`**, a new package that is provider-independent:
  * `base.py`: the `VisionProvider` interface, typed errors (`NotConfigured`, `ProviderUnavailable`,
    `ProviderTimeout`, `ProviderRateLimited`, `Rejected`, `BadResponse`), `SCENE_SCHEMA`, `parse_scene` and
    `scrub`;
  * `assistant.py`: `SceneAssistant` covers consent, rate limits, full 30 s attempts within a 45 s budget, one
    retry only for a quick 503 / network error (never after a timeout), the
    circuit breaker, image preparation in memory, the prompt and its rules, the safety filter, and the spoken text
    (at most 400 characters);
  * `gemini.py`: `GeminiProvider` (google-genai with SDK retries off, a timeout plus a hard guard thread, error
    mapping) and `make_provider`;
  * `mock.py`: `MockProvider` with scripted outcomes for tests and demonstrations.
* **Endpoints:** `GET /api/vision/status` and `POST /api/vision/describe` (`neurosonic/server.py`). Results go into
  the history as text only (source `vision`, kind `scene`, `neurosonic/store.py`).
* **Phone (`web/`):**
  * Home has an "Online scene description" card: Describe button, question box, status and the first-use consent
    panel;
  * Settings has a consent checkbox and the provider status;
  * the offline-status list gained a row for scene description;
  * How It Works gained topic 11;
  * a speech category `scene` was added: below "Stop", interruptible, kept 30 s in the queue.
* **Voice commands:** `describe_scene` and `ask_scene` (`neurosonic/voicecmd.py`), checked after all existing
  commands.
* **Start-up:** `neurosonic_app.py` takes `--vision-provider gemini|mock|off` and `--vision-model`, and prints one
  status line. It never prints the key.

## 18.2 Results

| Check | Result |
|---|---|
| Full suite | `Ran 182 tests … OK` (one opt-in live test skipped), after the deadline fix |
| `ui_vision_cdp.mjs` (mock provider, iPhone size, fake camera) | PASS: opt-in before any upload, spoken description, question passed through, simulated outage spoken, walking guidance unaffected, consent withdrawal, text-only history |
| Single live Gemini request (`gemini-3.8-flash`, `test_street.jpg`) | **Timeout**: no reply within 25 s (ReadTimeout after 25.9 s), 1 attempt, no retry; fallback spoken. No successful live description yet |

## 18.2b Deadline fix (after the iPhone test)

The iPhone test showed `504 DEADLINE_EXCEEDED` and `400 … deadline 4s is too short. Minimum allowed deadline is
10s`.

**Cause.** The SDK turns the per-attempt timeout into the server deadline (`X-Server-Timeout`), and `SceneAssistant`
gave the retry only the leftover budget, about 4 s.

**Fix:**

* The deadline is never below 10 s, and every attempt gets the full 30 s.
* There is no retry after a timeout; a quick 503 gets one full retry if it fits in the 45 s budget.
* The values are configurable through `NEUROSONIC_VISION_TIMEOUT_S` and `NEUROSONIC_VISION_BUDGET_S`.
* The phone waits 60 s and says "Still waiting…" after 15 s.

**Tests:**

* `TestTimeoutPolicy` (9 tests, mocked) failed against the old code and passes now.
* `ui_vision_slow_cdp.mjs` shows that walking guidance kept analysing about 2.5 frames per second during a 20 s cloud
  wait.
* Not yet checked against the real service.

## 18.3 Likely questions

* *Why on the laptop and not directly from the phone to Gemini?* Two reasons. The API key must never be in the web
  page. And one backend layer lets the provider be replaced, rate-limited and filtered for safety in one place.
* *Does walking guidance stop when Gemini is down?* No. It is a separate local pipeline. The browser test keeps it
  running through a simulated outage, and a test checks that no local module imports the cloud package.
* *How do you stop the model from saying "it is safe"?* In three ways:
  * the system prompt forbids it;
  * a filter on the reply removes such sentences, and distances, then adds "Please check the path yourself.";
  * every answer starts with "AI description:".
* *What happened in the live test?* The only approved request timed out after 25.9 s. The failure path worked as
  designed. Measuring latency and quality needs more approved live requests.
