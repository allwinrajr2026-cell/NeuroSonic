// End-to-end test of the final integration in a real headless Chrome (needs a running app on localhost):
//   * Chrome cannot resolve internet hosts; every request is recorded (must all be local).
//   * Test Voice (real tap) -> neural voice plays.
//   * Speech priority: an urgent warning interrupts a long navigation message, which is re-played afterwards.
//   * Voice command: real tap on "Speak"; Chrome's fake microphone plays a WAV of "navigate to the new bus stand";
//     the offline recogniser must set the destination and plan a route.
//   * Camera awareness: Chrome's fake camera plays a Y4M video of real frames with people. Walking Guidance (default)
//     must speak a walking-path message and no object names; after switching to Object Description a spoken
//     "Person ..." description must follow.
// node tests/js/ui_final_cdp.mjs <base-url> <chrome.exe> <fake_mic.wav> <fake_cam.y4m>
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, chrome, micWav, camY4m] = process.argv.slice(2);
const profile = mkdtempSync(join(tmpdir(), "ns-final-"));
const port = 9337;
const proc = spawn(chrome, ["--headless=new", "--disable-gpu", "--no-first-run", `--user-data-dir=${profile}`,
  `--remote-debugging-port=${port}`, "--window-size=540,1400", "--autoplay-policy=no-user-gesture-required",
  "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
  `--use-file-for-fake-audio-capture=${micWav}`, `--use-file-for-fake-video-capture=${camY4m}`,
  "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1", "--disable-background-networking",
  "--disable-component-update", "--disable-sync", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 60 && !target; i++) { try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page"); } catch { await sleep(200); } }
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map(); const errors = []; const requests = [];
ws.addEventListener("message", (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  if (msg.method === "Runtime.exceptionThrown") errors.push(msg.params.exceptionDetails.text + " " + (msg.params.exceptionDetails.exception?.description || ""));
  if (msg.method === "Network.requestWillBeSent") requests.push(msg.params.request.url);
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error("page evaluation failed: " + JSON.stringify(r.result.exceptionDetails).slice(0, 400));
  return r.result.result.value;
};
async function tap(sel) {
  const b = await ev(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); el.scrollIntoView({block: "center"});
    const r = el.getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()`);
  for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: b.x, y: b.y, button: "left", clickCount: 1 });
}
async function waitFor(expr, ms) { for (let t = 0; t < ms; t += 250) { if (await ev(expr)) return true; await sleep(250); } return false; }

await send("Runtime.enable"); await send("Page.enable"); await send("Network.enable");
await send("Page.navigate", { url: `${base}/#tab-set` });
await waitFor(`!!(window.neurosonic && document.getElementById("vc-status").textContent.indexOf("Checking") < 0)`, 15000);
await ev(`(() => { window.__spoken = []; window.__trace = []; const v = window.neurosonic.voice, prev = v.onSpeak;
  v.onSpeak = (t, c) => { window.__spoken.push(c + ": " + t); prev(t, c); };
  const pn = v._playNeural.bind(v);
  v._playNeural = (t) => { window.__trace.push("play " + t.slice(0, 50)); return pn(t).then(() => window.__trace.push("done " + t.slice(0, 30)), (e) => { window.__trace.push("ERR " + e.message + " (" + t.slice(0, 30) + ")"); throw e; }); };
  return true; })()`);
const vcStatus = await ev(`document.getElementById("vc-status").textContent`);

// 1. Test Voice
await tap("#v-test");
await waitFor(`window.__trace.some((x) => x.startsWith("done Hello. This is NeuroSonic"))`, 20000);
await waitFor(`!window.neurosonic.voice.speaking`, 15000);

// 2. priority interruption
await ev(`window.neurosonic.voice.say("Continue straight on the unnamed road for eight hundred metres, then turn left onto Gandhi Road and continue.", "navigation"); true`);
await waitFor(`window.neurosonic.voice.speaking && window.__trace.some((x) => x.startsWith("play Continue straight"))`, 10000);
await sleep(900);
await ev(`window.neurosonic.voice.say("Caution. Car ahead.", "urgent", "ahead"); true`);
await waitFor(`window.__trace.some((x) => x.startsWith("done Caution"))`, 15000);
await waitFor(`window.__trace.filter((x) => x.startsWith("done Continue straight")).length >= 1`, 20000);
const interruptTrace = await ev(`window.__trace.slice()`);

// 3. voice command through the fake microphone (a simulated position stands in for GPS)
await tap('[data-tab="tab-nav"]');
await sleep(500);
await ev(`window.neurosonic.mapView.centerOn(12.9165, 79.1325); document.getElementById("sim-here").click(); true`);
await sleep(300);
await tap("#mic");
const heard = await waitFor(`document.getElementById("mic-status").textContent.startsWith("Heard:")`, 20000);
await sleep(2500);
const micStatus = await ev(`document.getElementById("mic-status").textContent`);
const routeSummary = await ev(`document.getElementById("r-summary").textContent`);
const guidanceStartedByItself = await ev(`!!window.neurosonic.route`);

// 4. camera awareness through the fake camera
await tap('[data-tab="tab-detect"]');
await sleep(300);
await ev(`window.neurosonic.setDescribe(false, false); true`);
await tap("#a-start");
const sawPath = await waitFor(`window.__spoken.some((s) => /^(urgent|obstacle|system|info): (Stop\\. The walking path|Caution\\. An object is detected|The visible path appears clear|I cannot clearly assess)/.test(s))`, 25000);
const pathState = await ev(`window.neurosonic.pathState`);
const namesInGuidance = await ev(`window.__spoken.filter((s) => /^(description|obstacle|urgent): (Person|Bicycle|\\d+ people)/.test(s))`);
await tap("#od-desc");
const sawPerson = await waitFor(`window.__spoken.some((s) => /^description: (Person|\\d+ people)/.test(s))`, 25000);
const aStatus = await ev(`document.getElementById("a-status").textContent`);
const aDets = await ev(`document.getElementById("a-dets").textContent`);
await tap("#a-stop");
await sleep(500);

const spoken = await ev(`window.__spoken`);
const external = requests.filter((u) => !u.startsWith(base) && !u.startsWith("blob:") && !u.startsWith("data:"));
const interrupted = interruptTrace.some((x) => x.startsWith("ERR interrupted (Continue straight"));
const urgentIdx = interruptTrace.findIndex((x) => x.startsWith("done Caution"));
const replayIdx = interruptTrace.findIndex((x, i) => i > urgentIdx && x.startsWith("done Continue straight"));
console.log(JSON.stringify({ vcStatus, interruptTrace, micStatus, routeSummary, pathState, aStatus, aDets, spoken, requests: requests.length, external, errors }, null, 1));
const checks = {
  testVoicePlayed: interruptTrace.some((x) => x.startsWith("done Hello. This is NeuroSonic")),
  urgentInterruptedNavigation: interrupted && urgentIdx > 0,
  navigationReplayedAfterUrgent: replayIdx > urgentIdx,
  voiceCommandHeard: heard && /navigate/.test(micStatus),
  destinationAnnouncedByVoice: spoken.some((s) => s.startsWith("navigation: Destination: ")),
  routePlannedByVoice: spoken.some((s) => s.startsWith("navigation: Route to")),
  waitsForStartNavigation: !guidanceStartedByItself && spoken.some((s) => s.includes("Say start navigation to begin")),
  walkingGuidanceSpokePathState: sawPath && !!pathState,
  walkingGuidanceSpokeNoObjectNames: namesInGuidance.length === 0,
  objectDescriptionSpokePerson: sawPerson,
  noExternalRequests: external.length === 0,
  noJsErrors: errors.length === 0,
};
console.log(JSON.stringify(checks, null, 1));
console.log("spoken destination recognised correctly (Katpadi Junction):", spoken.some((s) => s.startsWith("navigation: Destination: Katpadi Junction")));
ws.close(); proc.kill(); await sleep(500);
try { rmSync(profile, { recursive: true, force: true }); } catch {}
const ok = Object.values(checks).every(Boolean);
console.log(ok ? "FINAL E2E: PASS" : "FINAL E2E: FAIL");
process.exit(ok ? 0 : 1);
