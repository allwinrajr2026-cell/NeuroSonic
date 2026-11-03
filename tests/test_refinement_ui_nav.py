"""Product refinement: spoken route steps (turn detection, merging, distances), and the structure of the
mobile interface (How It Works tab, safe areas, no fixed widths, offline - no external resources).
Browser rendering at iPhone size is checked separately by tests/js/ui_refine_cdp.mjs (manual, needs Chrome)."""
import re
import unittest

from tests._common import ROOT

MAP_DIR = ROOT / "maps" / "vellore"
WEB = ROOT / "web"


@unittest.skipUnless((MAP_DIR / "graph.json").exists(), "offline map not built")
class TestRouteSteps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from neurosonic.maps import OfflineMap
        cls.m = OfflineMap(MAP_DIR)

    def route(self, a, b):
        pa, pb = self.m.search(a, 1)[0], self.m.search(b, 1)[0]
        return self.m.route((pa["lat"], pa["lon"]), (pb["lat"], pb["lon"]))

    def test_steps_are_consistent_and_concise(self):
        for a, b in (("Katpadi", "CMC Hospital"), ("Vellore Fort", "CMC Hospital"), ("Katpadi", "VIT")):
            with self.subTest(f"{a} -> {b}"):
                r = self.route(a, b)
                steps = r["steps"]
                self.assertEqual(steps[-1]["turn"], "arrive")
                self.assertTrue(steps[0]["text"].startswith("Head "))
                walked = r["distance_m"] - r["snap_m"]["start"] - r["snap_m"]["destination"]
                self.assertLess(abs(sum(s["distance_m"] for s in steps) - walked), 15)   # steps cover the path
                for s in steps[1:-1]:
                    self.assertGreaterEqual(s["distance_m"], 12, s)                      # no micro-steps
                    self.assertTrue(s["action"] and s["text"].startswith(s["action"]), s)
                    if s["turn"] != "continue":
                        self.assertGreaterEqual(abs(s["turn_angle"]), 30, s)          # real turns only
                self.assertLess(len(steps), 15)
                for s in steps:
                    self.assertNotIn("unnamed road", s["text"])                          # no filler wording

    def test_straight_named_street_change_is_continue(self):
        r = self.route("Katpadi", "CMC Hospital")
        cont = [s for s in r["steps"] if s["turn"] == "continue"]
        self.assertTrue(cont)
        self.assertTrue(all(s["text"].startswith("Continue onto ") for s in cont))


class TestMobileInterface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (WEB / "index.html").read_text(encoding="utf-8")
        cls.css = (WEB / "style.css").read_text(encoding="utf-8")

    def test_screens_and_tab_bar(self):
        for sec in ("tab-detect", "tab-nav", "tab-hist", "tab-set", "tab-how", "tab-sim"):
            self.assertIn(f'id="{sec}"', self.html)
        bar = re.search(r'<nav class="tabs".*?</nav>', self.html, re.S).group(0)
        self.assertEqual(re.findall(r'data-tab="([^"]+)"', bar), ["tab-detect", "tab-nav", "tab-hist", "tab-set", "tab-how"])
        self.assertIn('id="mic"', bar)                                   # microphone reachable on every screen

    def test_how_it_works_content(self):
        how = re.search(r'<section id="tab-how".*?</section>', self.html, re.S).group(0)
        topics = re.findall(r"<summary>(\d+)\.", how)
        self.assertEqual(topics, [str(i) for i in range(1, 12)])        # 10 topics + 11. online scene description
        for box in ("iPhone camera", "NeuroSonic app", "Local laptop server",
                    "Camera detection · speech recognition · routing", "Voice feedback to the user"):
            self.assertIn(box, how)
        self.assertIn("<strong>not</strong> a standalone iPhone app", how)
        self.assertIn("Local guidance needs no internet", " ".join(how.split()))
        self.assertIn("only the optional online scene description does", " ".join(how.split()))
        self.assertIn("Not a replacement for a cane", how)

    def test_walking_guidance_switch_and_settings(self):
        for i in ("od-walk", "od-desc", "v-describe", "a-state", "perm-cam", "perm-mic", "perm-loc", "off-list",
                  "g-age", "rt-now"):
            self.assertIn(f'id="{i}"', self.html)

    def test_phone_layout_rules(self):
        self.assertIn("viewport-fit=cover", self.html)
        self.assertIn("env(safe-area-inset-bottom", self.css)
        self.assertIn("env(safe-area-inset-top", self.css)
        self.assertIn("overflow-x: hidden", self.css)
        # inputs at 16 px: iOS Safari zooms the page when focusing smaller text fields
        self.assertRegex(self.css, r"input\[type=search\][^{]*\{[^}]*font-size: 16px")
        # no fixed pixel widths above a phone width
        self.assertFalse([w for w in re.findall(r"(?<![-\w])width:\s*(\d+)px", self.css) if int(w) > 360])
        for size in re.findall(r"min-height:\s*(\d+)px", self.css):
            self.assertGreaterEqual(int(size), 40)                       # touch targets

    def test_no_external_resources(self):
        for page in (self.html, self.css):
            self.assertIsNone(re.search(r'(src|href)="https?://', page))
            self.assertNotIn("@import", page)
            self.assertNotIn("url(http", page)


if __name__ == "__main__":
    unittest.main()
