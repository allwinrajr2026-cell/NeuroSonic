// Sprint 1 browser test of online scene description, against a server started with the MOCK provider:
//   NEUROSONIC_VISION_MOCK_SCRIPT=ok,503,503  python neurosonic_app.py --port 8799 --vision-provider mock
// Checks: opt-in on first use (no upload before consent), consent -> photo from the (fake) camera -> spoken
// "AI description: ...", question passed through, simulated 503 outage -> clear spoken fallback, walking guidance keeps
// working while the cloud fails, withdrawing consent stops uploads, history has text only, layout at iPhone size,
// no browser request leaves the laptop, no JS errors. No real cloud service is contacted.
// node tests/js/ui_vision_cdp.mjs <base-url> <chrome.exe> <fake_cam.y4m>
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, chrome, camY4m] = process.argv.slice(2);
const profile = mkdtempSync(join(tmpdir(), "ns-vision-"));
const port = 9339;
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
const initialBadge = await ev(`document.getElementById("sc-badge").textContent`);
const statusInfo = await ev(`window.neurosonic.vision`);

// 1. first use: consent requested, nothing uploaded
await tap("#sc-go");
await sleep(600);
const consentShown = await ev(`!document.getElementById("sc-consent").hidden`);
const consentSpoken = await ev(`window.__spoken.some((s) => s.includes("Tap Allow to continue"))`);
const callsBeforeConsent = describeCalls().length;

// 2. allow -> photo -> spoken AI description
await tap("#sc-allow");
const described = await waitFor(`window.__spoken.some((s) => s.startsWith("scene: AI description:"))`, 20000);
const firstCall = describeCalls()[0] || "";
const consentStored = await ev(`JSON.parse(localStorage.getItem("neurosonic.settings")).cloudConsent === true`);
const scStatus1 = await ev(`document.getElementById("sc-status").textContent`);

// 3. a question during a (simulated) 503 outage -> clear fallback; walking guidance keeps working
await tap("#a-start");
const guidanceRunning = await waitFor(`!!window.neurosonic.pathState`, 20000);
await sleep(5200);                                           // per-session rate limit is 5 s
await ev(`document.getElementById("sc-q").value = "Is there a bus stop?"; true`);
await tap("#sc-go");
const fallback = await waitFor(`window.__spoken.some((s) => s === "scene: Online scene description is unavailable right now. Local walking guidance continues.")`, 25000);
const questionCall = describeCalls().slice(-1)[0] || "";
await sleep(1500);
const guidanceStillRunning = await ev(`!!window.neurosonic.pathState && document.getElementById("a-status").textContent.indexOf("error") < 0`);
await tap("#a-stop");

// 4. withdraw consent in Settings -> no further uploads
await tap("#t-set"); await sleep(300);
await tap("#v-cloud"); await sleep(300);
const consentOff = await ev(`JSON.parse(localStorage.getItem("neurosonic.settings")).cloudConsent === false`);
await tap("#t-detect"); await sleep(300);
const callsBefore = describeCalls().length;
await tap("#sc-go"); await sleep(800);
const noUploadAfterWithdraw = describeCalls().length === callsBefore && await ev(`!document.getElementById("sc-consent").hidden`);
await tap("#sc-deny"); await sleep(300);

// 5. history: text only; layout
const hist = await ev(`fetch("/api/history?limit=50").then((r) => r.json())`);
const sceneRows = hist.history.filter((h) => h.kind === "scene");
const histJson = JSON.stringify(hist);
const layout = await ev(`({ scrollW: document.documentElement.scrollWidth, vw: document.documentElement.clientWidth })`);

const external = requests.filter((u) => !u.startsWith(base) && !u.startsWith("blob:") && !u.startsWith("data:"));
const spoken = await ev(`window.__spoken`);
console.log(JSON.stringify({ initialBadge, statusInfo: { provider: statusInfo.provider, model: statusInfo.model, configured: statusInfo.configured },
  firstCall, questionCall, scStatus1, sceneRows: sceneRows.map((r) => r.text), spoken, external, errors }, null, 1));
const checks = {
  optInRequestedBeforeAnyUpload: consentShown && consentSpoken && callsBeforeConsent === 0 && initialBadge === "needs permission",
  describedAfterConsent: described && /consent=1/.test(firstCall) && consentStored,
  questionPassedToBackend: /q=Is%20there%20a%20bus%20stop/.test(questionCall),
  outageSpokenClearly: fallback,
  walkingGuidanceIndependentOfCloud: guidanceRunning && guidanceStillRunning,
  withdrawingConsentStopsUploads: consentOff && noUploadAfterWithdraw,
  historyHasTextOnly: sceneRows.length >= 2 && !histJson.includes("/9j/") && !histJson.includes("base64"),
  noHorizontalOverflow: layout.scrollW <= layout.vw,
  noExternalRequests: external.length === 0,
  noJsErrors: errors.length === 0,
};
console.log(JSON.stringify(checks, null, 1));
ws.close(); proc.kill(); await sleep(500);
try { rmSync(profile, { recursive: true, force: true }); } catch {}
const ok = Object.values(checks).every(Boolean);
console.log(ok ? "VISION E2E: PASS" : "VISION E2E: FAIL");
process.exit(ok ? 0 : 1);
