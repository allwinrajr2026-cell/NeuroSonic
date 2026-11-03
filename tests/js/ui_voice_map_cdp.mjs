// Manual end-to-end test (needs a running app): real headless Chrome over the DevTools protocol.
//  * Chrome cannot resolve any internet host (--host-resolver-rules), and every request is recorded:
//    the test fails if the page requests anything other than the local app.
//  * "Test Voice" is pressed with a synthetic mouse click (a real user gesture), then we check that the neural
//    (Piper) audio element actually played to the end and that the server received the playback report.
//  * Navigate: offline map loads, search "CMC Hospital", simulated start at Katpadi, start guidance, walk the route
//    in 20 m simulated steps until arrival; all spoken texts are recorded.
//   node tests/js/ui_voice_map_cdp.mjs http://127.0.0.1:8793 "C:/Program Files/Google/Chrome/Application/chrome.exe" out.png
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, chrome, shot] = process.argv.slice(2);
const host = new URL(base).host;
const profile = mkdtempSync(join(tmpdir(), "ns-cdp2-"));
const port = 9334;
const proc = spawn(chrome, ["--headless=new", "--disable-gpu", "--no-first-run", `--user-data-dir=${profile}`,
  `--remote-debugging-port=${port}`, "--window-size=540,1400",
  "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1", "--disable-background-networking",
  "--disable-component-update", "--disable-sync", "--no-default-browser-check", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 60 && !target; i++) {
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page"); } catch { await sleep(200); }
}
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
  if (r.result.exceptionDetails) throw new Error("page evaluation failed: " + JSON.stringify(r.result.exceptionDetails).slice(0, 500));
  return r.result.result.value;
};
async function tap(selector) {   // real pointer click via CDP = trusted user gesture
  const box = await ev(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); el.scrollIntoView({block: "center"});
    const r = el.getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()`);
  for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: box.x, y: box.y, button: "left", clickCount: 1 });
}

await send("Runtime.enable"); await send("Page.enable"); await send("Network.enable");
await send("Page.navigate", { url: `${base}/#tab-set` });
for (let i = 0; i < 60; i++) {   // wait until the app has initialised
  await sleep(250);
  const ready = await ev(`!!(window.neurosonic && document.getElementById("v-engine-status").textContent.indexOf("Checking") < 0)`).catch(() => false);
  if (ready) break;
}
await ev(`(() => { window.__spoken = []; window.__trace = []; const v = window.neurosonic.voice, prev = v.onSpeak;
  v.onSpeak = (t, c) => { window.__spoken.push(t); prev(t, c); };
  const pn = v._playNeural.bind(v);
  v._playNeural = (t) => { window.__trace.push("play " + t.slice(0, 40)); return pn(t).then(() => window.__trace.push("done"), (e) => { window.__trace.push("ERR " + e.message); throw e; }); };
  return true; })()`);

// ---- 1. voice
const engineStatus = await ev(`document.getElementById("v-engine-status").textContent`);
await tap("#v-test");
let voice = null;
for (let i = 0; i < 40; i++) {
  await sleep(500);
  voice = await ev(`(() => { const v = window.neurosonic.voice, a = v.audio;
    return { lastOk: v.status.lastOk, lastError: v.status.lastError, speaking: v.status.speaking,
             played: a.played.length ? a.played.end(a.played.length - 1) : 0, duration: a.duration, ended: a.ended,
             badge: document.getElementById("b-voice").textContent }; })()`);
  if (!voice.speaking && (voice.lastOk || voice.lastError) && voice.ended) break;
}
const reports = await (await fetch(`${base}/api/voice/reports`)).json();

// ---- 2. navigation (offline map + route + guidance with simulated walking)
await tap('[data-tab="tab-nav"]');
await sleep(1500);
const mapLoaded = await ev(`!!window.neurosonic.mapView.data && document.getElementById("m-info").textContent`);
await ev(`document.getElementById("s-q").value = "CMC Hospital"; document.getElementById("s-go").click(); true`);
await sleep(800);
const firstResult = await ev(`document.querySelector("#s-results button") && document.querySelector("#s-results button").textContent`);
await ev(`document.querySelector("#s-results button").click(); true`);
await ev(`window.neurosonic.mapView.centerOn(12.9690, 79.1356); document.getElementById("sim-here").click(); true`);   // Katpadi
await tap("#rt-start");
await sleep(1500);
const summary = await ev(`document.getElementById("r-summary").textContent`);
let steps = 0, arrived = false;
for (; steps < 400 && !arrived; steps++) {
  await ev(`document.getElementById("sim-step").click(); true`);
  await sleep(15);
  arrived = await ev(`document.getElementById("r-summary").textContent.startsWith("Arrived")`);
}
await sleep(500);
await sleep(20000);   // let queued speech finish
const spoken = await ev(`window.__spoken`);
const trace = await ev(`window.__trace`);
const finalVoice = await ev(`JSON.stringify(window.neurosonic.voice.status)`);
const allReports = (await (await fetch(`${base}/api/voice/reports`)).json()).reports;
if (shot) {
  await ev(`window.neurosonic.mapView.setRoute(window.neurosonic.mapView.route); document.getElementById("m-canvas").scrollIntoView(); true`);
  const img = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(shot, Buffer.from(img.result.data, "base64"));
}
const external = requests.filter((u) => !u.startsWith(base) && !u.startsWith("blob:") && !u.startsWith("data:"));
console.log(JSON.stringify({ engineStatus, voice, lastReport: reports.reports[reports.reports.length - 1], mapLoaded,
  firstResult, summary, simulatedSteps: steps, arrived, spoken, trace, finalVoice,
  neuralPlaysOk: allReports.filter((r) => r.engine === "neural" && r.ok === "True").map((r) => r.text),
  requests: requests.length, external, errors }, null, 1));
ws.close(); proc.kill(); await sleep(500);
try { rmSync(profile, { recursive: true, force: true }); } catch {}
const navPlayed = allReports.filter((r) => r.engine === "neural" && r.ok === "True" && /^(Starting guidance|Turn|In about|Continue|You have arrived)/.test(r.text)).length;
console.log("neural navigation instructions actually played:", navPlayed);
const testPlayed = allReports.some((r) => r.engine === "neural" && r.ok === "True" && r.text === "Hello. This is NeuroSonic. Your voice assistant is working correctly.");
console.log("Test Voice sentence played with the neural voice:", testPlayed);
const ok = testPlayed && voice.lastOk && voice.lastOk.startsWith("Neural voice") && voice.ended && voice.played > 3 && !!mapLoaded && arrived && navPlayed >= 2 &&
  external.length === 0 && errors.length === 0;
console.log(ok ? "VOICE+MAP E2E: PASS" : "VOICE+MAP E2E: FAIL");
process.exit(ok ? 0 : 1);
