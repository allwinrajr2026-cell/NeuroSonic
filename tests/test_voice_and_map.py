"""Local neural voice (Piper) and offline Vellore map/routing: engine, HTTP API, and no-internet operation."""
import gzip
import heapq
import http.client
import io
import json
import math
import random
import shutil
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from tests._common import ROOT
from tests._offline import NetworkBlocked, no_internet
from neurosonic.server import make_server, serve_in_thread
from neurosonic.tts import DEFAULT_VOICE, PiperTTS, TTSError, wav_duration

MAP_DIR = ROOT / "maps" / "vellore"
TEST_SENTENCE = "Hello. This is NeuroSonic. Your voice assistant is working correctly."
HAVE_VOICE = DEFAULT_VOICE.exists()
HAVE_MAP = (MAP_DIR / "manifest.json").exists()
_VOICE = None


def voice():
    global _VOICE
    if _VOICE is None:
        _VOICE = PiperTTS(DEFAULT_VOICE)
    return _VOICE


def wav_stats(data):
    with wave.open(io.BytesIO(data)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64)
        return w.getframerate(), w.getnchannels(), w.getsampwidth(), len(a) / w.getframerate(), float(np.sqrt((a ** 2).mean()))


class _NoService:
    pass


# ======================================================================================== voice
@unittest.skipUnless(HAVE_VOICE, "voice model not installed (models/tts/en_IN-spicor)")
class TestPiperVoice(unittest.TestCase):
    def test_acceptance_sentence_is_real_speech_audio(self):
        sr, ch, sw, dur, rms = wav_stats(voice().synthesize(TEST_SENTENCE))
        self.assertEqual((sr, ch, sw), (22050, 1, 2))
        self.assertTrue(3.0 < dur < 9.0, dur)      # measured 5.34 s
        self.assertGreater(rms, 500)               # not silence (measured ~5300)

    def test_cache_and_limits(self):
        v = voice()
        a = v.synthesize("Cache test sentence.")
        hits = v.stats["cache_hits"]
        self.assertEqual(v.synthesize("Cache   test sentence."), a)   # whitespace-normalised, cached
        self.assertEqual(v.stats["cache_hits"], hits + 1)
        with self.assertRaises(TTSError):
            v.synthesize("   ")
        with self.assertRaises(TTSError):
            v.synthesize("x" * 401)

    def test_works_without_internet(self):
        with no_internet() as attempts:
            data = PiperTTS(DEFAULT_VOICE).synthesize("Offline voice check.")   # fresh load from disk
        self.assertEqual(attempts, [])
        self.assertGreater(wav_duration(data), 0.5)

    def test_network_guard_really_blocks(self):
        with no_internet(), self.assertRaises(NetworkBlocked):
            http.client.HTTPConnection("example.com", 80, timeout=2).request("GET", "/")

    def test_info(self):
        i = voice().info()
        self.assertTrue(i["available"])
        self.assertEqual(i["language"], "en-IN")
        self.assertEqual(i["engine_licence"], "GPL-3.0-or-later")
        self.assertIn("AGPL-3.0", i["voice_licence"])


# ======================================================================================== map
@unittest.skipUnless(HAVE_MAP, "offline map not built (tools/build_offline_map.py)")
class TestOfflineMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from neurosonic.maps import OfflineMap
        cls.m = OfflineMap(MAP_DIR)

    def test_coverage_and_counts(self):
        b = self.m.bbox
        self.assertEqual((b["south"], b["west"], b["north"], b["east"]), (12.86, 79.07, 13.0, 79.21))
        self.assertTrue(self.m.in_coverage(12.9165, 79.1325))      # Vellore centre
        self.assertFalse(self.m.in_coverage(13.08, 79.13))
        self.assertGreater(self.m.main_share, 0.98)
        self.assertGreater(len(self.m.nodes), 30000)

    def test_search(self):
        names = lambda q: [p["name"] for p in self.m.search(q, 5)]
        self.assertIn("CMC Hospital", names("CMC Hospital"))
        self.assertIn("Vellore Fort", names("vellore fort"))
        self.assertTrue(any("Katpadi" in n for n in names("katpadi")))
        self.assertEqual(self.m.search("x"), [])

    def test_route_is_shortest_path(self):
        """A* result equals an independent Dijkstra on random pairs of the main network."""
        main = np.flatnonzero(self.m.comp == self.m.main_comp)
        rng = random.Random(1)
        for _ in range(8):
            s, t = (int(x) for x in rng.sample(list(main), 2))
            prev = self.m._astar(s, t)
            path, length = [t], 0.0
            while path[-1] != s:
                u, l, _ = prev[path[-1]]
                length += l
                path.append(u)
            dist, pq, done = {s: 0.0}, [(0.0, s)], set()
            while pq:
                d, u = heapq.heappop(pq)
                if u == t:
                    break
                if u in done:
                    continue
                done.add(u)
                for v, l, _ in self.m.adj[u]:
                    if d + l < dist.get(v, math.inf):
                        dist[v] = d + l
                        heapq.heappush(pq, (d + l, v))
            self.assertAlmostEqual(length, dist[t], places=6)

    def test_route_content_and_island_note(self):
        from neurosonic.maps import MapError
        fort = self.m.search("Vellore Fort", 1)[0]
        cmc = self.m.search("CMC Hospital", 1)[0]
        r = self.m.route((fort["lat"], fort["lon"]), (cmc["lat"], cmc["lon"]))
        self.assertGreater(r["distance_m"], 700)
        self.assertTrue(r["steps"][0]["text"].startswith("Head "))
        self.assertEqual(r["steps"][-1]["turn"], "arrive")
        self.assertTrue(any("not connected to the street network" in n for n in r["notes"]))
        with self.assertRaises(MapError):
            self.m.route((12.9165, 79.1325), (13.08, 79.13))      # destination outside coverage

    def test_works_without_internet(self):
        from neurosonic.maps import OfflineMap
        with no_internet() as attempts:
            m = OfflineMap(MAP_DIR)
            a, b = m.search("Katpadi", 1)[0], m.search("VIT", 1)[0]
            r = m.route((a["lat"], a["lon"]), (b["lat"], b["lon"]))
        self.assertEqual(attempts, [])
        self.assertGreater(r["distance_m"], 1000)


# ======================================================================================== HTTP API
@unittest.skipUnless(HAVE_VOICE and HAVE_MAP, "voice model or offline map missing")
class TestVoiceMapApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from neurosonic.maps import OfflineMap
        cls.td = Path(tempfile.mkdtemp(prefix="ns_vm_"))
        cls.httpd = make_server(_NoService(), None, "127.0.0.1", 0, tts=PiperTTS(DEFAULT_VOICE, cache_dir=cls.td),
                                offline_map=OfflineMap(MAP_DIR))
        serve_in_thread(cls.httpd)
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.td, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        c.request(method, path, body=None if body is None else json.dumps(body), headers=headers or {})
        r = c.getresponse()
        out = r.status, dict(r.getheaders()), r.read()
        c.close()
        return out

    def test_tts_endpoint_and_ranges(self):
        from urllib.parse import quote
        st, h, wav = self.req("GET", "/api/tts?text=" + quote(TEST_SENTENCE))
        self.assertEqual((st, h["Content-Type"], h["Accept-Ranges"]), (200, "audio/wav", "bytes"))
        self.assertEqual(wav[:4], b"RIFF")
        self.assertGreater(wav_duration(wav), 3)
        st, h, part = self.req("GET", "/api/tts?text=" + quote(TEST_SENTENCE), headers={"Range": "bytes=0-1"})
        self.assertEqual((st, part, h["Content-Range"]), (206, b"RI", f"bytes 0-1/{len(wav)}"))   # iOS probe
        st, h, part = self.req("GET", "/api/tts?text=" + quote(TEST_SENTENCE), headers={"Range": "bytes=100-"})
        self.assertEqual((st, part), (206, wav[100:]))
        st, h, _ = self.req("GET", "/api/tts?text=" + quote(TEST_SENTENCE), headers={"Range": f"bytes={len(wav) + 5}-"})
        self.assertEqual(st, 416)
        self.assertEqual(self.req("GET", "/api/tts?text=")[0], 503)
        st, h, body = self.req("GET", "/api/tts/status")
        self.assertTrue(json.loads(body)["available"])

    def test_voice_report_roundtrip(self):
        st, _, _ = self.req("POST", "/api/voice/report", {"engine": "neural", "ok": True, "text": TEST_SENTENCE,
                                                          "user_agent": "test-agent"})
        self.assertEqual(st, 200)
        reps = json.loads(self.req("GET", "/api/voice/reports")[2])["reports"]
        self.assertEqual(reps[-1]["user_agent"], "test-agent")
        self.assertEqual(reps[-1]["ok"], "True")

    def test_map_endpoints(self):
        st, h, info = self.req("GET", "/api/map/info")
        self.assertTrue(json.loads(info)["available"])
        st, h, data = self.req("GET", "/api/map/data", headers={"Accept-Encoding": "gzip"})
        self.assertEqual((st, h.get("Content-Encoding")), (200, "gzip"))
        d = json.loads(gzip.decompress(data))
        self.assertIn("roads", d)
        self.assertIn("OpenStreetMap", d["attribution"])
        res = json.loads(self.req("GET", "/api/map/search?q=CMC%20Hospital")[2])["results"]
        self.assertTrue(res)
        st, _, body = self.req("POST", "/api/route", {"from": {"lat": 12.9690, "lon": 79.1356},
                                                       "to": {"lat": res[0]["lat"], "lon": res[0]["lon"]}})
        self.assertEqual(st, 200, body)
        r = json.loads(body)
        self.assertGreater(len(r["polyline"]), 2)
        st, _, body = self.req("POST", "/api/route", {"from": {"lat": 12.9690, "lon": 79.1356}, "to": {"lat": 13.2, "lon": 79.1}})
        self.assertEqual(st, 400)
        self.assertIn("outside the offline map", json.loads(body)["error"])
        self.assertEqual(self.req("POST", "/api/route", {"from": {}})[0], 400)

    def test_api_serves_voice_and_route_without_internet(self):
        from urllib.parse import quote
        with no_internet() as attempts:
            st1, _, _ = self.req("GET", "/api/tts?text=" + quote("No internet needed."))
            st2, _, _ = self.req("POST", "/api/route", {"from": {"lat": 12.9690, "lon": 79.1356},
                                                         "to": {"lat": 12.9248, "lon": 79.1355}})
        self.assertEqual((st1, st2), (200, 200))
        self.assertEqual(attempts, [])


if __name__ == "__main__":
    unittest.main()
