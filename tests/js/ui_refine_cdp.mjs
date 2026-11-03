// Real-browser check of the refined interface at iPhone 17 Pro Max size (440 x 956 CSS px, DPR 3, touch, iOS UA)
// in headless Chrome. This is Chrome's mobile emulation, NOT Safari on a real iPhone (WebKit differences remain).
//   * every screen: no horizontal overflow, touch targets >= 40 px, content not hidden under the fixed bars
//   * How It Works: 10 topics + architecture diagram
//   * GPS through CDP geolocation emulation: good fix, inaccurate fix (guidance not used), permission denied
//   * map canvas: sized correctly, re-measured after rotation to landscape (no distortion)
//   * simulated route: search -> preview -> start -> spoken instruction; offline (no external requests)
// node tests/js/ui_refine_cdp.mjs <base-url> <chrome.exe> [screenshot-dir]
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, chrome, shotDir] = process.argv.slice(2);
const profile = mkdtempSync(join(tmpdir(), "ns-refine-"));
const port = 9338;
const proc = spawn(chrome, ["--headless=new", "--disable-gpu", "--no-first-run", `--user-data-dir=${profile}`,
  `--remote-debugging-port=${port}`, "--autoplay-policy=no-user-gesture-required",
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
const IPHONE = { width: 440, height: 956, deviceScaleFactor: 3, mobile: true };
const UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1";

await send("Runtime.enable"); await send("Page.enable"); await send("Network.enable");
await send("Emulation.setDeviceMetricsOverride", IPHONE);
await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
await send("Emulation.setUserAgentOverride", { userAgent: UA, platform: "iPhone" });
await send("Browser.grantPermissions", { origin: base, permissions: ["geolocation"] });
await send("Emulation.setGeolocationOverride", { latitude: 12.9249, longitude: 79.1353, accuracy: 8 });
await send("Page.navigate", { url: `${base}/` });
await waitFor(`!!(window.neurosonic && document.getElementById("off-list").children.length && document.getElementById("m-info").textContent.indexOf("Loading") < 0)`, 20000);
await ev(`(() => { window.__spoken = []; const v = window.neurosonic.voice, prev = v.onSpeak;
  v.onSpeak = (t, c) => { window.__spoken.push(c + ": " + t); prev(t, c); }; return true; })()`);

// 1. layout of every screen
const LAYOUT = `(() => {
  const vw = document.documentElement.clientWidth, sec = document.querySelector(".tab.active");
  sec.querySelectorAll("details").forEach((d) => { d.open = true; });
  const over = [...sec.querySelectorAll("*")].filter((e) => { const r = e.getBoundingClientRect(); return r.width && (r.right > vw + 1 || r.left < -1); })
    .map((e) => e.tagName + "#" + (e.id || e.className)).slice(0, 5);
  // a checkbox's touch target is its enclosing <label> (tapping the label toggles it)
  const small = [...sec.querySelectorAll("button, select, input[type=checkbox], summary")].filter((e) => {
    const t = e.type === "checkbox" && e.closest("label") ? e.closest("label") : e;
    const r = t.getBoundingClientRect(); return r.width && (r.height < 40 || r.width < 40); }).map((e) => e.id || e.textContent.trim().slice(0, 20));
  const bars = document.querySelector(".tabs").getBoundingClientRect().height + document.querySelector(".micstatus").getBoundingClientRect().height;
  const pad = parseFloat(getComputedStyle(document.body).paddingBottom);
  window.scrollTo(0, 0);
  const alertBottom = document.querySelector(".alert").getBoundingClientRect().bottom;
  const firstTop = sec.firstElementChild.getBoundingClientRect().top;
  window.scrollTo(0, document.body.scrollHeight);
  const last = [...sec.children].filter((e) => e.getBoundingClientRect().height).pop().getBoundingClientRect();
  const lastVisible = last.bottom <= document.querySelector(".micstatus").getBoundingClientRect().top + 1;
  window.scrollTo(0, 0);
  return { scrollW: document.documentElement.scrollWidth, vw, over, small, padOk: pad >= bars, alertBottom, firstTop, lastVisible };
})()`;
const layout = {};
for (const tab of ["tab-detect", "tab-nav", "tab-hist", "tab-set", "tab-how", "tab-sim"]) {
  await ev(`window.neurosonic.showTab(${JSON.stringify(tab)}); true`);
  await sleep(500);
  await shot(tab + "-top");
  layout[tab] = await ev(LAYOUT);
  await sleep(200);
  await shot(tab + "-open");
  await ev(`document.querySelectorAll(".tab.active details").forEach((d, i) => { d.open = (i === 0 && d.closest("#tab-how") !== null); }); true`);
}
const howTopics = await ev(`[...document.querySelectorAll("#tab-how summary")].map((s) => s.textContent.trim().slice(0, 3))`);
const howDiagram = await ev(`[...document.querySelectorAll("#tab-how .fbox")].map((b) => b.textContent.trim())`);

// 2. tab bar: real taps switch screens
await tap('[data-tab="tab-how"]'); await sleep(300);
const howActive = await ev(`document.getElementById("tab-how").classList.contains("active") && document.getElementById("t-how").getAttribute("aria-current") === "page"`);
await tap('[data-tab="tab-nav"]'); await sleep(700);

// 3. map canvas size + rotation
const mapPortrait = await ev(`(() => { const c = document.getElementById("m-canvas"), r = c.getBoundingClientRect(); return { cssW: r.width, cssH: r.height, w: c.width, h: c.height }; })()`);
await send("Emulation.setDeviceMetricsOverride", { width: 956, height: 440, deviceScaleFactor: 3, mobile: true });
await sleep(800);
const mapLandscape = await ev(`(() => { const c = document.getElementById("m-canvas"), r = c.getBoundingClientRect(); return { cssW: r.width, cssH: r.height, w: c.width, h: c.height, scrollW: document.documentElement.scrollWidth, vw: document.documentElement.clientWidth }; })()`);
await shot("tab-nav-landscape");
await send("Emulation.setDeviceMetricsOverride", IPHONE);
await sleep(800);

// 4. GPS: good fix, then inaccurate, then denied
await tap("#g-start");
const gpsGood = await waitFor(`document.getElementById("g-badge").textContent === "good"`, 10000);
const gpsAcc = await ev(`document.getElementById("g-acc").textContent`);
const mapCentredOnUser = await ev(`Math.abs(window.neurosonic.mapView.center.lat - 12.9249) < 0.001`);
await shot("tab-nav-gps");
await send("Emulation.setGeolocationOverride", { latitude: 12.9250, longitude: 79.1354, accuracy: 300 });
const gpsInaccurate = await waitFor(`document.getElementById("g-badge").textContent === "inaccurate"`, 10000);
const inaccurateStatus = await ev(`document.getElementById("g-status").textContent`);
await tap("#g-stop");
await send("Browser.setPermission", { origin: base, permission: { name: "geolocation" }, setting: "denied" });
await tap("#g-start");
const gpsDenied = await waitFor(`document.getElementById("g-badge").textContent === "denied"`, 10000);
const deniedSpoken = await ev(`window.__spoken.some((s) => s.startsWith("system: Location permission denied"))`);
await send("Browser.setPermission", { origin: base, permission: { name: "geolocation" }, setting: "granted" });
await send("Emulation.setGeolocationOverride", { latitude: 12.9249, longitude: 79.1353, accuracy: 8 });

// 5. simulated route: search, preview, start, walk
await ev(`window.neurosonic.mapView.centerOn(12.9720, 79.1370); document.getElementById("sim-here").click(); true`);
await sleep(300);
await ev(`document.getElementById("s-q").value = "CMC Hospital"; true`);
await tap("#s-go");
await waitFor(`document.querySelector("#s-results button") !== null`, 8000);
await tap("#s-results button");
const previewed = await waitFor(`/kilometres|metres/.test(document.getElementById("r-summary").textContent)`, 10000);
await tap("#rt-start");
await waitFor(`!!window.neurosonic.route`, 8000);
for (let i = 0; i < 12; i++) { await ev(`document.getElementById("sim-step").click(); true`); await sleep(120); }
const rtNow = await ev(`document.getElementById("rt-now").textContent`);
const routeSpoken = await ev(`window.__spoken.filter((s) => s.startsWith("navigation: ")).slice(-6)`);
await shot("tab-nav-route");
await tap("#rt-stop");

// 6. object description switch on Home + settings checkbox stay in sync
await tap('[data-tab="tab-detect"]'); await sleep(300);
await tap("#od-desc"); await sleep(200);
const descSynced = await ev(`document.getElementById("v-describe").checked && window.neurosonic.settings.describe === true && document.getElementById("od-desc").getAttribute("aria-checked") === "true"`);
await tap("#od-walk"); await sleep(200);
const walkSynced = await ev(`!document.getElementById("v-describe").checked && window.neurosonic.settings.describe === false`);

const external = requests.filter((u) => !u.startsWith(base) && !u.startsWith("blob:") && !u.startsWith("data:"));
console.log(JSON.stringify({ layout, howTopics, howDiagram, mapPortrait, mapLandscape, gpsAcc, inaccurateStatus, rtNow, routeSpoken, external, errors }, null, 1));
const layoutOk = Object.values(layout).every((l) => l.scrollW <= l.vw && l.over.length === 0 && l.small.length === 0 && l.padOk && l.lastVisible && l.firstTop >= l.alertBottom - 1);
const checks = {
  noHorizontalOverflowOrTinyTargetsOnAnyScreen: layoutOk,
  howItWorksTenTopicsAndDiagram: howTopics.length === 11 && howTopics[9].startsWith("10") && howTopics[10].startsWith("11") && howDiagram.length === 5,
  tabBarSwitchesScreens: howActive,
  mapCanvasSizedForDpr: mapPortrait.cssW > 300 && mapPortrait.w === Math.round(mapPortrait.cssW * 3) && mapPortrait.h === Math.round(mapPortrait.cssH * 3),
  mapResizedOnRotation: mapLandscape.w === Math.round(mapLandscape.cssW * 3) && mapLandscape.cssW > mapPortrait.cssW && mapLandscape.scrollW <= mapLandscape.vw,
  gpsGoodFix: gpsGood && gpsAcc === "± 8 m" && mapCentredOnUser,
  gpsInaccurateFixNotUsed: gpsInaccurate && /Guidance paused/.test(inaccurateStatus),
  gpsPermissionDeniedHandled: gpsDenied && deniedSpoken,
  routePreviewStartAndSpokenSteps: previewed && rtNow.length > 3 && routeSpoken.some((s) => /Starting guidance|In about|Turn|Continue|Bear|Head/.test(s)),
  describeSwitchInSync: descSynced && walkSynced,
  noExternalRequests: external.length === 0,
  noJsErrors: errors.length === 0,
};
console.log(JSON.stringify(checks, null, 1));
ws.close(); proc.kill(); await sleep(500);
try { rmSync(profile, { recursive: true, force: true }); } catch {}
const ok = Object.values(checks).every(Boolean);
console.log(ok ? "REFINE UI E2E: PASS" : "REFINE UI E2E: FAIL");
process.exit(ok ? 0 : 1);
