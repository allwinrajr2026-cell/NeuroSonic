// Unit tests for the browser logic (Node's built-in runner, no packages): node --test tests/js
import { test } from "node:test";
import assert from "node:assert/strict";
import { SpeechQueue, panFor } from "../../web/js/speech.js";
import { bearingDeg, compass, distanceM, formatDistance, guidance, osmWalkingUrl, parseCoords } from "../../web/js/nav.js";
import { MotionAlerter, diffEvents, paintEvents, toGray } from "../../web/js/eventsim.js";

// ---------------------------------------------------------------- speech queue
test("speech queue: priority order, de-duplication and stale obstacle messages", () => {
  const q = new SpeechQueue({ dedupeMs: 4000 });
  q.push("Destination 200 metres", "navigation", 0);
  q.push("Person detected ahead.", "obstacle", 10);
  q.push("Obstacle detection unavailable.", "system", 20);
  assert.equal(q.push("Person detected ahead.", "obstacle", 30), false); // already queued
  assert.equal(q.next(100).text, "Obstacle detection unavailable.");
  assert.equal(q.next(200).text, "Person detected ahead.");
  assert.equal(q.next(300).text, "Destination 200 metres");
  assert.equal(q.push("Person detected ahead.", "obstacle", 1000), false); // said 800 ms ago
  assert.equal(q.push("Person detected ahead.", "obstacle", 5000), true);
  assert.equal(q.next(10000), null); // 5 s old obstacle warning is dropped, not spoken late
});

test("speech queue: length limit keeps the most important items", () => {
  const q = new SpeechQueue({ maxLength: 2 });
  q.push("a", "info", 0); q.push("b", "obstacle", 0); q.push("c", "system", 0);
  assert.deepEqual([q.next(1).text, q.next(1).text, q.next(1)], ["c", "b", null]);
});

test("stereo pan per position", () => {
  assert.equal(panFor("left"), -0.8); assert.equal(panFor("right"), 0.8); assert.equal(panFor("ahead"), 0);
});

// ---------------------------------------------------------------- navigation maths
test("distance and bearing", () => {
  const london = { lat: 51.5007, lon: -0.1246 }, paris = { lat: 48.8584, lon: 2.2945 };
  assert.ok(Math.abs(distanceM(london, paris) - 340500) < 3000);
  assert.ok(Math.abs(bearingDeg({ lat: 0, lon: 0 }, { lat: 1, lon: 0 }) - 0) < 1e-6);
  assert.ok(Math.abs(bearingDeg({ lat: 0, lon: 0 }, { lat: 0, lon: 1 }) - 90) < 1e-6);
  assert.equal(compass(0), "north"); assert.equal(compass(44), "north-east"); assert.equal(compass(181), "south");
  assert.equal(compass(350), "north"); assert.equal(compass(-90), "west");
});

test("formatting and coordinate parsing", () => {
  assert.equal(formatDistance(242), "240 metres");
  assert.equal(formatDistance(1234), "1.2 kilometres");
  assert.deepEqual(parseCoords(" 51.5007, -0.1246 "), { lat: 51.5007, lon: -0.1246 });
  assert.deepEqual(parseCoords("10 20"), { lat: 10, lon: 20 });
  assert.equal(parseCoords("95, 0"), null);
  assert.equal(parseCoords("hello"), null);
  assert.match(osmWalkingUrl({ lat: 1, lon: 2 }, { lat: 3, lon: 4 }), /^https:\/\/www\.openstreetmap\.org\/directions\?engine=fossgis_osrm_foot/);
});

test("guidance: speaks on start, on 50 m change or after 30 s, and on arrival", () => {
  const dest = { name: "Library", lat: 0.01, lon: 0 };   // ~1112 m north
  let g = guidance({ lat: 0, lon: 0, accuracy: 10 }, dest, {}, 0);
  assert.equal(g.text, "Library: 1.1 kilometres to the north, straight line.");
  g = guidance({ lat: 0.0001, lon: 0, accuracy: 10 }, dest, g.state, 1000);  // moved 11 m
  assert.equal(g.text, null);
  g = guidance({ lat: 0.0006, lon: 0, accuracy: 10 }, dest, g.state, 2000);  // moved 67 m since last spoken
  assert.match(g.text, /^Library: 1\.0 kilometres to the north/);
  g = guidance({ lat: 0.0006, lon: 0, accuracy: 10 }, dest, g.state, 40000);  // 30 s repeat
  assert.ok(g.text);
  g = guidance({ lat: 0.0099, lon: 0, accuracy: 10 }, dest, g.state, 41000);  // 11 m away
  assert.match(g.text, /^You are near Library/);
  assert.equal(guidance({ lat: 0.0099, lon: 0, accuracy: 10 }, dest, g.state, 42000).text, null);
});

test("guidance warns about poor GPS accuracy", () => {
  const g = guidance({ lat: 0, lon: 0, accuracy: 120 }, { name: "X", lat: 0.01, lon: 0 }, {}, 0);
  assert.match(g.text, /GPS accuracy is low, about 120 metres/);
});

// ---------------------------------------------------------------- event simulation
test("frame differencing: polarity and per-third fractions", () => {
  const w = 9, h = 2, prev = new Uint8ClampedArray(w * h).fill(100), cur = prev.slice();
  cur[0] = 200;      // left third brighter
  cur[w + 8] = 10;   // right third darker
  const ev = diffEvents(prev, cur, w, h, 25);
  assert.equal(ev.on, 1); assert.equal(ev.off, 1);
  assert.equal(ev.polarity[0], 1); assert.equal(ev.polarity[w + 8], -1);
  assert.deepEqual(ev.thirds, [1 / 6, 0, 1 / 6]);
  const out = new Uint8ClampedArray(w * h * 4); paintEvents(ev.polarity, out);
  assert.deepEqual([...out.slice(0, 4)], [0, 255, 0, 255]);
});

test("grey conversion", () => {
  assert.deepEqual([...toGray(new Uint8ClampedArray([255, 255, 255, 255, 0, 0, 0, 255]), 2)], [255, 0]);
});

test("motion alerter: needs sustained motion, has cooldown and a camera-moving guard", () => {
  const m = new MotionAlerter({ level: 0.04, frames: 2, cooldownMs: 4000, globalLevel: 0.25 });
  assert.deepEqual(m.update([0.1, 0, 0], 0), []);                       // 1 frame: not yet
  assert.deepEqual(m.update([0.1, 0, 0], 100).map((a) => a.text), ["Motion on the left."]);
  assert.deepEqual(m.update([0.1, 0, 0], 200), []);                     // cooldown
  assert.deepEqual(m.update([0.1, 0, 0], 4200).map((a) => a.position), ["left"]);
  const g = m.update([0.5, 0.5, 0.5], 5000);
  assert.equal(g.length, 1); assert.equal(g[0].position, null);       // whole image changing
  assert.deepEqual(m.update([0.5, 0.5, 0.5], 5100), []);
});

// ---------------------------------------------------------------- route following (offline routes)
import { followRoute, prepareRoute, projectOnPolyline } from "../../web/js/nav.js";
import { TEST_SENTENCE, silentWavBytes } from "../../web/js/speech.js";

// a straight 300 m route north along lon 79.13, with a turn step at 200 m
const N = (m) => 12.90 + m / 110540;
const ROUTE = {
  polyline: [[N(0), 79.13], [N(100), 79.13], [N(200), 79.13], [N(300), 79.13]],
  steps: [
    { text: "Head north on Test Road for 200 metres.", at: [N(0), 79.13] },
    { text: "Turn left onto Side Street, then continue for 100 metres.", at: [N(200), 79.13] },
    { text: "You have reached the destination area.", at: null, turn: "arrive" },
  ],
};

test("projection onto a polyline", () => {
  const p = projectOnPolyline({ lat: N(150), lon: 79.13 + 20 / 108000 }, ROUTE.polyline);
  assert.ok(Math.abs(p.along - 150) < 1, p.along);
  assert.ok(Math.abs(p.distance - 20) < 1.5, p.distance);
  assert.ok(Math.abs(p.total - 300) < 1);
});

test("route following: pre-announce, announce, arrive", () => {
  const r = prepareRoute(ROUTE, "Library");
  assert.ok(Math.abs(r.steps[1].along - 200) < 1);
  let st = {}, out;
  out = followRoute(r, { lat: N(50), lon: 79.13, accuracy: 5 }, st); st = out.state;
  assert.deepEqual(out.texts, []);
  out = followRoute(r, { lat: N(140), lon: 79.13, accuracy: 5 }, st); st = out.state;
  assert.match(out.texts[0], /^In about 60 metres: turn left onto Side Street/);
  out = followRoute(r, { lat: N(150), lon: 79.13, accuracy: 5 }, st); st = out.state;
  assert.deepEqual(out.texts, []);                                  // not repeated
  out = followRoute(r, { lat: N(185), lon: 79.13, accuracy: 5 }, st); st = out.state;
  assert.equal(out.texts[0], "Turn left onto Side Street, then continue for 100 metres.");
  out = followRoute(r, { lat: N(295), lon: 79.13, accuracy: 5 }, st); st = out.state;
  assert.equal(out.texts[0], "You have arrived near Library.");
  assert.ok(out.state.arrived);
  assert.deepEqual(followRoute(r, { lat: N(296), lon: 79.13 }, st).texts, []);
});

test("route following: off-route needs two consecutive fixes and respects GPS accuracy", () => {
  const r = prepareRoute(ROUTE, "X");
  const off = { lat: N(100), lon: 79.13 + 60 / 108000, accuracy: 5 };   // ~60 m east of the route
  let out = followRoute(r, off, {});
  assert.equal(out.offRoute, false);
  out = followRoute(r, off, out.state);
  assert.equal(out.offRoute, true);
  assert.match(out.texts[0], /off the route/);
  const fuzzy = { lat: N(100), lon: 79.13 + 60 / 108000, accuracy: 50 };  // inaccurate fix: tolerance 75 m
  out = followRoute(r, fuzzy, {}); out = followRoute(r, fuzzy, out.state);
  assert.equal(out.offRoute, false);
});

test("silent unlock WAV and test sentence", () => {
  const b = silentWavBytes();
  assert.equal(String.fromCharCode(...b.slice(0, 4)), "RIFF");
  assert.equal(String.fromCharCode(...b.slice(8, 12)), "WAVE");
  assert.equal(b.length, 44 + 800);
  assert.equal(TEST_SENTENCE, "Hello. This is NeuroSonic. Your voice assistant is working correctly.");
});

import { pointAtAlong } from "../../web/js/nav.js";
test("point at a distance along a polyline (used by the simulated walk)", () => {
  const p = pointAtAlong(ROUTE.polyline, 150);
  assert.ok(Math.abs(projectOnPolyline(p, ROUTE.polyline).along - 150) < 0.5);
  // repeated 20 m steps always advance (regression: the first version got stuck on long segments)
  let along = 0;
  for (let i = 0; i < 10; i++) { const q = pointAtAlong(ROUTE.polyline, along + 20); const a = projectOnPolyline(q, ROUTE.polyline).along; assert.ok(a > along + 19.5); along = a; }
  const end = pointAtAlong(ROUTE.polyline, 1e6);
  assert.deepEqual([end.lat, end.lon], ROUTE.polyline[3]);
});

// ---------------------------------------------------------------- voice: interruption + recorder helpers
import { SpeechQueue as SQ2 } from "../../web/js/speech.js";
import { EndOfSpeech, downsample, encodeWav, rms } from "../../web/js/recorder.js";

test("urgent/obstacle warnings interrupt routine speech; interrupted steps are re-queued once", () => {
  const q = new SQ2();
  const nav = { text: "Turn left onto Gandhi Road.", category: "navigation", priority: 1, t: 0 };
  assert.equal(q.shouldInterrupt(nav, "urgent"), true);
  assert.equal(q.shouldInterrupt(nav, "obstacle"), true);
  assert.equal(q.shouldInterrupt(nav, "system"), true);
  assert.equal(q.shouldInterrupt(nav, "navigation"), false);
  assert.equal(q.shouldInterrupt(nav, "info"), false);
  const obs = { text: "Person ahead.", category: "obstacle", priority: 2, t: 0 };
  assert.equal(q.shouldInterrupt(obs, "obstacle"), false);       // same level: wait in the queue
  assert.equal(q.shouldInterrupt(obs, "urgent"), true);
  assert.equal(q.shouldInterrupt(null, "urgent"), false);
  q.push("Caution. Car ahead.", "urgent", 100);
  assert.equal(q.requeue(nav), true);
  assert.equal(q.next(200).text, "Caution. Car ahead.");             // urgent first
  assert.equal(q.next(300).text, "Turn left onto Gandhi Road.");     // then the interrupted step
  assert.equal(q.requeue(Object.assign({}, nav, { requeued: true })), false);   // only once
  assert.equal(q.requeue(obs), false);                               // stale obstacle warnings are not repeated
  q.push("Old step.", "navigation", 0);
  assert.equal(q.next(20000), null);                                 // still dropped when stale
});

test("recorder: 48 kHz -> 16 kHz WAV and end-of-speech detection", () => {
  const sr = 48000, x = new Float32Array(sr);
  for (let i = 0; i < sr; i++) x[i] = 0.5 * Math.sin((2 * Math.PI * 440 * i) / sr);
  const y = downsample(x, sr);
  assert.equal(y.length, 16000);
  assert.ok(Math.abs(rms(y) - 0.5 / Math.SQRT2) < 0.02);
  const wav = encodeWav(y);
  assert.equal(String.fromCharCode(...wav.slice(0, 4)), "RIFF");
  assert.equal(new DataView(wav.buffer).getUint32(24, true), 16000);
  assert.equal(wav.length, 44 + 32000);
  // 0.5 s quiet, 1 s speech, then quiet: ends ~1 s after speech, not before speech
  const e = new EndOfSpeech({ silenceMs: 1000 });
  const blocks = [...Array(6).fill(0.002), ...Array(12).fill(0.2), ...Array(20).fill(0.002)];
  const states = blocks.map((lvl) => e.push(lvl, 85));
  const end = states.indexOf("end");
  assert.ok(end > 18 && end <= 18 + 13, `ended at block ${end}`);
  assert.ok(e.heardSpeech);
  const silent = new EndOfSpeech({ maxMs: 1000 });
  let s; for (let i = 0; i < 20; i++) { s = silent.push(0.001, 85); if (s !== "continue") break; }
  assert.equal(s, "timeout");
  assert.equal(silent.heardSpeech, false);
});
