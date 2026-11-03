// Browser test: a SLOW cloud reply must not interrupt local walking guidance. Server with the mock provider:
//   NEUROSONIC_VISION_MOCK_SCRIPT=slow20  python neurosonic_app.py --port 8799 --vision-provider mock
// Checks: "Still waiting for the online description…" after ~15 s, the description after ~20 s, and during the
// whole wait camera frames keep being analysed (walking-guidance path state stays available, no camera-unavailable),
// no external requests, no JS errors. No real cloud service is contacted.
// node tests/js/ui_vision_slow_cdp.mjs <base-url> <chrome.exe> <fake_cam.y4m>
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, chrome, camY4m] = process.argv.slice(2);
const profile = mkdtempSync(join(tmpdir(), "ns-vision-slow-"));
const port = 9340;
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
const describeCalls = () => requests.filter((u) => u.includes("/api/vision/describe"));

await send("Runtime.enable"); await send("Page.enable"); await send("Network.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 440, height: 956, deviceScaleFactor: 3, mobile: true });
await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
await send("Page.navigate", { url: `${base}/` });
await waitFor(`!!(window.neurosonic && window.neurosonic.vision && document.getElementById("sc-badge").textContent !== "checking")`, 20000);
await ev(`(() => { window.__spoken = []; const v = window.neurosonic.voice, prev = v.onSpeak;
  v.onSpeak = (t, c) => { window.__spoken.push(c + ": " + t); prev(t, c); }; return true; })()`);
const frames = () => requests.filter((u) => u.includes("/api/awareness/frame")).length;
await ev(`window.neurosonic.setCloudConsent(true, false); true`);
await tap("#a-start");
const guidanceUp = await waitFor(`!!window.neurosonic.pathState`, 20000);
const f0 = frames();
const t0 = Date.now();
await tap("#sc-go");
const stillWaiting = await waitFor(`window.__spoken.some((s) => s === "scene: Still waiting for the online description. Local walking guidance continues.")`, 25000);
const tWaiting = (Date.now() - t0) / 1000;
const described = await waitFor(`window.__spoken.some((s) => s.startsWith("scene: AI description:"))`, 30000);
const tDescribed = (Date.now() - t0) / 1000;
const framesDuringWait = frames() - f0;
const stateAfter = await ev(`window.neurosonic.pathState`);
const spoken = await ev(`window.__spoken`);
const pathMessagesDuringWait = spoken.slice(spoken.indexOf("scene: Looking.")).filter((s) => /^(urgent|obstacle|info|system): (Stop|Caution|The visible path|I cannot)/.test(s));
await tap("#a-stop");
const external = requests.filter((u) => !u.startsWith(base) && !u.startsWith("blob:") && !u.startsWith("data:"));
console.log(JSON.stringify({ tWaiting, tDescribed, framesDuringWait, stateAfter, pathMessagesDuringWait, spoken, external, errors }, null, 1));
const checks = {
  walkingGuidanceRunning: guidanceUp,
  stillWaitingAnnouncedAround15s: stillWaiting && tWaiting >= 14 && tWaiting < 19,
  slowDescriptionStillDelivered: described && tDescribed >= 19,
  framesKeptFlowingDuringWait: framesDuringWait >= 2 * tDescribed,          // >= 2 analysed frames per second
  guidanceNotMarkedUnavailable: stateAfter !== null && stateAfter !== "CAMERA_UNAVAILABLE",
  noExternalRequests: external.length === 0,
  noJsErrors: errors.length === 0,
};
console.log(JSON.stringify(checks, null, 1));
ws.close(); proc.kill(); await sleep(500);
try { rmSync(profile, { recursive: true, force: true }); } catch {}
const ok = Object.values(checks).every(Boolean);
console.log(ok ? "VISION SLOW E2E: PASS" : "VISION SLOW E2E: FAIL");
process.exit(ok ? 0 : 1);
