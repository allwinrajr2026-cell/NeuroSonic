// Product-refinement tests (2026-11-02): GPS fix quality, GPS loss, reroute limit, turn pre-announcements,
// speech pacing (latest-wins keys, cooldowns, interruption) and the canvas map renderer (rendering + resizing).
// Node's built-in runner; no packages. These test logic only; they are not evidence of real-world behaviour.
import { test } from "node:test";
import assert from "node:assert/strict";
import { COOLDOWN_MS, SpeechQueue } from "../../web/js/speech.js";
import { assessFix, canReroute, followRoute, gpsWatch, prepareRoute } from "../../web/js/nav.js";

// ---------------------------------------------------------------- GPS fix quality
test("GPS: no fix, good, poor, unusable and stale fixes", () => {
  const now = 1_000_000;
  assert.equal(assessFix(null, now).use, false);
  const good = assessFix({ lat: 12.9, lon: 79.1, accuracy: 8, timestamp: now - 1000 }, now);
  assert.deepEqual([good.use, good.level], [true, "good"]);
  const poor = assessFix({ lat: 12.9, lon: 79.1, accuracy: 70, timestamp: now - 1000 }, now);
  assert.deepEqual([poor.use, poor.level], [true, "poor"]);
  assert.match(poor.message, /accuracy is low, about 70 metres/);
  const bad = assessFix({ lat: 12.9, lon: 79.1, accuracy: 400, timestamp: now }, now);
  assert.deepEqual([bad.use, bad.level], [false, "unusable"]);
  assert.match(bad.message, /Guidance paused/);
  const stale = assessFix({ lat: 12.9, lon: 79.1, accuracy: 5, timestamp: now - 40000 }, now);
  assert.deepEqual([stale.use, stale.level], [false, "stale"]);
  assert.match(stale.message, /40 seconds old/);
  assert.equal(assessFix({ lat: NaN, lon: 79.1, accuracy: 5, timestamp: now }, now).use, false);
});

test("GPS: permission-denied state never yields a usable position (no fix object)", () => {
  // the app keeps fix = null after a denial; guidance must then have no position
  assert.equal(assessFix(null, Date.now()).level, "none");
});

test("GPS loss and recovery are announced once each, only during guidance", () => {
  let st = {}, r;
  r = gpsWatch(st, 10_000, 9_000, true); assert.equal(r.text, null); st = r.state;
  r = gpsWatch(st, 31_000, 9_000, true); assert.match(r.text, /GPS signal lost/); st = r.state;
  r = gpsWatch(st, 40_000, 9_000, true); assert.equal(r.text, null); st = r.state;           // not repeated
  r = gpsWatch(st, 41_000, 40_500, true); assert.match(r.text, /restored/); st = r.state;
  r = gpsWatch(st, 99_000, 9_000, false); assert.equal(r.text, null);                         // no guidance: silent
});

test("rerouting is rate-limited", () => {
  assert.equal(canReroute(null, 0), true);
  assert.equal(canReroute(1000, 10_000), false);
  assert.equal(canReroute(1000, 16_000), true);
});

// ---------------------------------------------------------------- routes: pre-announcement wording, off-route, reroute
const N = (m) => 12.90 + m / 110540;
const ROUTE = {
  polyline: [[N(0), 79.13], [N(100), 79.13], [N(200), 79.13], [N(300), 79.13]],
  steps: [
    { text: "Head north on Test Road for 200 metres.", action: "Head north on Test Road", at: [N(0), 79.13] },
    { text: "Turn left onto Side Street and walk 100 metres.", action: "Turn left onto Side Street", at: [N(200), 79.13] },
    { text: "You have reached the destination area.", action: "You have arrived", at: null, turn: "arrive" },
  ],
};

test("route following uses the short action for pre-announcements", () => {
  const r = prepareRoute(ROUTE, "Library");
  let out = followRoute(r, { lat: N(140), lon: 79.13, accuracy: 5 }, {});
  assert.equal(out.texts[0], "In about 60 metres, turn left onto Side Street.");
  out = followRoute(r, { lat: N(185), lon: 79.13, accuracy: 5 }, out.state);
  assert.equal(out.texts[0], "Turn left onto Side Street and walk 100 metres.");
});

test("off-route detection then rerouting from the new position", () => {
  const r = prepareRoute(ROUTE, "Library");
  const off = { lat: N(100), lon: 79.13 + 80 / 108000, accuracy: 8 };     // ~80 m east of the route
  let out = followRoute(r, off, {});
  assert.equal(out.offRoute, false);                                      // one fix is not enough
  out = followRoute(r, off, out.state);
  assert.equal(out.offRoute, true);
  assert.match(out.texts[0], /off the route\. Recalculating/);
  // the app then requests a new route starting at the current position; following restarts with fresh state
  const rerouted = prepareRoute({ polyline: [[off.lat, off.lon], [N(300), 79.13]], steps: [{ text: "Head north-west for 210 metres.", at: [off.lat, off.lon] },
    { text: "You have reached the destination area.", at: null, turn: "arrive" }] }, "Library");
  const again = followRoute(rerouted, off, {});
  assert.equal(again.offRoute, false);
  assert.ok(again.progress.distance < 1);
});

test("off-route tolerance grows with poor GPS accuracy", () => {
  const r = prepareRoute(ROUTE, "Library");
  const fuzzy = { lat: N(100), lon: 79.13 + 60 / 108000, accuracy: 60 };  // 60 m away but ±60 m accuracy
  let out = followRoute(r, fuzzy, {}); out = followRoute(r, fuzzy, out.state);
  assert.equal(out.offRoute, false);
});

// ---------------------------------------------------------------- speech pacing
test("speech: a newer path state replaces an outdated queued one (latest wins)", () => {
  const q = new SpeechQueue();
  q.push("Caution. An object is detected in the walking path.", "obstacle", 0, "path");
  q.push("Turn left onto Side Street.", "navigation", 10);
  q.push("The visible path appears clear. Continue carefully.", "info", 20, "path");
  const texts = q.items.map((i) => i.text);
  assert.ok(!texts.includes("Caution. An object is detected in the walking path."), texts);
  assert.ok(texts.includes("The visible path appears clear. Continue carefully."));
  assert.ok(texts.includes("Turn left onto Side Street."));
});

test("speech: duplicate suppression with per-category cooldowns", () => {
  const q = new SpeechQueue();
  assert.ok(q.push("Stop. The walking path may be blocked.", "urgent", 0));
  q.next(0);
  assert.equal(q.push("Stop. The walking path may be blocked.", "urgent", 1000), false);          // within 3 s
  assert.ok(q.push("Stop. The walking path may be blocked.", "urgent", COOLDOWN_MS.urgent + 1));   // allowed again
  q.clear();
  assert.ok(q.push("The visible path appears clear. Continue carefully.", "info", 0)); q.next(0);
  assert.equal(q.push("The visible path appears clear. Continue carefully.", "info", 10_000), false); // routine waits longer
  assert.ok(COOLDOWN_MS.info > COOLDOWN_MS.urgent);
});

test("speech: urgent interrupts navigation, obstacle and descriptions; descriptions never interrupt", () => {
  const q = new SpeechQueue();
  const nav = { text: "Turn left.", category: "navigation", priority: 1 };
  const obs = { text: "Caution.", category: "obstacle", priority: 2 };
  const desc = { text: "Person on the left.", category: "description", priority: 0 };
  assert.equal(q.shouldInterrupt(nav, "urgent"), true);
  assert.equal(q.shouldInterrupt(obs, "urgent"), true);
  assert.equal(q.shouldInterrupt(desc, "urgent"), true);
  assert.equal(q.shouldInterrupt(nav, "description"), false);
  assert.equal(q.shouldInterrupt(desc, "navigation"), false);
  // urgent is always taken first from the queue
  q.push("Person on the left.", "description", 0);
  q.push("In about 60 metres, turn left.", "navigation", 1);
  q.push("Stop. The walking path may be blocked.", "urgent", 2);
  assert.equal(q.next(3).category, "urgent");
});

test("speech: stale descriptions are dropped rather than spoken late", () => {
  const q = new SpeechQueue();
  q.push("Person on the left.", "description", 0);
  assert.equal(q.next(5000), null);
});

// ---------------------------------------------------------------- map renderer (stub canvas)
function stubCanvas(width, height) {
  const calls = { fillRect: 0, stroke: 0, arc: 0, fillText: 0 };
  const ctx = new Proxy({}, {
    get(_, k) {
      if (k === "measureText") return () => ({ width: 10 });
      if (k in calls) return () => { calls[k] += 1; };
      return () => {};
    },
    set() { return true; },
  });
  const size = { width, height };
  return {
    calls, size, width: 0, height: 0, style: {},
    getContext: () => ctx, getBoundingClientRect: () => ({ width: size.width, height: size.height }),
    addEventListener() {}, setPointerCapture() {},
  };
}

test("map: renders data, fits the area, resizes and follows the position", async () => {
  globalThis.window = { devicePixelRatio: 3, addEventListener() {} };
  globalThis.requestAnimationFrame = (f) => { f(); return 1; };
  const { MapView } = await import("../../web/js/mapview.js");
  const c = stubCanvas(400, 300);
  const m = new MapView(c);
  assert.equal(c.width, 1200);                        // device-pixel-ratio aware backing store
  assert.equal(c.height, 900);
  const bbox = { south: 12.86, north: 13.0, west: 79.07, east: 79.21 };
  m.setData({ bbox, roads: { major: [[[79.1, 12.9], [79.2, 12.95]]], minor: [], medium: [], foot: [] } });
  assert.ok(c.calls.stroke > 0 && c.calls.fillRect > 0, "drew roads and background");
  const [x0, y0] = m._xy(bbox.north, bbox.west), [x1, y1] = m._xy(bbox.south, bbox.east);
  assert.ok(x0 >= 0 && y0 >= 0 && x1 <= 400 && y1 <= 300, "whole area visible after fit");
  const ll = m._ll(123, 77), xy = m._xy(ll.lat, ll.lon);
  assert.ok(Math.abs(xy[0] - 123) < 1e-6 && Math.abs(xy[1] - 77) < 1e-6, "projection round-trip");
  // resize (rotation / iPhone toolbar change): backing store follows, no distortion (same metres per pixel in x and y)
  c.size.width = 430; c.size.height = 360; m.resize();
  assert.equal(c.width, 1290); assert.equal(c.height, 1080);
  const a = m._xy(12.93, 79.14), b = m._xy(12.93 + 100 / 110540, 79.14), d = m._xy(12.93, 79.14 + 100 / (111320 * Math.cos(12.93 * Math.PI / 180)));
  assert.ok(Math.abs(Math.abs(b[1] - a[1]) - Math.abs(d[0] - a[0])) < 1e-6, "100 m north == 100 m east on screen");
  // first position inside the area centres the map at street zoom; follow mode keeps it centred
  m.setPosition({ lat: 12.93, lon: 79.14, accuracy: 10 });
  assert.ok(Math.abs(m.center.lat - 12.93) < 1e-9 && m.mpp <= 3);
  m.setFollow(true); m.setPosition({ lat: 12.931, lon: 79.141, accuracy: 10 });
  assert.ok(Math.abs(m.center.lat - 12.931) < 1e-9);
  m.setFollow(false); m.setPosition({ lat: 12.94, lon: 79.15, accuracy: 10 });
  assert.ok(Math.abs(m.center.lat - 12.931) < 1e-9, "not following: map stays where the user put it");
  // route + destination drawn
  const arcs = c.calls.arc;
  m.setDestination({ lat: 12.95, lon: 79.16, name: "CMC" }); m.setRoute([[12.93, 79.14], [12.95, 79.16]]);
  assert.ok(c.calls.arc > arcs && c.calls.fillText > 0);
  assert.equal(m.inCoverage(12.93, 79.14), true); assert.equal(m.inCoverage(13.5, 79.14), false);
});
