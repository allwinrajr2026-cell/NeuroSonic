// Browser test of the live perception pipeline (RF-DETR -> tracking -> events -> speech), run against the app started
// from .venv-gpu. Chrome's fake camera plays tools/make_event_clip.py's clip (a real recorded person composited over a
// real recorded empty scene, walking left -> right; camera still). Records detector, frame interval, achieved fps,
// camera->answer latency, event->speech delay, screenshots. It is not field evidence.
// node tests/js/ui_events_cdp.mjs <base-url> <chrome.exe> <event_cam.y4m> [screenshot-dir]
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, chrome, camY4m, shotDir] = process.argv.slice(2);
const profile = mkdtempSync(join(tmpdir(), "ns-events-"));
const port = 9341;
const proc = spawn(chrome, ["--headless=new", "--disable-gpu", "--no-first-run", `--user-data-dir=${profile}`,
  `--remote-debugging-port=${port}`, "--autoplay-policy=no-user-gesture-required",
  "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-video-capture=${camY4m}`,
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
  for (const type of ["touchStart", "touchEnd"]) await send("Input.dispatchTouchEvent", { type, touchPoints: type === "touchEnd" ? [] : [{ x: b.x, y: b.y }] });
}
async function waitFor(expr, ms) { for (let t = 0; t < ms; t += 250) { if (await ev(expr)) return true; await sleep(250); } return false; }
async function shot(name) {
  if (!shotDir) return;
  const r = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(shotDir, name + ".png"), Buffer.from(r.result.data, "base64"));
}
await send("Runtime.enable"); await send("Page.enable"); await send("Network.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 440, height: 956, deviceScaleFactor: 2, mobile: true });
await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
await send("Page.navigate", { url: `${base}/` });
await waitFor(`!!(window.neurosonic && window.neurosonic.awarenessInfo)`, 30000);
await ev(`(() => { window.__spoken = []; window.__speechStart = [];
  const v = window.neurosonic.voice, prev = v.onSpeak, prevSt = v.onStatus;
  v.onSpeak = (t, c) => { window.__spoken.push({ t: performance.now(), c, text: t }); prev(t, c); };
  v.onStatus = (st) => { if (st.speaking && st.text) window.__speechStart.push({ t: performance.now(), text: st.text, engine: st.engine }); prevSt(st); };
  return true; })()`);
const info = await ev(`window.neurosonic.awarenessInfo`);
const frames = () => requests.filter((u) => u.includes("/api/awareness/frame")).length;
await tap("#a-start");
await waitFor(`!!window.neurosonic.pathState`, 30000);
const f0 = frames(), t0 = Date.now();
const sawEvent = await waitFor(`window.__spoken.some((s) => /is moving into your path|is crossing in front of you/.test(s.text))`, 40000);
await sleep(400);
await shot("live_event_alert");
await sleep(Number(process.env.HOLD_MS || 6000));   // keep the camera running (HOLD_MS for resource measurements)
const fps = (frames() - f0) / ((Date.now() - t0) / 1000);
await shot("live_detection_overlay");
const latency = await ev(`window.neurosonic.awarenessLatency`);
const spoken = await ev(`window.__spoken`);
const starts = await ev(`window.__speechStart`);
const aStatus = await ev(`document.getElementById("a-status").textContent`);
await tap("#a-stop");
const evSpoken = spoken.find((s) => /is moving into your path|is crossing in front of you/.test(s.text));
const evStart = evSpoken && starts.find((s) => s.text === evSpoken.text && s.t >= evSpoken.t);
const sorted = [...latency].sort((a, b) => a - b), pct = (p) => sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
const external = requests.filter((u) => !u.startsWith(base) && !u.startsWith("blob:") && !u.startsWith("data:"));
const result = { detector: info.detector, recommended_frame_ms: info.recommended_frame_ms, achieved_fps: +fps.toFixed(2),
  latency_ms: { n: latency.length, median: pct(0.5), p90: pct(0.9), max: sorted[sorted.length - 1] },
  event: evSpoken ? evSpoken.text : null, event_to_speech_start_ms: evStart ? Math.round(evStart.t - evSpoken.t) : null,
  speech_engine: evStart ? evStart.engine : null, aStatus, spoken: spoken.map((s) => `${s.c}: ${s.text}`), external, errors };
console.log(JSON.stringify(result, null, 1));
const checks = {
  rfdetrOnGpu: info.detector.name === "rf-detr-nano" && info.detector.device === "cuda",
  frameInterval200ms: info.recommended_frame_ms === 200,
  eventSpoken: sawEvent,
  eventAudioStarted: !!evStart,
  noExternalRequests: external.length === 0,
  noJsErrors: errors.length === 0,
};
console.log(JSON.stringify(checks, null, 1));
ws.close(); proc.kill(); await sleep(500);
try { rmSync(profile, { recursive: true, force: true }); } catch {}
const ok = Object.values(checks).every(Boolean);
console.log(ok ? "EVENTS E2E: PASS" : "EVENTS E2E: FAIL");
process.exit(ok ? 0 : 1);
