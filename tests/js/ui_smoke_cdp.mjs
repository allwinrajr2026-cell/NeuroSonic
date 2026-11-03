// Manual UI smoke test (not part of the unit-test run): drives a real headless Chrome over the DevTools
// protocol using Node's built-in WebSocket, with Chrome's fake camera. Requires a running app.
//   node tests/js/ui_smoke_cdp.mjs http://127.0.0.1:8799 "C:/Program Files/Google/Chrome/Application/chrome.exe"
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base = "http://127.0.0.1:8765", chrome = "C:/Program Files/Google/Chrome/Application/chrome.exe"] = process.argv.slice(2);
const profile = mkdtempSync(join(tmpdir(), "ns-cdp-"));
const port = 9333;
const proc = spawn(chrome, ["--headless=new", "--disable-gpu", "--no-first-run", `--user-data-dir=${profile}`,
  `--remote-debugging-port=${port}`, "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
  "--window-size=540,1000", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let target;
for (let i = 0; i < 50 && !target; i++) {
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page"); }
  catch { await sleep(200); }
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map(); const consoleErrors = [];
ws.addEventListener("message", (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  if (msg.method === "Runtime.exceptionThrown") consoleErrors.push(msg.params.exceptionDetails.text + " " + (msg.params.exceptionDetails.exception?.description || ""));
  if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") consoleErrors.push(msg.params.args.map((a) => a.value).join(" "));
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result.result.value;

await send("Runtime.enable");
await send("Page.enable");
await send("Page.navigate", { url: `${base}/?autostart=eventsim` });
await sleep(6000);
const sim = await evaluate(`(() => {
  const c = document.getElementById("s-canvas").getContext("2d").getImageData(0, 0, 160, 120).data;
  let ev = 0; for (let i = 0; i < c.length; i += 4) if (c[i] || c[i + 1]) ev++;
  return { status: document.getElementById("s-status").textContent, eventPixels: ev,
           meters: [0, 1, 2].map((k) => +document.getElementById("m-" + k).value.toFixed(3)),
           alert: document.getElementById("alert").textContent };
})()`);
// navigation maths in the page context + tab switching + layout width
const page = await evaluate(`(() => {
  document.querySelector('[data-tab="tab-nav"]').click();
  document.getElementById("p-coords").value = "51.5007, -0.1246";
  return { navVisible: document.getElementById("tab-nav").classList.contains("active"),
           overflowX: document.documentElement.scrollWidth > window.innerWidth,
           width: window.innerWidth, secure: window.isSecureContext,
           badges: [...document.querySelectorAll(".badge")].map((b) => b.textContent) };
})()`);
console.log(JSON.stringify({ sim, page, consoleErrors }, null, 1));
ws.close(); proc.kill();
await sleep(500);
try { rmSync(profile, { recursive: true, force: true }); } catch {}
const ok = sim.eventPixels > 0 && sim.status.startsWith("Camera on") && page.navVisible && !page.overflowX && consoleErrors.length === 0;
console.log(ok ? "UI SMOKE TEST: PASS" : "UI SMOKE TEST: FAIL");
process.exit(ok ? 0 : 1);
