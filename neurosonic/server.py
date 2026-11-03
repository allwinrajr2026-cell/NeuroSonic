"""NeuroSonic local web server (Python standard library only).

API (JSON unless noted):
  GET  /api/status                       model, replay sets, replay state, last event id
  GET  /api/events?since=ID              alert events newer than ID
  POST /api/replay/start {set, fps, start, loop}
  POST /api/replay/stop
  GET  /api/replay/state
  GET  /api/replay/frame.jpg             latest annotated frame (image/jpeg; 204 if none)
  POST /api/detect {ir_base64, depth_base64}   one IR + colour-depth pair
  POST /api/alerts {source, kind, text}  log a client-side alert (event simulation / navigation)
  GET  /api/history?limit=N | GET /api/stats | POST /api/history/clear
  GET  /api/places | POST /api/places {name, lat, lon} | POST /api/places/delete {id}
  GET  /api/tts/status | GET /api/tts?text=...   (audio/wav, local Piper voice; supports HTTP Range for iOS)
  POST /api/voice/report {engine, ok, error, ...} | GET /api/voice/reports   (client playback results)
  GET  /api/map/info | GET /api/map/data (offline display layers) | GET /api/map/search?q=&lat=&lon=
  POST /api/route {from: {lat, lon}, to: {lat, lon}}   (offline walking route)
  GET  /api/voicecmd/status | POST /api/voicecmd?lat=&lon=  (body: 16 kHz mono WAV; offline Vosk -> intent)
  GET  /api/awareness/status | POST /api/awareness/frame?session=&mode=chest|handheld&describe=0|1  (body: JPEG;
       walking-path state + optional object descriptions)
  GET  /api/vision/status | POST /api/vision/describe?session=&mode=chest|handheld&consent=1&q=<question>
       (body: JPEG/PNG; ONLINE scene description through the configured cloud provider; opt-in; the image is
       processed in memory and never stored; only the spoken text is kept in the history)
Static files are served from web/ (path traversal is rejected).
"""
import base64
import binascii
import collections
import gzip
import json
import time
import mimetypes
import socket
import ssl
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .service import InvalidInput
from .tts import TTSError

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
MAX_BODY = 20 * 1024 * 1024
TLS_HANDSHAKE_TIMEOUT = 10.0   # seconds a client may take to complete the TLS handshake
REQUEST_TIMEOUT = 60.0         # seconds of inactivity before a connection is dropped
STATIC_TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript",
                ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
                ".ico": "image/x-icon", ".webmanifest": "application/manifest+json"}
CLIENT_SOURCES = {"eventsim", "navigation"}
CLIENT_KINDS = {"motion", "navigation", "system"}


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def make_handler(service, store, quiet=True, tts=None, offline_map=None, voicecmd=None, awareness=None, vision=None):
    voice_reports = collections.deque(maxlen=50)
    map_cache = {}

    class Handler(BaseHTTPRequestHandler):
        server_version = "NeuroSonic/1.0"
        timeout = REQUEST_TIMEOUT   # idle/slow clients cannot hold a worker thread forever

        def log_message(self, fmt, *args):
            if not quiet:
                super().log_message(fmt, *args)

        # ---------------------------------------------------------------- helpers
        def _send(self, status, body, ctype, extra=None):
            extra = dict(extra or {})
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", extra.pop("Cache-Control", "no-store"))
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, status=200):
            self._send(status, json.dumps(obj).encode(), "application/json")

        def _raw_body(self, limit, kinds):
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                raise ApiError(400, "empty request body")
            if n > limit:
                raise ApiError(413, "request too large")
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if kinds and ctype not in kinds:
                raise ApiError(415, f"Content-Type must be one of {sorted(kinds)}")
            self._body_consumed = True
            return self.rfile.read(n)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ApiError(413, "request too large")
            raw = self.rfile.read(n) if n else b"{}"
            self._body_consumed = True
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                raise ApiError(400, "invalid JSON")
            if not isinstance(data, dict):
                raise ApiError(400, "JSON object expected")
            return data

        def _drain_unread_body(self, cap=4 * 1024 * 1024):
            """Read a request body that the handler rejected without reading (e.g. 415, 503). Closing a socket with
            unread data makes Windows send a reset, so the client saw "connection aborted" instead of the error
            response (found 2026-11-02). Bodies larger than `cap` are not read; that connection is closed."""
            if self._body_consumed:
                return
            self._body_consumed = True
            n = int(self.headers.get("Content-Length") or 0)
            if 0 < n <= cap:
                try:
                    self.rfile.read(n)
                except OSError:
                    pass
            elif n > cap:
                self.close_connection = True

        def _dispatch(self, routes):
            url = urlparse(self.path)
            fn = routes.get(url.path)
            self._body_consumed = False
            try:
                if fn is None:
                    if self.command in ("GET", "HEAD"):
                        return self._static(url.path)
                    raise ApiError(404, "not found")
                fn(self, url)
            except ApiError as e:
                self._drain_unread_body()
                self._json({"error": e.message}, e.status)
            except TTSError as e:
                self._drain_unread_body()
                self._json({"error": f"voice engine: {e}"}, 503)
            except (InvalidInput, ValueError) as e:
                self._drain_unread_body()
                self._json({"error": str(e)}, 400)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                # the client went away while we were answering (page closed, phone locked, Wi-Fi drop): there is
                # nobody to send an error to, so just close this connection quietly
                self.close_connection = True
            except Exception as e:  # pragma: no cover - last resort
                traceback.print_exc()
                self._drain_unread_body()
                self._json({"error": f"internal error: {type(e).__name__}"}, 500)

        def _static(self, path):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (WEB_ROOT / rel).resolve()
            if WEB_ROOT.resolve() not in target.parents or not target.is_file():
                return self._json({"error": "not found"}, 404)
            # explicit types: Python's mimetypes reads the Windows registry, which can map .js to text/plain
            # (browsers then refuse to run ES modules)
            ctype = STATIC_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))

        # ---------------------------------------------------------------- routes
        def r_status(self, url):
            self._json({"app": "NeuroSonic", "engine": "WOAD exp72 cross-modal detector", "model": service.info(),
                        "replay_sets": service.replay_sets(), "replay": service.replay_state(),
                        "last_event_id": service.events.last_id})

        def r_events(self, url):
            q = parse_qs(url.query)
            try:
                since = int(q.get("since", ["0"])[0])
            except ValueError:
                raise ApiError(400, "since must be an integer")
            self._json({"events": service.events.since(since), "last_event_id": service.events.last_id})

        def r_replay_start(self, url):
            b = self._body()
            self._json(service.start_replay(b.get("set", "detec_test"), b.get("fps", 4.0), b.get("start", 0),
                                            b.get("loop", True)))

        def r_replay_stop(self, url):
            self._body()
            self._json(service.stop_replay())

        def r_replay_state(self, url):
            self._json(service.replay_state())

        def r_replay_frame(self, url):
            jpg = service.replay_jpeg()
            if jpg is None:
                return self._send(204, b"", "image/jpeg")
            self._send(200, jpg, "image/jpeg")

        def r_detect(self, url):
            b = self._body()
            try:
                ir = base64.b64decode(_strip_data_url(b.get("ir_base64", "")), validate=True)
                dp = base64.b64decode(_strip_data_url(b.get("depth_base64", "")), validate=True)
            except (binascii.Error, ValueError):
                raise ApiError(400, "images must be base64 encoded")
            self._json(service.detect_upload(ir, dp))

        def r_alerts(self, url):
            b = self._body()
            source, kind, text = b.get("source"), b.get("kind"), str(b.get("text", "")).strip()
            if source not in CLIENT_SOURCES or kind not in CLIENT_KINDS or not text:
                raise ApiError(400, f"source must be one of {sorted(CLIENT_SOURCES)}, kind one of {sorted(CLIENT_KINDS)}")
            ev = service.events.add(source, kind, text[:300], int(b.get("priority", 5)), {"position": b.get("position")})
            self._json(ev)

        def r_history(self, url):
            q = parse_qs(url.query)
            self._json({"history": store.history(q.get("limit", ["100"])[0])})

        def r_history_clear(self, url):
            self._body()
            store.clear_history()
            self._json({"ok": True})

        def r_stats(self, url):
            self._json(store.stats())

        def r_places(self, url):
            if self.command == "POST":
                b = self._body()
                pid = store.add_place(b.get("name", ""), b.get("lat"), b.get("lon"))
                return self._json({"id": pid, "places": store.places()})
            self._json({"places": store.places()})

        def r_places_delete(self, url):
            b = self._body()
            if not store.delete_place(b.get("id", -1)):
                raise ApiError(404, "place not found")
            self._json({"places": store.places()})

        # ---------------------------------------------------------------- voice (local Piper TTS)
        def r_tts_status(self, url):
            self._json(tts.info() if tts else {"available": False, "error": "voice engine not configured"})

        def r_tts(self, url):
            if tts is None:
                raise ApiError(503, "voice engine not configured")
            text = parse_qs(url.query).get("text", [""])[0]
            self._send_media(tts.synthesize(text), "audio/wav")

        def _send_media(self, data, ctype):
            """Media response with HTTP Range support (iOS Safari/WebKit requests audio in byte ranges)."""
            total, rng = len(data), self.headers.get("Range")
            common = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=86400"}
            if rng and rng.startswith("bytes="):
                try:
                    a, b = rng[6:].split(",")[0].strip().split("-")
                    if a:
                        start, end = int(a), (min(int(b), total - 1) if b else total - 1)
                    else:
                        start, end = max(0, total - int(b)), total - 1
                except ValueError:
                    start, end = 0, -1
                if not 0 <= start <= end < total:
                    return self._send(416, b"", ctype, {**common, "Content-Range": f"bytes */{total}"})
                return self._send(206, data[start:end + 1], ctype,
                                  {**common, "Content-Range": f"bytes {start}-{end}/{total}"})
            self._send(200, data, ctype, common)

        def r_voice_report(self, url):
            b = self._body()
            report = {k: str(b.get(k, ""))[:300] for k in ("engine", "ok", "error", "text", "duration", "user_agent", "via")}
            report["time"] = time.time()
            report["client"] = self.client_address[0]
            voice_reports.append(report)
            ua = report["user_agent"]
            device = ("iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else "Android" if "Android" in ua
                      else "Windows" if "Windows" in ua else "Mac" if "Macintosh" in ua else "device")
            browser = "Chrome" if ("CriOS" in ua or "Chrome" in ua) else "Safari" if "Safari" in ua else "browser"
            status = "PLAYED" if report["ok"] == "True" else f"FAILED ({report['error']})"
            print(f"[voice] {report['client']} {device}/{browser}: {report['engine']} voice {status}: "
                  f"\"{report['text'][:70]}\"", flush=True)
            self._json({"ok": True})

        def r_voice_reports(self, url):
            self._json({"reports": list(voice_reports)})

        # ---------------------------------------------------------------- offline map
        def _map(self):
            if offline_map is None:
                raise ApiError(503, "no offline map installed")
            return offline_map

        def r_map_info(self, url):
            self._json(offline_map.info() if offline_map else {"available": False})

        def r_map_data(self, url):
            m = self._map()
            if "raw" not in map_cache:
                map_cache["raw"] = (m.folder / "map.json").read_bytes()
                map_cache["gz"] = gzip.compress(map_cache["raw"], 6)
            if "gzip" in (self.headers.get("Accept-Encoding") or ""):
                return self._send(200, map_cache["gz"], "application/json",
                                  {"Content-Encoding": "gzip", "Cache-Control": "private, max-age=3600"})
            self._send(200, map_cache["raw"], "application/json", {"Cache-Control": "private, max-age=3600"})

        def r_map_search(self, url):
            q = parse_qs(url.query)
            near = None
            if q.get("lat") and q.get("lon"):
                near = (float(q["lat"][0]), float(q["lon"][0]))
            self._json({"results": self._map().search(q.get("q", [""])[0], limit=10, near=near)})

        def r_route(self, url):
            b = self._body()
            try:
                f, t = b["from"], b["to"]
                start, end = (float(f["lat"]), float(f["lon"])), (float(t["lat"]), float(t["lon"]))
            except (KeyError, TypeError, ValueError):
                raise ApiError(400, "from/to must be {lat, lon}")
            self._json(self._map().route(start, end))

        # ---------------------------------------------------------------- voice commands (offline Vosk)
        def r_voicecmd_status(self, url):
            self._json(voicecmd.info() if voicecmd else {"available": False, "error": "voice commands not configured"})

        def r_voicecmd(self, url):
            if voicecmd is None:
                raise ApiError(503, "voice commands not configured")
            from .voicecmd import VoiceCommandError
            wav = self._raw_body(2 * 1024 * 1024, {"audio/wav", "audio/x-wav", "application/octet-stream"})
            q = parse_qs(url.query)
            near = None
            if q.get("lat") and q.get("lon"):
                near = (float(q["lat"][0]), float(q["lon"][0]))
            try:
                res = voicecmd.handle(wav, near=near, saved=store.places() if store else None)
            except VoiceCommandError as e:
                raise ApiError(400, str(e))
            print(f"[voicecmd] {self.client_address[0]}: heard \"{res['heard']}\" -> {res['intent']}"
                  + (f" ({res['query']})" if res.get("query") else ""), flush=True)
            self._json(res)

        # ---------------------------------------------------------------- live camera awareness (RGB detector)
        # ---------------------------------------------------------------- online scene description (cloud, opt-in)
        def r_vision_status(self, url):
            self._json(vision.info() if vision else {"available": False, "enabled": False, "configured": False,
                                                       "problem": "online scene description not configured",
                                                       "requires_internet": True, "requires_consent": True,
                                                       "stores_images": False})

        def r_vision_describe(self, url):
            if vision is None:
                raise ApiError(503, "online scene description not configured")
            img = self._raw_body(3 * 1024 * 1024, {"image/jpeg", "image/png", "application/octet-stream"})
            q = parse_qs(url.query)
            session = (q.get("session", ["default"])[0] or "default")[:64]
            mode = q.get("mode", ["chest"])[0]
            consent = q.get("consent", ["0"])[0] in ("1", "true", "yes")
            res = vision.describe(img, question=q.get("q", [""])[0], mode=mode,
                                  session=f"{self.client_address[0]}:{session}", consent=consent)
            del img                                    # the image is never stored anywhere
            if res.get("code") not in ("consent", "rate_limited"):
                service.events.add("vision", "scene", res["text"], 5,
                                   {"ok": res["ok"], "code": res.get("code"), "provider": res.get("provider"),
                                    "model": res.get("model"), "latency_ms": res.get("latency_ms"),
                                    "question": res.get("question") or None}, "camera")
            self._json(res)

        def r_awareness_status(self, url):
            self._json(awareness.info() if awareness else {"available": False, "error": "camera awareness not configured"})

        def r_awareness_frame(self, url):
            if awareness is None:
                raise ApiError(503, "camera awareness not configured")
            jpg = self._raw_body(3 * 1024 * 1024, {"image/jpeg", "application/octet-stream"})
            q = parse_qs(url.query)
            session = (q.get("session", ["default"])[0] or "default")[:64]
            mode = q.get("mode", ["chest"])[0]
            describe = q.get("describe", ["0"])[0] in ("1", "true", "yes")
            res = awareness.process_frame(jpg, session=f"{self.client_address[0]}:{session}", mode=mode,
                                          describe=describe)
            for e in res["events"]:
                if e["kind"] in ("object", "path", "event"):
                    service.events.add("awareness", e["kind"], e["text"], e["priority"], e["data"], "camera")
            self._json(res)

        GET = {"/api/status": r_status, "/api/events": r_events, "/api/replay/state": r_replay_state,
               "/api/replay/frame.jpg": r_replay_frame, "/api/history": r_history, "/api/stats": r_stats,
               "/api/places": r_places, "/api/tts/status": r_tts_status, "/api/tts": r_tts,
               "/api/voice/reports": r_voice_reports, "/api/map/info": r_map_info, "/api/map/data": r_map_data,
               "/api/map/search": r_map_search, "/api/voicecmd/status": r_voicecmd_status,
               "/api/awareness/status": r_awareness_status, "/api/vision/status": r_vision_status}
        POST = {"/api/replay/start": r_replay_start, "/api/replay/stop": r_replay_stop, "/api/detect": r_detect,
                "/api/alerts": r_alerts, "/api/history/clear": r_history_clear, "/api/places": r_places,
                "/api/places/delete": r_places_delete, "/api/voice/report": r_voice_report, "/api/route": r_route,
                "/api/voicecmd": r_voicecmd, "/api/awareness/frame": r_awareness_frame,
                "/api/vision/describe": r_vision_describe}

        def do_GET(self):
            self._dispatch(self.GET)

        def do_HEAD(self):
            self._dispatch(self.GET)

        def do_POST(self):
            self._dispatch(self.POST)

    return Handler


def _strip_data_url(s):
    s = str(s)
    return s.split(",", 1)[1] if s.startswith("data:") and "," in s else s


class NeuroSonicHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP(S) server that performs the TLS handshake per connection, in the worker thread.

    Previously the *listening* socket was TLS-wrapped, so every handshake ran inside accept() on the single
    main thread: one client that connected without finishing the handshake (a browser pre-connect, a phone
    showing a certificate warning) blocked the whole server and every other client hung. Here accept()
    returns plain sockets immediately; each worker thread completes (or times out) its own handshake.
    """
    daemon_threads = True
    # Windows: SO_REUSEADDR lets a second process bind the same port *silently*; requests can then be answered
    # by an old, still-running NeuroSonic (found 2026-11-02: new endpoints returned 404 from a stale instance).
    # Bind exclusively instead, so a second instance fails loudly with "address in use".
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address, handler, ssl_context=None, handshake_timeout=TLS_HANDSHAKE_TIMEOUT):
        self.ssl_context, self.handshake_timeout = ssl_context, handshake_timeout
        super().__init__(address, handler)

    def finish_request(self, request, client_address):
        if self.ssl_context is None:
            return super().finish_request(request, client_address)
        request.settimeout(self.handshake_timeout)
        try:
            tls = self.ssl_context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return  # failed, rejected or timed-out handshake: drop only this connection
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            try:
                tls.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            tls.close()


def make_server(service, store, host="127.0.0.1", port=8765, quiet=True, ssl_context=None, tts=None,
                offline_map=None, voicecmd=None, awareness=None, vision=None):
    return NeuroSonicHTTPServer((host, port), make_handler(service, store, quiet, tts=tts, offline_map=offline_map,
                                                           voicecmd=voicecmd, awareness=awareness, vision=vision),
                                ssl_context=ssl_context)


def make_setup_server(ca_cert_path, app_url, fingerprint, host="0.0.0.0", port=8766, quiet=True):
    """Plain-HTTP helper (HTTPS mode only) that serves ONLY a setup page and the local CA certificate, so a
    phone can install the CA before the HTTPS app is trusted. It exposes no app data or API."""
    ca_bytes = Path(ca_cert_path).read_bytes()
    page = SETUP_PAGE.format(app_url=app_url, fingerprint=fingerprint).encode()

    class SetupHandler(BaseHTTPRequestHandler):
        server_version = "NeuroSonicSetup/1.0"
        timeout = REQUEST_TIMEOUT

        def log_message(self, fmt, *args):
            if not quiet:
                super().log_message(fmt, *args)

        def _send(self, status, body, ctype, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/setup"):
                self._send(200, page, "text/html; charset=utf-8")
            elif path == "/neurosonic-ca.crt":
                self._send(200, ca_bytes, "application/x-x509-ca-cert",
                           {"Content-Disposition": 'attachment; filename="neurosonic-ca.crt"'})
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        do_HEAD = do_GET

    return NeuroSonicHTTPServer((host, port), SetupHandler)


SETUP_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>NeuroSonic phone setup</title>
<style>body{{font-family:system-ui,sans-serif;background:#0b1020;color:#f2f5ff;margin:0;padding:1rem;line-height:1.5;font-size:18px}}
a{{color:#ffd23f}} .btn{{display:block;text-align:center;background:#ffd23f;color:#111;padding:.9rem;border-radius:12px;
font-weight:700;text-decoration:none;margin:1rem 0}} code{{background:#1d2645;padding:0 .3em;border-radius:4px;word-break:break-all}}
li{{margin:.4rem 0}}</style></head><body>
<h1>NeuroSonic phone setup</h1>
<p>One-time step so the phone trusts this laptop's local HTTPS certificate (needed for camera and GPS).</p>
<h2>iPhone</h2>
<ol>
<li>Open <strong>this page in Safari</strong> (iOS only installs certificate profiles from Safari).</li>
<li><a class="btn" href="/neurosonic-ca.crt">Download the NeuroSonic certificate</a> Tap <em>Allow</em>.</li>
<li>Settings &rarr; General &rarr; VPN &amp; Device Management &rarr; <em>NeuroSonic Local CA</em> &rarr; Install.</li>
<li>Settings &rarr; General &rarr; About &rarr; Certificate Trust Settings &rarr; turn on <em>NeuroSonic Local CA</em>.</li>
<li>Check the certificate's SHA-256 fingerprint in the profile details matches the one printed by the laptop:<br>
<code>{fingerprint}</code></li>
<li>Open the app in Safari or Chrome: <a href="{app_url}">{app_url}</a></li>
</ol>
<h2>Android (Chrome)</h2>
<ol><li>Download the certificate above, then Settings &rarr; Security &rarr; Encryption &amp; credentials &rarr;
Install a certificate &rarr; CA certificate.</li><li>Open <a href="{app_url}">{app_url}</a>.</li></ol>
<p>Only install this certificate on your own devices, and remove it when you no longer use NeuroSonic
(Settings &rarr; General &rarr; VPN &amp; Device Management).</p>
</body></html>"""


def serve_in_thread(httpd):
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return t
