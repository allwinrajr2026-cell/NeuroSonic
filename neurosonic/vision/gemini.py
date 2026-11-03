"""Google Gemini provider (google-genai SDK, imported lazily so the app works without it).

* The API key is read on the backend only, from the environment variable GEMINI_API_KEY (or passed explicitly).
  It is never returned by any endpoint, never logged and never written to a file; error messages are scrubbed.
* The SDK's own automatic retries are switched off (HttpRetryOptions(attempts=1)): SceneAssistant decides whether
  to retry, so one analyze() call is exactly one HTTP request.
* Each call has an SDK timeout plus a hard outer guard thread, so a hanging connection cannot block the request.
  The SDK also sends that timeout to Google as the server deadline (header X-Server-Timeout = ceil(seconds)); the
  server rejects deadlines below 10 s (400 INVALID_ARGUMENT) and answers 504 DEADLINE_EXCEEDED when it runs out.
  Therefore no call is ever made with less than MIN_DEADLINE_S (fixed 2026-11-02 after a 4 s retry deadline).
* The model is configurable (default gemini-3.8-flash, chosen by the project owner on 2026-11-02; its availability
  was not assumed - see docs/ONLINE_VISION.md for the recorded live test).
"""
import os
import threading
import time

from .base import (BadResponse, NotConfigured, ProviderRateLimited, ProviderReply, ProviderTimeout,
                   ProviderUnavailable, Rejected, SCENE_SCHEMA, VisionError, VisionProvider, parse_scene, scrub)

DEFAULT_MODEL = "gemini-3.8-flash"
MIN_DEADLINE_S = 10.0     # Gemini API: "Minimum allowed deadline is 10s"
KEY_ENV = "GEMINI_API_KEY"


def read_key():
    """GEMINI_API_KEY from the process environment; on Windows, fall back to the user's registry environment
    (HKCU\\Environment), because a terminal opened before `setx GEMINI_API_KEY ...` does not see the variable.
    The value is only returned to the provider; it is never printed or stored."""
    key = os.environ.get(KEY_ENV, "")
    if key or os.name != "nt":
        return key
    try:
        import winreg  # noqa: PLC0415
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, KEY_ENV)[0] or "")
    except OSError:
        return ""


def _sdk():
    from google import genai               # noqa: PLC0415 - optional dependency
    from google.genai import errors, types  # noqa: PLC0415
    return genai, types, errors


class GeminiProvider(VisionProvider):
    name = "gemini"
    min_timeout_s = MIN_DEADLINE_S

    def __init__(self, model=None, api_key=None, client_factory=None):
        self.model = model or os.environ.get("NEUROSONIC_VISION_MODEL") or DEFAULT_MODEL
        self._key = api_key if api_key is not None else read_key()
        self._client_factory = client_factory     # tests inject a fake client; never used in production
        self._client = None
        self._lock = threading.Lock()
        try:
            _sdk()
            self._sdk_error = None
        except Exception as e:  # noqa: BLE001
            self._sdk_error = f"google-genai not installed ({type(e).__name__})"

    # ---------------------------------------------------------------- status (never the key)
    def configured(self):
        return bool(self._key) and (self._sdk_error is None or self._client_factory is not None)

    def problem(self):
        if not self._key:
            return f"API key missing: set the {KEY_ENV} environment variable for the laptop server"
        if self._sdk_error and self._client_factory is None:
            return self._sdk_error
        return ""

    def _get_client(self):
        with self._lock:
            if self._client is None:
                if self._client_factory is not None:
                    self._client = self._client_factory(self._key)
                else:
                    genai, types, _ = _sdk()
                    self._client = genai.Client(api_key=self._key, http_options=types.HttpOptions(
                        retry_options=types.HttpRetryOptions(attempts=1)))
            return self._client

    # ---------------------------------------------------------------- one call = one request
    def analyze(self, request, prompt, system, timeout_s):
        if not self.configured():
            raise NotConfigured(self.problem())
        timeout_s = max(float(timeout_s), self.min_timeout_s)   # never send a deadline the server rejects (10 s)
        client = self._get_client()
        try:
            genai, types, errors = _sdk()
        except Exception:  # noqa: BLE001 - only possible with an injected fake client
            types = errors = None
        contents, config = self._build(types, request, prompt, system, timeout_s)
        result, done = {}, threading.Event()

        def call():
            try:
                result["resp"] = client.models.generate_content(model=self.model, contents=contents, config=config)
            except BaseException as e:  # noqa: BLE001 - re-raised in the caller thread
                result["err"] = e
            finally:
                done.set()

        t0 = time.monotonic()
        threading.Thread(target=call, name="gemini-call", daemon=True).start()
        if not done.wait(timeout_s + 2.0):          # hard guard on top of the SDK timeout
            raise ProviderTimeout(f"no reply from {self.model} within {timeout_s:.0f} s")
        latency = int((time.monotonic() - t0) * 1000)
        if "err" in result:
            raise self._map_error(result["err"], errors, timeout_s)
        resp = result["resp"]
        text = getattr(resp, "text", None)
        if not text:
            reason = ""
            try:
                c = (resp.candidates or [None])[0]
                reason = f" (finish reason {getattr(c, 'finish_reason', None)})" if c is not None else ""
                pf = getattr(resp, "prompt_feedback", None)
                if pf is not None and getattr(pf, "block_reason", None):
                    reason = f" (blocked: {pf.block_reason})"
            except Exception:  # noqa: BLE001
                pass
            raise BadResponse(f"empty reply from {self.model}{reason}")
        return ProviderReply(scene=parse_scene(text), model=getattr(resp, "model_version", None) or self.model,
                             latency_ms=latency, raw_chars=len(text))

    def _build(self, types, request, prompt, system, timeout_s):
        if types is None:     # fake client in tests: plain structures
            return ([prompt, {"mime_type": request.mime, "bytes": len(request.image)}],
                    {"system_instruction": system, "timeout_ms": int(timeout_s * 1000)})
        contents = [prompt, types.Part.from_bytes(data=request.image, mime_type=request.mime)]
        config = types.GenerateContentConfig(
            system_instruction=system, response_mime_type="application/json", response_json_schema=SCENE_SCHEMA,
            temperature=0.2, max_output_tokens=1024,
            http_options=types.HttpOptions(timeout=int(timeout_s * 1000), retry_options=types.HttpRetryOptions(attempts=1)))
        return contents, config

    def _map_error(self, e, errors, timeout_s):
        msg = scrub(f"{type(e).__name__}: {e}", self._key)
        code = getattr(e, "code", None)
        if errors is not None and isinstance(e, errors.APIError) or isinstance(code, int):
            if code in (408, 504):
                return ProviderTimeout(msg)
            if code == 429:
                return ProviderRateLimited(msg)
            if isinstance(code, int) and code >= 500:
                return ProviderUnavailable(msg)
            return Rejected(msg)
        name = type(e).__name__.lower()
        if "timeout" in name or isinstance(e, TimeoutError):
            return ProviderTimeout(f"no reply from {self.model} within {timeout_s:.0f} s ({type(e).__name__})")
        if any(k in name for k in ("connect", "network", "transport", "dns", "gaierror", "ssl")) or isinstance(e, OSError):
            return ProviderUnavailable(f"network error, is the laptop online? ({msg})")
        return VisionError(msg)


def make_provider(name=None, model=None):
    """'gemini' (default) | 'mock' | 'off' -> provider or None. Reads NEUROSONIC_VISION_PROVIDER if name is None."""
    name = (name or os.environ.get("NEUROSONIC_VISION_PROVIDER") or "gemini").lower()
    if name == "off":
        return None
    if name == "mock":
        from .mock import MockProvider  # noqa: PLC0415
        # test/demo only: e.g. NEUROSONIC_VISION_MOCK_SCRIPT="ok,503,503" to simulate an outage in a browser test
        script = [x.strip() for x in os.environ.get("NEUROSONIC_VISION_MOCK_SCRIPT", "ok").split(",") if x.strip()]
        return MockProvider(script=script or ["ok"])
    if name == "gemini":
        return GeminiProvider(model=model)
    raise ValueError(f"unknown vision provider {name!r} (gemini, mock, off)")
