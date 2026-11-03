"""NeuroSonic app: HTTP API end to end (real server on a free port, temporary SQLite database)."""
import base64
import json
import shutil
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from tests._common import ROOT, demo_available, demo_pair
from neurosonic.server import make_server, serve_in_thread
from neurosonic.service import DetectionService
from neurosonic.store import Store

DETEC = ROOT / "demo_data" / "detec_test"


class AppTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = Path(tempfile.mkdtemp(prefix="neurosonic_test_"))
        cls.store = Store(cls.td / "t.sqlite3")
        cls.service = DetectionService(cls.store)
        cls.httpd = make_server(cls.service, cls.store, "127.0.0.1", 0)
        serve_in_thread(cls.httpd)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.service.stop_replay()
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.close()
        shutil.rmtree(cls.td, ignore_errors=True)

    def call(self, path, body=None, raw=False):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = r.read()
                return r.status, (payload if raw else json.loads(payload or b"null")), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null"), e.headers


class TestAppApi(AppTestBase):
    def test_index_and_static(self):
        st, body, hdr = self.call("/", raw=True)
        self.assertEqual(st, 200)
        self.assertIn(b"NeuroSonic", body)
        self.assertIn("text/html", hdr["Content-Type"])
        st, _, _ = self.call("/../weights/best.pt", raw=True)
        self.assertEqual(st, 404)
        st, _, _ = self.call("/%2e%2e/weights/best.pt", raw=True)
        self.assertEqual(st, 404)

    def test_status(self):
        st, s, _ = self.call("/api/status")
        self.assertEqual(st, 200)
        self.assertEqual(s["model"]["names"], ["person", "Ebike", "Car"])
        self.assertEqual(s["model"]["sha256"][:16], "da043ff2e1edd393")
        self.assertIn("detec_test", [r["name"] for r in s["replay_sets"]])

    @unittest.skipUnless(demo_available(), "demo samples missing")
    def test_detect_upload(self):
        ir, dp = demo_pair("recon_b00_i03.png")
        st, r, _ = self.call("/api/detect", {"ir_base64": base64.b64encode(ir.read_bytes()).decode(),
                                             "depth_base64": "data:image/png;base64," + base64.b64encode(dp.read_bytes()).decode()})
        self.assertEqual(st, 200, r)
        self.assertEqual(r["quality"]["status"], "ok")
        self.assertEqual([d["class_name"] for d in r["detections"]], ["person"])
        self.assertEqual(len(r["alerts"]), 1)
        self.assertTrue(r["alerts"][0].startswith("Person detected"))
        self.assertTrue(base64.b64decode(r["annotated_jpeg_base64"])[:2] == b"\xff\xd8")
        st, h, _ = self.call("/api/history?limit=5")
        self.assertTrue(any(x["source"] == "upload" and x["class_name"] == "person" for x in h["history"]))

    def test_detect_rejects_bad_input(self):
        st, r, _ = self.call("/api/detect", {"ir_base64": "@@@", "depth_base64": ""})
        self.assertEqual(st, 400)
        st, r, _ = self.call("/api/detect", {"ir_base64": base64.b64encode(b"not an image").decode(),
                                             "depth_base64": base64.b64encode(b"x").decode()})
        self.assertEqual(st, 400)
        self.assertIn("could not be decoded", r["error"])

    def test_places_crud_and_validation(self):
        st, r, _ = self.call("/api/places", {"name": "Library", "lat": 51.5, "lon": -0.12})
        self.assertEqual(st, 200)
        pid = r["id"]
        self.assertIn("Library", [p["name"] for p in self.call("/api/places")[1]["places"]])
        self.assertEqual(self.call("/api/places", {"name": "x", "lat": 95, "lon": 0})[0], 400)
        self.assertEqual(self.call("/api/places", {"name": "", "lat": 1, "lon": 1})[0], 400)
        self.assertEqual(self.call("/api/places/delete", {"id": pid})[0], 200)
        self.assertEqual(self.call("/api/places/delete", {"id": pid})[0], 404)

    def test_client_alerts_and_stats(self):
        st, ev, _ = self.call("/api/alerts", {"source": "eventsim", "kind": "motion", "text": "Motion on the left"})
        self.assertEqual(st, 200)
        self.assertGreater(ev["id"], 0)
        self.assertEqual(self.call("/api/alerts", {"source": "replay", "kind": "object", "text": "x"})[0], 400)
        st, ev2, _ = self.call(f"/api/events?since={ev['id'] - 1}")
        self.assertIn("Motion on the left", [e["text"] for e in ev2["events"]])
        st, s, _ = self.call("/api/stats")
        self.assertGreaterEqual(s["by_source"].get("eventsim", 0), 1)

    def test_errors(self):
        self.assertEqual(self.call("/api/nope", {})[0], 404)
        self.assertEqual(self.call("/api/replay/start", {"set": "../../etc"})[0], 400)
        self.assertEqual(self.call("/api/replay/start", {"set": "detec_test", "fps": 100})[0], 400)
        self.assertEqual(self.call("/api/events?since=abc")[0], 400)


@unittest.skipUnless((DETEC / "manifest.json").exists(), "detec_test demo missing")
class TestAppReplay(AppTestBase):
    def test_replay_stream(self):
        st, s, _ = self.call("/api/replay/start", {"set": "detec_test", "fps": 10, "start": 260, "loop": False})
        self.assertEqual(st, 200)
        self.assertTrue(s["running"])
        deadline, state = time.time() + 60, None
        while time.time() < deadline:
            state = self.call("/api/replay/state")[1]
            if state["seq"] >= 15:
                break
            time.sleep(0.2)
        self.assertGreaterEqual(state["seq"], 15, state)
        self.assertEqual(state["quality"]["status"], "ok")
        st, jpg, hdr = self.call("/api/replay/frame.jpg", raw=True)
        self.assertEqual(st, 200)
        self.assertEqual(jpg[:2], b"\xff\xd8")
        events = self.call("/api/events?since=0")[1]["events"]
        self.assertTrue(any(e["source"] == "replay" and e["kind"] == "object" for e in events), events)
        st, s, _ = self.call("/api/replay/stop", {})
        self.assertFalse(s["running"])


if __name__ == "__main__":
    unittest.main()
