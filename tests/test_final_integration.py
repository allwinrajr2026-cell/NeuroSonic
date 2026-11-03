"""Final integration: offline voice commands (Vosk), live RGB camera awareness, their APIs, and offline operation."""
import http.client
import io
import json
import shutil
import tempfile
import unittest
import wave
from pathlib import Path

import cv2
import numpy as np

from tests._common import ROOT
from tests._offline import no_internet
from neurosonic.server import make_server, serve_in_thread
from neurosonic.voicecmd import DEFAULT_MODEL, VoiceCommands, parse_intent, phonetic, place_score
from neurosonic.awareness import DEFAULT_WEIGHTS, RGBAwareness
from neurosonic.tts import DEFAULT_VOICE

HAVE_ASR = (DEFAULT_MODEL / "am").is_dir() and DEFAULT_VOICE.exists()
HAVE_RGB = DEFAULT_WEIGHTS.exists()
MAP_DIR = ROOT / "maps" / "vellore"
DETEC = ROOT / "demo_data" / "detec_test" / "ir"
_PIPER = None


def speech16k(text):
    """Deterministic Piper speech (noise off) resampled to 16 kHz mono WAV - a stand-in for a user's voice."""
    global _PIPER
    from piper import PiperVoice, SynthesisConfig
    if _PIPER is None:
        _PIPER = PiperVoice.load(str(DEFAULT_VOICE))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        _PIPER.synthesize_wav(text, w, syn_config=SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0))
    w = wave.open(io.BytesIO(buf.getvalue()))
    a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
    sr = w.getframerate()
    x = np.interp(np.arange(0, len(a), sr / 16000), np.arange(len(a)), a)
    x = np.concatenate([np.zeros(3000), x, np.zeros(6000)]).astype(np.int16)
    out = io.BytesIO()
    with wave.open(out, "wb") as o:
        o.setnchannels(1), o.setsampwidth(2), o.setframerate(16000), o.writeframes(x.tobytes())
    return out.getvalue()


class _NoService:
    class events:   # noqa: N801 - minimal stand-in for EventLog
        added = []

        @classmethod
        def add(cls, *a, **k):
            cls.added.append(a)


class TestIntentParser(unittest.TestCase):
    def test_intents(self):
        cases = {
            ("start navigation", ""): ("start_navigation", None), ("", "stop guidance please"): ("stop_navigation", None),
            ("repeat instruction", ""): ("repeat", None), ("", "say that again"): ("repeat", None),
            ("status", ""): ("status", None), ("", "why am i"): ("status", None),
            ("start awareness", ""): ("awareness_on", None), ("stop camera", ""): ("awareness_off", None),
            ("help", ""): ("help", None), ("test voice", ""): ("test_voice", None),
            ("navigate", "navigate"): ("navigate", None), ("navigate", "they took cut body"): ("navigate", "they took cut body"),
            ("navigate to", "navigate to cmc hospital"): ("navigate", "cmc hospital"),
            ("", "take me to gandhi nagar"): ("navigate", "gandhi nagar"),
            ("search for", "search for the bus stand"): ("search", "the bus stand"),
            ("", "find hospital"): ("search", "hospital"), ("", "banana"): ("unknown", None), ("", ""): ("unknown", None),
        }
        for (g, f), want in cases.items():
            with self.subTest(g=g, f=f):
                self.assertEqual(parse_intent(g, f), want)

    def test_sound_alike_matching(self):
        self.assertEqual(phonetic("katpadi"), phonetic("cut body"))
        self.assertGreater(place_score("cut paddy", "Katpadi"), place_score("cut paddy", "Court Ground"))
        self.assertGreater(place_score("see in see hospital", "CMC Hospital"), 0.7)


@unittest.skipUnless(HAVE_ASR, "Vosk model or Piper voice missing")
class TestVoiceCommands(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from neurosonic.maps import OfflineMap
        cls.vc = VoiceCommands(offline_map=OfflineMap(MAP_DIR))

    def test_fixed_commands_from_speech(self):
        cmds = {"start navigation": "start_navigation", "stop navigation": "stop_navigation",
                "repeat instruction": "repeat", "start awareness": "awareness_on", "stop awareness": "awareness_off",
                "help": "help", "test voice": "test_voice", "where am i": "status"}
        got = {text: self.vc.handle(speech16k(text))["intent"] for text in cmds}
        correct = sum(got[t] == want for t, want in cmds.items())
        # measured 2026-11-02: 8/8 with deterministic Piper speech; allow one miss for model updates
        self.assertGreaterEqual(correct, 7, got)

    def test_spoken_destination_and_saved_place(self):
        r = self.vc.handle(speech16k("navigate to Katpadi Junction"))
        self.assertEqual(r["intent"], "navigate")
        self.assertTrue(r["places"], r)
        r = self.vc.handle(speech16k("navigate to home"), saved=[{"id": 1, "name": "Home", "lat": 12.93, "lon": 79.14}])
        self.assertEqual(r["places"][0]["name"], "Home")
        self.assertEqual(r["places"][0]["match"], "saved place")

    def test_rejects_bad_audio(self):
        from neurosonic.voicecmd import VoiceCommandError
        with self.assertRaises(VoiceCommandError):
            self.vc.handle(b"not a wav")
        b = io.BytesIO()
        with wave.open(b, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(44100), w.writeframes(b"\0\0" * 44100)
        with self.assertRaises(VoiceCommandError):
            self.vc.handle(b.getvalue())   # wrong sample rate

    def test_offline(self):
        wav = speech16k("stop navigation")
        with no_internet() as attempts:
            r = VoiceCommands().handle(wav)     # fresh model load from disk
        self.assertEqual(attempts, [])
        self.assertEqual(r["intent"], "stop_navigation")


@unittest.skipUnless(HAVE_RGB and DETEC.is_dir(), "detector weights or demo frames missing")
class TestCameraAwareness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = RGBAwareness()

    def jpg(self, name):
        return cv2.imencode(".jpg", cv2.imread(str(DETEC / name)))[1].tobytes()

    def test_detects_people_and_confirms_over_frames(self):
        j = self.jpg("0000030226.png")                  # a person close to the camera
        # object names are spoken only with Object Description on (describe=True)
        r1 = self.a.process_frame(j, session="t1", mode="chest", t=0.0, describe=True)
        self.assertIn("Person", [d["class_name"] for d in r1["detections"]])
        self.assertEqual([e for e in r1["events"] if e["kind"] == "object"], [])   # needs 2 of 3 frames
        r2 = self.a.process_frame(j, session="t1", mode="chest", t=0.4, describe=True)
        texts = [e["text"] for e in r2["events"]]
        self.assertTrue(any(t.startswith("Person") and "camera view" not in t for t in texts), texts)

    def test_handheld_wording_never_says_ahead(self):
        j = self.jpg("0000060683.png")
        self.a.process_frame(j, session="t2", mode="handheld", t=0.0, describe=True)
        events = self.a.process_frame(j, session="t2", mode="handheld", t=0.4, describe=True)["events"]
        texts = [e["text"] for e in events]
        self.assertTrue(texts)
        self.assertTrue(all("ahead" not in t for t in texts), texts)
        self.assertTrue(all("in camera view" in e["text"] for e in events if e["kind"] == "object"), texts)
        self.assertTrue(all("camera" in e["text"] for e in events if e["kind"] == "path"), texts)

    def test_dark_frame_is_unusable_and_reported(self):
        dark = cv2.imencode(".jpg", np.full((240, 320, 3), 5, np.uint8))[1].tobytes()
        events = []
        for i in range(4):
            r = self.a.process_frame(dark, session="t3", t=float(i))
            events += r["events"]
            self.assertEqual(r["detections"], [])
        self.assertEqual(r["quality"]["status"], "unusable")
        self.assertTrue(any("cannot clearly assess" in e["text"] for e in events), events)
        self.assertEqual(r["path"]["state"], "UNCERTAIN")

    def test_urgent_flag_for_large_central_object(self):
        # synthetic: duplicate the close-up person into the centre of the frame
        im = cv2.imread(str(DETEC / "0000030226.png"))
        h, w = im.shape[:2]
        crop = im[:, int(w * 0.55):]                     # the person stands on the right
        centre = np.full_like(im, 128)
        x0 = (w - crop.shape[1]) // 2
        centre[:, x0:x0 + crop.shape[1]] = crop
        j = cv2.imencode(".jpg", centre)[1].tobytes()
        # urgency now comes from the BLOCKED_VIEW path state; object descriptions are never urgent
        self.a.process_frame(j, session="t4", t=0.0, describe=True)
        r = self.a.process_frame(j, session="t4", t=0.4, describe=True)
        path = [e for e in r["events"] if e["kind"] == "path"]
        self.assertTrue(path, r)
        self.assertTrue(path[0]["urgent"], path)
        self.assertEqual(path[0]["text"], "Stop. The walking path may be blocked.")
        self.assertTrue(all(not e["urgent"] for e in r["events"] if e["kind"] == "object"), r["events"])

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            self.a.process_frame(b"garbage", session="t5")
        with self.assertRaises(ValueError):
            self.a.process_frame(self.jpg("0000030226.png"), session="t5", mode="pocket")

    def test_offline(self):
        j = self.jpg("0000060683.png")
        with no_internet() as attempts:
            r = RGBAwareness().process_frame(j, session="t6")
        self.assertEqual(attempts, [])
        self.assertTrue(r["detections"])


@unittest.skipUnless(HAVE_ASR and HAVE_RGB, "models missing")
class TestNewApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from neurosonic.maps import OfflineMap
        from neurosonic.store import Store
        cls.td = Path(tempfile.mkdtemp(prefix="ns_final_"))
        cls.store = Store(cls.td / "t.sqlite3")
        cls.store.add_place("Home", 12.93, 79.14)
        om = OfflineMap(MAP_DIR)
        cls.httpd = make_server(_NoService(), cls.store, "127.0.0.1", 0, offline_map=om,
                                voicecmd=VoiceCommands(offline_map=om), awareness=RGBAwareness())
        serve_in_thread(cls.httpd)
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.close()
        shutil.rmtree(cls.td, ignore_errors=True)

    def req(self, method, path, body=None, ctype=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        c.request(method, path, body=body, headers={"Content-Type": ctype} if ctype else {})
        r = c.getresponse()
        out = r.status, json.loads(r.read() or b"null")
        c.close()
        return out

    def test_status_endpoints(self):
        st, v = self.req("GET", "/api/voicecmd/status")
        self.assertTrue(v["available"])
        self.assertTrue(v["offline"])
        st, a = self.req("GET", "/api/awareness/status")
        self.assertTrue(a["available"])
        self.assertEqual(a["distance"], "not available (single RGB camera)")

    def test_voice_command_endpoint(self):
        st, r = self.req("POST", "/api/voicecmd?lat=12.93&lon=79.14", speech16k("navigate to home"), "audio/wav")
        self.assertEqual(st, 200, r)
        self.assertEqual(r["intent"], "navigate")
        self.assertEqual(r["places"][0]["name"], "Home")
        self.assertEqual(self.req("POST", "/api/voicecmd", b"xx", "audio/wav")[0], 400)
        self.assertEqual(self.req("POST", "/api/voicecmd", speech16k("help"), "text/plain")[0], 415)

    def test_awareness_endpoint(self):
        j = cv2.imencode(".jpg", cv2.imread(str(DETEC / "0000060683.png")))[1].tobytes()
        st, r = self.req("POST", "/api/awareness/frame?session=a&mode=chest", j, "image/jpeg")
        self.assertEqual(st, 200, r)
        self.assertTrue(r["detections"])
        st, r = self.req("POST", "/api/awareness/frame?session=a&mode=chest", j, "image/jpeg")
        self.assertTrue(any(e["kind"] == "path" for e in r["events"]), r)
        self.assertFalse(any(e["kind"] == "object" for e in r["events"]), r)      # Object Description off
        for _ in range(2):
            st, r = self.req("POST", "/api/awareness/frame?session=b&mode=chest&describe=1", j, "image/jpeg")
        self.assertTrue(any(e["kind"] == "object" for e in r["events"]), r)
        self.assertEqual(self.req("POST", "/api/awareness/frame?mode=pocket", j, "image/jpeg")[0], 400)
        self.assertEqual(self.req("POST", "/api/awareness/frame", b"", "image/jpeg")[0], 400)


if __name__ == "__main__":
    unittest.main()
