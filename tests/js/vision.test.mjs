// Sprint 1: speech handling of online scene descriptions ("scene" category). Node's built-in runner.
import { test } from "node:test";
import assert from "node:assert/strict";
import { COOLDOWN_MS, INTERRUPTING, MAX_AGE_MS, PRIORITY, SpeechQueue } from "../../web/js/speech.js";

test("scene descriptions: below walking warnings, never interrupting, re-queued once after a Stop", () => {
  assert.ok(PRIORITY.scene < PRIORITY.obstacle && PRIORITY.scene < PRIORITY.urgent);
  assert.ok(!INTERRUPTING.scene);
  const q = new SpeechQueue();
  const playing = { text: "AI description: a street with parked cars.", category: "scene", priority: PRIORITY.scene };
  assert.equal(q.shouldInterrupt(playing, "urgent"), true);                 // "Stop. The walking path…" cuts in
  assert.equal(q.shouldInterrupt(playing, "obstacle"), true);
  assert.equal(q.shouldInterrupt(playing, "navigation"), false);
  assert.equal(q.requeue(playing), true);                                    // the description is repeated afterwards
  assert.equal(q.requeue(Object.assign({}, playing, { requeued: true })), false);
});

test("scene descriptions: urgent first, late answers kept for 30 s, then dropped", () => {
  const q = new SpeechQueue();
  q.push("AI description: a bus stop on the left.", "scene", 0);
  q.push("Stop. The walking path may be blocked.", "urgent", 10);
  assert.equal(q.next(20).category, "urgent");
  assert.equal(q.next(25).category, "scene");
  assert.equal(MAX_AGE_MS.scene, 30000);
  q.push("AI description: old answer.", "scene", 0);
  assert.equal(q.next(31000), null);
});

test("scene descriptions: the same answer may be asked for again after a short cooldown", () => {
  const q = new SpeechQueue();
  assert.ok(q.push("Looking.", "scene", 0)); q.next(0);
  assert.equal(q.push("Looking.", "scene", 1000), false);
  assert.ok(q.push("Looking.", "scene", COOLDOWN_MS.scene + 1));
});
