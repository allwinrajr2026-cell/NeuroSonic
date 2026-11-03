import { Announcer, TEST_SENTENCE } from "./speech.js";
import { assessFix, bearingDeg, canReroute, compass, distanceM, followRoute, formatDistance, gpsWatch, guidance, osmWalkingUrl, parseCoords, pointAtAlong, prepareRoute, projectOnPolyline } from "./nav.js";
import { MotionAlerter, diffEvents, paintEvents, toGray } from "./eventsim.js";
import { MapView } from "./mapview.js";
import { recordUtterance } from "./recorder.js";

const $ = (id) => document.getElementById(id);
const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ settings + voice
// describe=false: Walking Guidance (path states only); describe=true: Object Description (adds object names)
// cloudConsent=false: no camera photo is ever sent to the online scene-description service until the user allows it
const DEFAULTS = { speech: true, beeps: true, engine: "neural", voice: "", rate: 1.0, volume: 1, mode: "chest", describe: false, cloudConsent: false };
const settings = { ...DEFAULTS, ...JSON.parse(localStorage.getItem("neurosonic.settings") || "{}") };
const saveSettings = () => localStorage.setItem("neurosonic.settings", JSON.stringify(settings));
const voice = new Announcer(settings);

function showAlert(text, category) {
  const el = $("alert");
  el.textContent = text;
  el.className = "alert " + (category || "");
}
let lastNavText = null;   // for "repeat instruction"
voice.onSpeak = (t, c) => {
  if (c === "navigation") { lastNavText = t; $("rt-now").textContent = t; }
  showAlert(t, c);
};

function badge(id, text, cls) { const b = $(id); b.textContent = text; b.className = "badge " + (cls || ""); }
function pill(id, text, cls) { const b = $(id); b.textContent = text; b.className = "pill " + (cls || ""); }

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = res.status === 204 ? null : await res.json();
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}
const logClientAlert = (source, kind, text, position) =>
  api("/api/alerts", { source, kind, text, position }).catch(() => {});

// ------------------------------------------------------------------ screens
function showTab(id) {
  const sec = $(id);
  if (!sec || !sec.classList.contains("tab")) return;
  document.querySelectorAll(".tabs button[data-tab]").forEach((x) => {
    if (x.dataset.tab === id) x.setAttribute("aria-current", "page"); else x.removeAttribute("aria-current");
  });
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === id));
  window.scrollTo(0, 0);
  if (id === "tab-hist") loadHistory();
  if (id === "tab-nav") requestAnimationFrame(() => mapView.shown());
  if (id === "tab-set") { checkPermissions(); renderOffline(); }
}
document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
  showTab(b.dataset.tab);
  history.replaceState(null, "", "#" + b.dataset.tab);
}));

// ------------------------------------------------------------------ server / network status
const status = { server: null, tts: null, vc: null, aw: null, map: null, vision: null };
function updateNet() { badge("b-net", navigator.onLine ? "Online" : "No internet (OK)", navigator.onLine ? "" : "ok"); renderOffline(); }
addEventListener("online", updateNet); addEventListener("offline", updateNet);

let lastEventId = 0, serverDown = false;
async function init() {
  try {
    const s = await api("/api/status");
    status.server = true;
    badge("b-det", "Laptop ✓", "ok");
    lastEventId = s.last_event_id;
    $("r-set").innerHTML = s.replay_sets.map((r) =>
      `<option value="${r.name}" title="${escapeHtml(r.description)}" ${r.available ? "" : "disabled"}>${r.name}${r.available ? "" : " (missing)"}</option>`).join("");
    const desc = () => { const o = $("r-set").selectedOptions[0]; $("r-desc").textContent = o ? o.title : ""; };
    $("r-set").onchange = desc; desc();
    $("about-model").textContent = `WOAD exp72 · classes ${s.model.names.join(", ")} · ${s.model.num_params.toLocaleString()} parameters · ` +
      `checkpoint ${s.model.sha256.slice(0, 12)}… · ${s.model.device}`;
    if (s.replay.running) pollReplay();
  } catch (e) {
    status.server = false;
    badge("b-det", "Laptop ✕", "bad");
    showAlert("Laptop server not reachable. Detection, voice commands and routing are unavailable.", "system");
  }
  renderOffline();
}

// Poll alert events from the server (WOAD replay + upload) and announce them.
async function pollEvents() {
  try {
    const r = await api(`/api/events?since=${lastEventId}`);
    if (serverDown) { serverDown = false; status.server = true; badge("b-det", "Laptop ✓", "ok"); voice.say("Connection to the laptop restored.", "system"); renderOffline(); }
    for (const e of r.events) {
      lastEventId = Math.max(lastEventId, e.id);
      if (e.source !== "replay" && e.source !== "upload") continue; // camera + client alerts are spoken directly
      voice.say(e.text, e.kind === "system" ? "system" : "obstacle", e.data && e.data.position);
    }
  } catch (e) {
    if (!serverDown) {
      serverDown = true; status.server = false; renderOffline();
      voice.say("Connection to the laptop lost. Detection and voice commands are unavailable.", "system");
    }
    badge("b-det", "Laptop ✕", "bad");
  } finally { setTimeout(pollEvents, document.hidden ? 3000 : 1000); }
}

// ------------------------------------------------------------------ WOAD replay (research tools)
let replayTimer = null, lastSeq = -1;
$("r-start").onclick = async () => {
  try {
    voice.beep("ahead", "info"); // user gesture: unlocks audio on mobile browsers
    await api("/api/replay/start", { set: $("r-set").value, fps: Number($("r-fps").value), loop: true });
    pollReplay();
  } catch (e) { showAlert("Could not start replay: " + e.message, "system"); }
};
$("r-stop").onclick = async () => { await api("/api/replay/stop", {}).catch(() => {}); };

async function pollReplay() {
  clearTimeout(replayTimer);
  try {
    const s = await api("/api/replay/state");
    if (s.running && s.seq !== lastSeq) {
      lastSeq = s.seq;
      $("r-img").src = `/api/replay/frame.jpg?seq=${s.seq}`;
      $("r-cap").textContent = `${s.set} · frame ${s.frame_index + 1}/${s.frames} (${s.frame_id})` +
        (s.inference_ms != null ? ` · inference ${s.inference_ms} ms` : "");
      const q = s.quality || {};
      $("r-quality").className = "quality " + (q.status || "");
      $("r-quality").textContent = q.status ? `Input quality: ${q.status.toUpperCase()}` +
        (q.reasons && q.reasons.length ? " — " + q.reasons.join("; ") : "") + ` (IR mean ${q.ir_mean}, contrast ${q.ir_std})` : "";
      $("r-dets").innerHTML = s.detections.map((d) => `<li>${escapeHtml(d.class_name)} ${Math.round(d.confidence * 100)}%</li>`).join("") ||
        "<li>no detections</li>";
    }
    if (s.running) replayTimer = setTimeout(pollReplay, 250);
  } catch (e) { replayTimer = setTimeout(pollReplay, 1000); }
}

// ------------------------------------------------------------------ single pair upload (research tools)
const readB64 = (file) => new Promise((ok, fail) => {
  const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = fail; r.readAsDataURL(file); });
$("u-go").onclick = async () => {
  const ir = $("u-ir").files[0], dp = $("u-depth").files[0];
  if (!ir || !dp) { showAlert("Choose both an IR image and a depth image.", "info"); return; }
  $("u-go").disabled = true; $("u-cap").textContent = "Detecting…";
  try {
    const r = await api("/api/detect", { ir_base64: await readB64(ir), depth_base64: await readB64(dp) });
    $("u-img").src = "data:image/jpeg;base64," + r.annotated_jpeg_base64;
    $("u-cap").textContent = `Input quality ${r.quality.status.toUpperCase()}` + (r.alerts.length ? " · " + r.alerts.join(" ") : " · nothing above the alert threshold");
    $("u-dets").innerHTML = r.detections.map((d) => `<li>${escapeHtml(d.class_name)} ${Math.round(d.confidence * 100)}%</li>`).join("") || "<li>no detections</li>";
  } catch (e) { $("u-cap").textContent = "Error: " + e.message; }
  finally { $("u-go").disabled = false; }
};

// ------------------------------------------------------------------ GPS
// fix: latest raw fix; every fix is checked by assessFix (stale / too inaccurate fixes are never used for guidance).
let watchId = null, fix = null, lastGoodT = null, gpsLoss = {}, lastPoorSpokenT = 0, geoDenied = false;
let dest = null, navState = {};
function geoStatus(t, speak) { $("g-status").textContent = t; if (speak) voice.say(t, "system"); }
const usableFix = () => (fix && assessFix(fix, Date.now()).use ? fix : null);

function renderGps() {
  const q = assessFix(fix, Date.now());
  const label = watchId == null ? (geoDenied ? "denied" : "off") : { none: "waiting", stale: "stale", unusable: "inaccurate", poor: "weak", good: "good" }[q.level];
  const cls = watchId == null ? (geoDenied ? "bad" : "") : { none: "warn", stale: "bad", unusable: "bad", poor: "warn", good: "ok" }[q.level];
  badge("b-gps", "GPS " + label, cls); pill("g-badge", label, cls); pill("a-gps", "GPS " + label, cls);
  if (fix) {
    $("g-pos").textContent = `${fix.lat.toFixed(5)}, ${fix.lon.toFixed(5)}`;
    $("g-acc").textContent = `± ${Math.round(fix.accuracy)} m`;
    $("g-age").textContent = `${Math.max(0, Math.round((Date.now() - fix.timestamp) / 1000))} s`;
  }
  if (watchId != null && fix) geoStatus(q.message);
}

function startLocation() {
  if (!("geolocation" in navigator)) return geoStatus("Location is not supported by this browser.", true);
  if (!window.isSecureContext) return geoStatus("Location needs the secure https:// address of the laptop.", true);
  if (watchId != null) return;
  geoDenied = false;
  geoStatus("Requesting location… allow it when the phone asks.");
  watchId = navigator.geolocation.watchPosition(onFix, onGeoError, { enableHighAccuracy: true, maximumAge: 3000, timeout: 20000 });
  renderGps();
}
function stopLocation() {
  if (watchId != null) navigator.geolocation.clearWatch(watchId);
  watchId = null; fix = null; lastGoodT = null; gpsLoss = {};
  geoStatus("Location off."); ["g-pos", "g-acc", "g-age"].forEach((id) => { $(id).textContent = "—"; });
  renderGps();
}
function onGeoError(err) {
  if (err.code === 1) {
    geoDenied = true;
    if (watchId != null) navigator.geolocation.clearWatch(watchId);
    watchId = null;
    geoStatus("Location permission denied. Navigation needs location. Allow it in Settings › Apps › Safari › Location.", true);
  } else if (err.code === 2) {
    geoStatus("Location unavailable: no GPS signal. Move to an open area. Still trying.", true);
  } else {
    geoStatus("Still waiting for a GPS fix…");
  }
  renderGps();
}
$("g-start").onclick = startLocation;
$("g-stop").onclick = stopLocation;

function onFix(p) {
  const now = Date.now();
  fix = { lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy, t: now,
    timestamp: p.timestamp && Math.abs(now - p.timestamp) < 864e5 ? p.timestamp : now };   // guard against odd clocks
  const q = assessFix(fix, now);
  renderGps();
  if (q.use) lastGoodT = now;
  if (simPos) return;                                // a simulated position is in use (testing)
  mapView.setPosition(fix);                          // drawn with its accuracy circle even when not used
  if (!q.use) return;                                // stale or too inaccurate: never used for guidance
  if (q.level === "poor" && activeRoute && now - lastPoorSpokenT > 60000) { lastPoorSpokenT = now; voice.say(q.message, "system"); }
  onPosition(fix);
}

// One entry point for every usable position (real GPS fix or simulated): coverage, route following, fallback guidance.
function onPosition(p) {
  updateCoverage(p);
  if (activeRoute) followActiveRoute(p);
  else updateGuidance();
}
setInterval(() => {   // fix age, GPS loss / recovery during guidance
  if (watchId != null) renderGps();
  const w = gpsWatch(gpsLoss, Date.now(), lastGoodT, !!activeRoute && !simPos && watchId != null);
  gpsLoss = w.state;
  if (w.text) { voice.say(w.text, "system"); logClientAlert("navigation", "system", w.text); }
  $("rt-badge").textContent = activeRoute ? (gpsLoss.lost ? "paused: no GPS" : "guiding") : (previewRoute ? "preview" : "no route");
}, 2000);

// ------------------------------------------------------------------ saved places + straight-line fallback
async function loadPlaces(selectId) {
  const { places } = await api("/api/places");
  $("p-list").innerHTML = `<option value="">— choose —</option>` +
    places.map((p) => `<option value="${p.id}" data-lat="${p.lat}" data-lon="${p.lon}">${escapeHtml(p.name)}</option>`).join("");
  if (selectId) $("p-list").value = String(selectId);
}
$("p-go").onclick = () => {
  const opt = $("p-list").selectedOptions[0];
  const c = parseCoords($("p-coords").value);
  if (opt && opt.value) chooseDestination({ name: opt.textContent, lat: Number(opt.dataset.lat), lon: Number(opt.dataset.lon) });
  else if (c) chooseDestination({ name: "Destination", ...c });
  else { showAlert("Choose a saved place or enter coordinates like 12.9249, 79.1353.", "info"); return; }
  if (!curPos()) voice.say("Start location to get guidance.", "navigation");
  updateGuidance();
};
$("p-clear").onclick = () => {
  dest = null; navState = {}; previewRoute = null; mapView.setDestination(null); mapView.setRoute(null);
  $("n-big").textContent = "No destination."; $("n-osm").hidden = true; $("r-summary").textContent = "No route."; $("rt-steps").innerHTML = "";
};
$("p-save-here").onclick = async () => {
  const p = curPos();
  if (!p) return showAlert("No current location yet. Press Start location first.", "info");
  await savePlace(p.lat, p.lon);
};
$("p-save-coords").onclick = async () => {
  const c = parseCoords($("p-coords").value);
  if (!c) return showAlert("Enter valid coordinates first.", "info");
  await savePlace(c.lat, c.lon);
};
async function savePlace(lat, lon) {
  const name = $("p-name").value.trim();
  if (!name) return showAlert("Enter a name for the place.", "info");
  try { const r = await api("/api/places", { name, lat, lon }); await loadPlaces(r.id); showAlert(`Saved ${name}.`, "navigation"); }
  catch (e) { showAlert("Could not save: " + e.message, "system"); }
}
$("p-delete").onclick = async () => {
  const id = $("p-list").value; if (!id) return;
  await api("/api/places/delete", { id: Number(id) }).catch(() => {}); await loadPlaces();
};

function updateGuidance() {
  if (!dest) return;
  const p = curPos();
  if (!p) { $("n-big").textContent = `${dest.name}: waiting for a current location…`; return; }
  const g = guidance(p, dest, navState, Date.now());
  navState = g.state;
  $("n-big").textContent = g.state.arrived ? `Near ${dest.name}` :
    `${formatDistance(g.info.distance)} · ${g.info.direction} (${Math.round(g.info.bearing)}°)`;
  $("n-arrow").setAttribute("transform", `rotate(${g.info.bearing})`);
  $("n-osm").href = osmWalkingUrl(p, dest); $("n-osm").hidden = false;
  // spoken only when no offline route is available for this destination (otherwise route guidance speaks)
  if (g.text && $("n-speak").checked && !previewRoute) { voice.say(g.text, "navigation"); logClientAlert("navigation", "navigation", g.text); }
}

// ------------------------------------------------------------------ offline map, search, walking route
const mapView = new MapView($("m-canvas"));
let mapInfo = null, activeRoute = null, previewRoute = null, routeState = {}, simPos = null, lastCoverageMsg = "", lastRerouteT = null;
const curPos = () => simPos || usableFix();

async function loadMap() {
  try {
    mapInfo = await api("/api/map/info");
    status.map = mapInfo;
    if (!mapInfo.available) { $("m-info").textContent = "No offline map installed. Straight-line guidance only."; return; }
    const b = mapInfo.bbox;
    $("m-info").textContent = `Offline map: ${mapInfo.region}, ${b.south.toFixed(2)}–${b.north.toFixed(2)}°N, ` +
      `${b.west.toFixed(2)}–${b.east.toFixed(2)}°E (dashed yellow box). ${mapInfo.places} searchable places. ` +
      `OpenStreetMap data of ${mapInfo.osm_timestamp.slice(0, 10)}. No map tiles or internet are used.` +
      (mapInfo.not_included && mapInfo.not_included.length ? ` Not included: ${mapInfo.not_included.map((x) => x.split(" (")[0]).join(", ")}.` : "");
    mapView.setData(await api("/api/map/data"));
    const p = curPos(); if (p) mapView.setPosition(p);
  } catch (e) { $("m-info").textContent = "Offline map could not be loaded: " + e.message; status.map = { available: false }; }
  renderOffline();
}

function updateCoverage(p) {
  if (!mapInfo || !mapInfo.available || !p) return;
  const inside = mapView.inCoverage(p.lat, p.lon);
  const msg = inside ? "" : "Outside the offline map area. Offline routes are not available here.";
  $("m-coverage").textContent = msg;
  if (msg !== lastCoverageMsg) { if (msg) voice.say(msg, "navigation"); else if (lastCoverageMsg) voice.say("Back inside the offline map area.", "navigation"); lastCoverageMsg = msg; }
}

$("m-zoom-in").onclick = () => mapView.zoom(1.6);
$("m-zoom-out").onclick = () => mapView.zoom(0.625);
$("m-fit").onclick = () => { if (mapInfo && mapInfo.bbox) { const b = mapInfo.bbox; mapView.setFollow(false); mapView.fitBounds(b.south, b.west, b.north, b.east); } };
$("m-me").onclick = () => {
  const p = curPos() || fix;
  if (!p) return showAlert("No position yet. Press Start location first.", "info");
  mapView.setPosition(p);
  if (activeRoute) mapView.setFollow(true); else mapView.centerOn(p.lat, p.lon, 2);
};

async function runSearch() {
  const q = $("s-q").value.trim();
  if (q.length < 2) return showAlert("Type at least two letters of a place or street name.", "info");
  const p = curPos();
  try {
    const r = await api(`/api/map/search?q=${encodeURIComponent(q)}` + (p ? `&lat=${p.lat}&lon=${p.lon}` : ""));
    $("s-results").innerHTML = r.results.map((x, i) => `<li><button data-i="${i}">${escapeHtml(x.name)}` +
      `<small> · ${escapeHtml(x.kind.replace("=", ": "))}${x.distance_m != null ? " · " + formatDistance(x.distance_m) : ""}</small></button></li>`).join("") ||
      "<li class=\"hint\">No offline match. Try another spelling or a nearby street name.</li>";
    voice.say(r.results.length ? `${r.results.length} results. First: ${r.results[0].name}.` : "No offline match found.", "info");
    $("s-results").querySelectorAll("button").forEach((b) => b.onclick = () => { chooseDestination(r.results[Number(b.dataset.i)]); if (curPos()) planRoute(true); });
  } catch (e) { showAlert("Search failed: " + e.message, "system"); }
}
$("s-go").onclick = runSearch;
$("s-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("s-q").blur(); runSearch(); } });

function chooseDestination(place) {
  dest = { name: place.name, lat: place.lat, lon: place.lon };
  navState = {}; activeRoute = null; previewRoute = null; routeState = {};
  mapView.setFollow(false); mapView.setDestination(dest); mapView.setRoute(null);
  $("r-summary").textContent = `Destination: ${dest.name}.`;
  $("rt-now").textContent = "Press Start to begin guidance.";
  $("rt-steps").innerHTML = "";
  $("s-results").innerHTML = "";
  voice.say(`Destination set: ${dest.name}.`, "navigation");
}

async function planRoute(spoken = true) {
  if (!dest) { showAlert("Choose a destination first.", "info"); return null; }
  const p = curPos();
  if (!p) {
    voice.say(fix ? "The current location is too old or inaccurate for a route. Waiting for a better GPS fix." :
      "No current position. Start location, or use a simulated position for testing.", "system");
    return null;
  }
  try {
    const r = await api("/api/route", { from: { lat: p.lat, lon: p.lon }, to: { lat: dest.lat, lon: dest.lon } });
    const route = prepareRoute(r, dest.name);
    previewRoute = route;
    mapView.setRoute(r.polyline);
    const mins = Math.max(1, Math.round(r.duration_s / 60));
    $("r-summary").textContent = `${dest.name}: ${formatDistance(r.distance_m)}, about ${mins} min` +
      (r.major_road_m > 0 ? ` (${formatDistance(r.major_road_m)} on main roads)` : "");
    $("rt-steps").innerHTML = r.steps.map((s) => `<li>${escapeHtml(s.text)}</li>`).join("") +
      (r.notes || []).map((n) => `<li class="warn">${escapeHtml(n)}</li>`).join("");
    if (spoken) {
      voice.say(`Route to ${dest.name}: ${formatDistance(r.distance_m)}, about ${mins} minutes.`, "navigation");
      (r.notes || []).forEach((n) => voice.say(n, "navigation"));
    }
    return route;
  } catch (e) {
    previewRoute = null;
    $("r-summary").textContent = "No offline route: " + e.message;
    voice.say("No offline route. " + e.message + " Straight-line guidance is still available.", "navigation");
    return null;
  }
}
$("rt-plan").onclick = () => planRoute(true);
$("rt-start").onclick = async () => {
  const route = await planRoute(false);
  if (!route) return;
  activeRoute = route; routeState = {}; gpsLoss = {}; lastRerouteT = null;
  mapView.setFollow(true);
  voice.say(`Starting guidance to ${dest.name}. ${route.steps[0].text}`, "navigation");
  logClientAlert("navigation", "navigation", `Guidance started to ${dest.name}`);
  const p = curPos(); if (p) followActiveRoute(p);
};
function stopGuidance(spoken = true) {
  const was = !!activeRoute;
  activeRoute = null; routeState = {}; gpsLoss = {};
  mapView.setFollow(false);
  if (spoken && was) voice.say("Guidance stopped.", "navigation");
}
$("rt-stop").onclick = () => stopGuidance(true);

let recalculating = false;
async function followActiveRoute(p) {
  if (!activeRoute || recalculating) return;
  const r = followRoute(activeRoute, p, routeState);
  routeState = r.state;
  const items = [...document.querySelectorAll("#rt-steps li")];
  items.forEach((li, i) => li.classList.toggle("current", i === Object.keys(routeState.announced).length));
  $("r-summary").textContent = r.state.arrived ? `Arrived near ${activeRoute.destName}.` :
    `${formatDistance(r.remaining)} to ${activeRoute.destName}` + (r.progress.distance > 20 ? ` · ${Math.round(r.progress.distance)} m from route` : "");
  if (r.offRoute && !canReroute(lastRerouteT, Date.now())) return;     // recently recalculated: wait
  r.texts.forEach((t) => { voice.say(t, "navigation"); logClientAlert("navigation", "navigation", t); });
  if (r.state.arrived) { activeRoute = null; mapView.setFollow(false); return; }
  if (r.offRoute) {
    recalculating = true; lastRerouteT = Date.now();
    const nr = await planRoute(false);
    recalculating = false;
    if (nr && activeRoute) { activeRoute = nr; routeState = {}; voice.say(`New route. ${nr.steps[0].text}`, "navigation"); }
  }
}

// simulated position (testing on the laptop; clearly marked purple on the map)
$("sim-here").onclick = () => { simPos = { lat: mapView.center.lat, lon: mapView.center.lon, accuracy: 5, simulated: true, t: Date.now() }; mapView.setPosition(simPos); onPosition(simPos); voice.say("Simulated position set.", "info"); };
$("sim-off").onclick = () => { simPos = null; mapView.setPosition(fix); voice.say(fix ? "Using real GPS." : "Simulation off. Start location for GPS.", "info"); };
$("sim-step").onclick = () => {
  const route = activeRoute || previewRoute;
  if (!route) return showAlert("Preview or start a route first.", "info");
  const p = curPos(), poly = route.polyline;
  // walk 20 m further along the route from the current position's projection onto it
  const along = p ? projectOnPolyline(p, poly).along : 0;
  const at = pointAtAlong(poly, along + 20);
  simPos = { lat: at.lat, lon: at.lon, accuracy: 5, simulated: true, t: Date.now() };
  mapView.setPosition(simPos);
  onPosition(simPos);
};

// ------------------------------------------------------------------ event-camera simulation (research tools)
let stream = null, simTimer = null, prevGray = null;
const alerter = new MotionAlerter();
const work = document.createElement("canvas"); work.width = 160; work.height = 120;
const wctx = work.getContext("2d", { willReadFrequently: true });
$("s-th").oninput = () => { $("s-th-v").textContent = $("s-th").value; };
$("s-start").onclick = async () => {
  if (stream) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return $("s-status").textContent = window.isSecureContext ? "Camera not supported by this browser." : "Camera needs HTTPS or localhost.";
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: 320, height: 240 }, audio: false });
    $("s-video").srcObject = stream; await $("s-video").play();
    $("s-status").textContent = "Camera on. Simulation running (about 10 frames per second).";
    prevGray = null; simTimer = setInterval(simStep, 100);
  } catch (e) {
    stream = null;
    $("s-status").textContent = e.name === "NotAllowedError" ? "Camera permission denied." : "Camera unavailable: " + e.message;
    voice.say($("s-status").textContent, "system");
  }
};
$("s-stop").onclick = () => {
  clearInterval(simTimer); simTimer = null;
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = null; prevGray = null; $("s-status").textContent = "Camera off.";
};
const simCtx = $("s-canvas").getContext("2d");
const simOut = simCtx.createImageData(160, 120);
function simStep() {
  const v = $("s-video"); if (v.readyState < 2) return;
  wctx.drawImage(v, 0, 0, 160, 120);
  const g = toGray(wctx.getImageData(0, 0, 160, 120).data, 160 * 120);
  if (prevGray) {
    const ev = diffEvents(prevGray, g, 160, 120, Number($("s-th").value));
    paintEvents(ev.polarity, simOut.data); simCtx.putImageData(simOut, 0, 0);
    ev.thirds.forEach((f, k) => { $("m-" + k).value = f; });
    for (const a of alerter.update(ev.thirds, Date.now())) {
      voice.say(a.text, "motion", a.position);
      logClientAlert("eventsim", "motion", a.text, a.position);
    }
  }
  prevGray = g;
}

// ------------------------------------------------------------------ history
function fmtTime(sec) {
  const d = new Date(sec * 1000), today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : d.toLocaleString();
}
async function loadHistory() {
  try {
    const [s, h] = await Promise.all([api("/api/stats"), api("/api/history?limit=100")]);
    const chips = [`Total ${s.total}`, ...Object.entries(s.by_source).map(([k, v]) => `${k}: ${v}`)];
    $("h-stats").innerHTML = chips.map((c) => `<span>${escapeHtml(c)}</span>`).join("");
    $("h-list").innerHTML = h.history.map((x) => `<li class="k-${escapeHtml(x.kind)}">${escapeHtml(x.text)}<small>${fmtTime(x.created)} · ${escapeHtml(x.source)} · ${escapeHtml(x.kind)}</small></li>`).join("") ||
      "<li>No alerts yet.</li>";
  } catch (e) { $("h-list").innerHTML = `<li>Could not load history: ${escapeHtml(e.message)}</li>`; }
}
$("h-refresh").onclick = loadHistory;
$("h-clear").onclick = async () => { if (confirm("Delete all stored alerts and navigation events?")) { await api("/api/history/clear", {}); loadHistory(); } };

// ------------------------------------------------------------------ live camera awareness: Walking Guidance
// The phone sends a small JPEG about every 400 ms (never more than one request in flight); the laptop returns the
// walking-path state. Only the server's announcements are spoken (they already include temporal confirmation).
const PATH_UI = {
  CLEAR_VIEW: ["clear", "Path appears clear"],
  POSSIBLE_OBSTACLE: ["caution", "Caution"],
  BLOCKED_VIEW: ["stop", "Stop"],
  UNCERTAIN: ["uncertain", "Cannot assess path"],
  CAMERA_UNAVAILABLE: ["unavailable", "Camera unavailable"],
};
// Frame interval: the laptop says what it can sustain (200 ms with the GPU detector, 400 ms with the CPU fallback);
// still at most one request in flight. Latency (camera capture -> analysed response) is recorded for diagnostics.
const FRAME_MS_DEFAULT = 400;
const frameMs = () => (aInfo && aInfo.recommended_frame_ms) || FRAME_MS_DEFAULT;
const aLatency = [];   // last 100 capture -> response times (ms)
let aStream = null, aTimer = null, aErrors = 0, aInfo = null, aState = null, aStallSince = null, aFps = null, aLastT = null;
let aSession = Math.random().toString(36).slice(2, 10);
const aCanvas = document.createElement("canvas");

// Detector chip: GPU (RF-DETR) or CPU fallback (SSDLite), so the user / presenter can see which one is analysing
function renderDetector(d) {
  if (!d || !d.name) { pill("a-det", "Detector —", ""); return; }
  const gpu = d.device === "cuda";
  pill("a-det", `${gpu ? "RF-DETR · GPU" : "SSDLite · CPU"}${d.fallback_reason ? " (fallback)" : ""}`, gpu ? "ok" : "warn");
  $("a-det").title = d.fallback_reason || (gpu ? "RF-DETR Nano on the laptop's NVIDIA GPU" : "SSDLite on the laptop CPU");
}

function setPathState(state, sub) {
  const ui = PATH_UI[state] || ["idle", aStream ? "Checking the path…" : "Awareness off"];
  aState = state || null;
  $("a-state").className = "pathstate " + ui[0];
  $("a-state-title").textContent = ui[1];
  if (sub != null) $("a-state-sub").textContent = sub;
}
function cameraUnavailable(reason) {
  if (aState === "CAMERA_UNAVAILABLE") return;
  const text = (aInfo && aInfo.path_messages && aInfo.path_messages[settings.mode].CAMERA_UNAVAILABLE) || "Camera view is unavailable.";
  setPathState("CAMERA_UNAVAILABLE", reason);
  voice.say(text, "system", null, { key: "path" });
  logClientAlert("awareness", "path", text);
  aSession = Math.random().toString(36).slice(2, 10);   // recovery starts a fresh server-side path state
}

async function startAwareness() {
  if (aStream) { voice.say("Camera awareness is already on.", "info"); return; }
  if (!aInfo || !aInfo.available) { voice.say("Camera awareness is not available on the laptop.", "system"); return; }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    voice.say(window.isSecureContext ? "This browser cannot use the camera." : "The camera needs the secure https address.", "system");
    return;
  }
  try {
    aStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
  } catch (e) {
    aStream = null;
    const msg = e.name === "NotAllowedError" ? "Camera permission denied. Camera awareness is off." : "Camera unavailable: " + e.message;
    $("a-status").textContent = msg; setPathState("CAMERA_UNAVAILABLE", msg); voice.say(msg, "system"); return;
  }
  aStream.getVideoTracks().forEach((t) => t.addEventListener("ended", () => cameraUnavailable("The camera stopped.")));
  const v = $("a-video"); v.srcObject = aStream; await v.play().catch(() => {});
  aErrors = 0; aStallSince = null; aFps = null; aLastT = null;
  aSession = Math.random().toString(36).slice(2, 10);
  $("a-camhint").textContent = "";
  setPathState(null, "Checking the path…");
  $("a-status").textContent = `Camera awareness on (${settings.mode} mode).`;
  if (aInfo.path_messages) voice.prefetch(Object.values(aInfo.path_messages[settings.mode]).concat(aInfo.path_reminders ? [aInfo.path_reminders[settings.mode]] : []));
  voice.say(`Camera awareness on. ${settings.describe ? "Object description on." : "Walking guidance."} No distances.`, "info");
  logClientAlert("awareness", "system", "Camera awareness started");
  scheduleFrame(0);
}
function stopAwareness(spoken = true) {
  clearTimeout(aTimer); aTimer = null;
  if (aStream) aStream.getTracks().forEach((t) => t.stop());
  const was = !!aStream; aStream = null;
  const ov = $("a-overlay"); ov.getContext("2d").clearRect(0, 0, ov.width, ov.height);
  $("a-video").srcObject = null;
  $("a-camhint").textContent = "Camera off";
  $("a-status").textContent = "Camera awareness off."; $("a-dets").innerHTML = ""; $("a-fps").textContent = "— fps";
  setPathState(null, "Press Start. The phone camera looks at the path ahead.");
  if (spoken && was) voice.say("Camera awareness off.", "info");
}
function scheduleFrame(ms) { clearTimeout(aTimer); if (aStream) aTimer = setTimeout(awarenessStep, ms); }

async function awarenessStep() {
  const v = $("a-video");
  const t0 = Date.now();
  if (!aStream) return;
  if (document.hidden) { scheduleFrame(1000); return; }          // no uploads while the page is not visible
  if (v.readyState < 2 || !v.videoWidth) {                        // no picture from the camera
    aStallSince = aStallSince || t0;
    if (t0 - aStallSince > 4000) cameraUnavailable("No picture from the camera.");
    scheduleFrame(frameMs()); return;
  }
  aStallSince = null;
  try {
    const tCapture = performance.now();
    const w = 320, h = Math.round((v.videoHeight / v.videoWidth) * 320);
    aCanvas.width = w; aCanvas.height = h;
    aCanvas.getContext("2d").drawImage(v, 0, 0, w, h);
    const blob = await new Promise((r) => aCanvas.toBlob(r, "image/jpeg", 0.7));
    const ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    const kill = ctl ? setTimeout(() => ctl.abort(), 5000) : null;   // a stuck request must not stop guidance
    const res = await fetch(`/api/awareness/frame?session=${aSession}&mode=${settings.mode}&describe=${settings.describe ? 1 : 0}`,
      { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: blob, signal: ctl ? ctl.signal : undefined });
    clearTimeout(kill);
    const r = await res.json();
    if (!res.ok) throw new Error(r.error || `HTTP ${res.status}`);
    if (!aStream) return;
    aErrors = 0;
    aLatency.push(Math.round(performance.now() - tCapture)); if (aLatency.length > 100) aLatency.shift();
    drawAwareness(r);
    for (const e of r.events) {
      if (e.kind === "path") {
        voice.say(e.text, e.category, null, { key: "path" });
        $("a-state-sub").textContent = e.text;
      } else if (e.kind === "event") {           // entering the path / crossing in front (camera-motion compensated)
        voice.say(e.text, e.category, (e.data && e.data.side) || null, { key: "path" });
        $("a-state-sub").textContent = e.text;
      } else if (settings.describe) {
        voice.say(e.text, "description", e.data && e.data.position);
      }
    }
    const p = r.path || {};
    if (p.state && p.state !== aState) setPathState(p.state);
    else if (!p.state && aState !== "CAMERA_UNAVAILABLE") setPathState(null);
    const dt = aLastT ? (Date.now() - aLastT) / 1000 : null; aLastT = Date.now();
    if (dt) aFps = aFps == null ? 1 / dt : 0.8 * aFps + 0.2 / dt;
    $("a-fps").textContent = aFps ? `${aFps.toFixed(1)} fps` : "— fps";
    if (r.detector) renderDetector(r.detector);
    const lat = aLatency.length ? [...aLatency].sort((x, y) => x - y)[Math.floor(aLatency.length / 2)] : null;
    $("a-status").textContent = `${settings.describe ? "Object description" : "Walking guidance"} · ${r.detector && r.detector.name ? r.detector.name : "detector"}` +
      ` ${r.inference_ms} ms · camera→answer ${lat != null ? lat + " ms" : "—"} · image ${r.quality.status}` +
      (r.quality.reasons.length ? ` (${r.quality.reasons[0]})` : "");
  } catch (e) {
    aErrors += 1;
    $("a-status").textContent = "Camera awareness error: " + (e.name === "AbortError" ? "laptop did not answer in time" : e.message);
    if (aErrors >= 3) cameraUnavailable("Cannot reach the laptop for camera analysis.");
  } finally {
    scheduleFrame(Math.max(0, frameMs() - (Date.now() - t0)));
  }
}
function drawAwareness(r) {
  const ov = $("a-overlay"), g = ov.getContext("2d");
  if (ov.width !== r.width || ov.height !== r.height) { ov.width = r.width; ov.height = r.height; }
  g.clearRect(0, 0, ov.width, ov.height);
  const p = r.path || {};
  if (p.polygon) {   // the walking-path region used for guidance
    g.beginPath();
    p.polygon.forEach(([x, y], i) => { const X = x * r.width, Y = y * r.height; if (i) g.lineTo(X, Y); else g.moveTo(X, Y); });
    g.closePath();
    const col = { BLOCKED_VIEW: "255,93,93", POSSIBLE_OBSTACLE: "255,176,32", CLEAR_VIEW: "61,220,151" }[p.state] || "169,179,214";
    g.fillStyle = `rgba(${col},0.12)`; g.fill(); g.strokeStyle = `rgba(${col},0.8)`; g.lineWidth = 2; g.setLineDash([6, 5]); g.stroke(); g.setLineDash([]);
  }
  const inPath = new Set((p.in_path || []).map((o) => o.class_name));
  g.lineWidth = 3; g.font = "14px system-ui";
  r.detections.forEach((d) => {
    const [x1, y1, x2, y2] = d.box_xyxy;
    const c = inPath.has(d.class_name) ? "#ffb020" : "#a9b3d6";
    g.strokeStyle = c; g.fillStyle = c;
    g.strokeRect(x1, y1, x2 - x1, y2 - y1);
    if (settings.describe) g.fillText(d.class_name, x1 + 3, Math.max(14, y1 - 3));
  });
  $("a-dets").innerHTML = settings.describe ? (r.detections.map((d) => `<li class="${inPath.has(d.class_name) ? "inpath" : ""}">${escapeHtml(d.class_name)}</li>`).join("") || "<li>nothing recognised</li>") : "";
}
$("a-start").onclick = () => { voice.unlock(); startAwareness(); };
$("a-stop").onclick = () => stopAwareness();
document.addEventListener("visibilitychange", () => {
  if (document.hidden && aStream) $("a-status").textContent = "Paused while the page is hidden (iPhone stops the camera).";
});

// Walking Guidance / Object Description switch (Home) + checkbox (Settings) stay in sync
function setDescribe(on, spoken) {
  settings.describe = !!on; saveSettings();
  $("v-describe").checked = settings.describe;
  $("od-walk").setAttribute("aria-checked", String(!settings.describe));
  $("od-desc").setAttribute("aria-checked", String(settings.describe));
  if (!settings.describe) $("a-dets").innerHTML = "";
  if (spoken) voice.say(settings.describe ? "Object description on. Object names will also be spoken." : "Walking guidance. Only changes in the path are spoken.", "info", null, { force: true });
}
$("od-walk").onclick = () => setDescribe(false, true);
$("od-desc").onclick = () => setDescribe(true, true);
$("v-describe").onchange = () => setDescribe($("v-describe").checked, true);

// ------------------------------------------------------------------ online scene description (cloud, opt-in)
// One still photo per request, only when the user asks (button, question or voice command) and only after consent.
// The laptop forwards it to the configured cloud provider; the answer is spoken with the "scene" category, so
// walking-guidance warnings ("Stop…") still interrupt it. Local walking guidance never waits for this.
let scBusy = false, scPendingQuestion = null;
const STILL_MAX = 1024;
// The laptop allows up to 45 s per description (30 s per attempt); the phone waits a little longer, and says once
// after 15 s that it is still waiting, so the user is not left in silence. Walking guidance continues meanwhile.
const SCENE_REQUEST_TIMEOUT_MS = 60000;
const SCENE_STILL_WAITING_MS = 15000;
const SCENE_STILL_WAITING_TEXT = "Still waiting for the online description. Local walking guidance continues.";
function renderVision() {
  const v = status.vision;
  let label = "checking", cls = "", msg = "";
  if (v === null) { label = "checking"; }
  else if (!v || v.available === false && !v.configured) { label = "unavailable"; cls = "bad"; msg = `Not available on the laptop${v && v.problem ? ": " + v.problem : ""}. Local walking guidance is not affected.`; }
  else if (v.breaker === "open") { label = "paused"; cls = "warn"; msg = `Paused after repeated failures; retry in about ${v.retry_after_s} s. Local walking guidance continues.`; }
  else if (!settings.cloudConsent) { label = "needs permission"; cls = "warn"; msg = "Off until you allow sending photos to the online service (Settings, or tap Describe)."; }
  else { label = scBusy ? "looking…" : "ready"; cls = "ok"; msg = `${v.provider} ${v.model}. Needs internet on the laptop.` + (v.last_error && v.ok === 0 ? ` Last error: ${v.last_error}` : ""); }
  pill("sc-badge", label, cls);
  if (!scBusy && msg) $("sc-status").textContent = msg;
  $("v-cloud").checked = !!settings.cloudConsent;
  $("v-cloud-status").textContent = v ? (v.configured ? `Provider: ${v.provider}, model ${v.model}. ${v.ok || 0} successful and ${Object.values(v.failures || {}).reduce((a, b) => a + b, 0)} failed requests since the laptop app started.` :
    `Not available: ${v.problem || "not configured"}.`) : "Checking…";
}
async function checkVision() {
  try { status.vision = await api("/api/vision/status"); } catch (e) { status.vision = { available: false, configured: false, problem: "laptop not reachable" }; }
  renderVision(); renderOffline();
}
function setCloudConsent(on, spoken) {
  settings.cloudConsent = !!on; saveSettings();
  $("sc-consent").hidden = true;
  renderVision();
  if (spoken) voice.say(on ? "Online scene description allowed. Photos are sent only when you ask." : "Online scene description is off. No photos will be sent.", "info", null, { force: true });
}
// one JPEG from the running awareness camera, or from a briefly opened camera
async function captureStill() {
  let stream = null, v = $("a-video");
  try {
    if (!aStream || v.readyState < 2 || !v.videoWidth) {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error(window.isSecureContext ? "camera not supported" : "the camera needs the https:// address");
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false });
      v = document.createElement("video"); v.muted = true; v.setAttribute("playsinline", ""); v.srcObject = stream;
      await v.play().catch(() => {});
      for (let i = 0; i < 40 && (v.readyState < 2 || !v.videoWidth); i++) await new Promise((r) => setTimeout(r, 50));
      await new Promise((r) => setTimeout(r, 300));          // let exposure settle
      if (!v.videoWidth) throw new Error("no picture from the camera");
    }
    const s = Math.min(1, STILL_MAX / Math.max(v.videoWidth, v.videoHeight));
    const c = document.createElement("canvas");
    c.width = Math.round(v.videoWidth * s); c.height = Math.round(v.videoHeight * s);
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    return await new Promise((r) => c.toBlob(r, "image/jpeg", 0.8));
  } finally {
    if (stream) stream.getTracks().forEach((t) => t.stop());
  }
}
async function describeScene(question) {
  question = String(question || "").trim().slice(0, 300);
  if (scBusy) { voice.say("Still waiting for the previous description.", "scene", null, { force: true }); return; }
  if (!settings.cloudConsent) {                               // opt-in on first use: ask, never upload silently
    scPendingQuestion = question;
    $("sc-consent").hidden = false;
    $("sc-status").textContent = "Permission needed before any photo is sent.";
    voice.say("Online description sends one camera photo to an online AI service. Tap Allow to continue, or Not now.", "scene", null, { force: true });
    return;
  }
  const v = status.vision;
  if (v && !v.configured) { voice.say(`Online scene description is not available on the laptop. Local walking guidance continues.`, "scene", null, { force: true }); return; }
  scBusy = true; renderVision();
  $("sc-status").textContent = question ? `Asking: "${question}"…` : "Looking…";
  voice.say(question ? "Asking." : "Looking.", "scene", null, { force: true });
  const waiting = setTimeout(() => { if (scBusy) voice.say(SCENE_STILL_WAITING_TEXT, "scene", null, { force: true }); }, SCENE_STILL_WAITING_MS);
  let text;
  try {
    const img = await captureStill();
    const ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    const kill = ctl ? setTimeout(() => ctl.abort(), SCENE_REQUEST_TIMEOUT_MS) : null;
    const res = await fetch(`/api/vision/describe?session=${aSession}&mode=${settings.mode}&consent=1&q=${encodeURIComponent(question)}`,
      { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: img, signal: ctl ? ctl.signal : undefined });
    clearTimeout(kill);
    const r = await res.json();
    if (!res.ok) throw new Error(r.error || `HTTP ${res.status}`);
    text = r.text;
    $("sc-status").textContent = r.ok ? `${r.text} (${(r.latency_ms / 1000).toFixed(1)} s, ${r.model})` : `${r.text}`;
  } catch (e) {
    text = e.name === "AbortError" ? "The online description took too long. Local walking guidance continues." :
      e.name === "NotAllowedError" ? "Camera permission denied. Online description needs the camera." :
      `Online scene description is unavailable: ${e.message}. Local walking guidance continues.`;
    $("sc-status").textContent = text;
  } finally {
    clearTimeout(waiting);
    scBusy = false;
  }
  voice.say(text, "scene", null, { force: true });
  checkVision();
}
$("sc-go").onclick = () => { voice.unlock(); describeScene($("sc-q").value); };
$("sc-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("sc-q").blur(); voice.unlock(); describeScene($("sc-q").value); } });
$("sc-allow").onclick = () => { setCloudConsent(true, false); const q = scPendingQuestion; scPendingQuestion = null; describeScene(q || ""); };
$("sc-deny").onclick = () => { scPendingQuestion = null; setCloudConsent(false, true); };
$("v-cloud").onchange = () => setCloudConsent($("v-cloud").checked, true);

// ------------------------------------------------------------------ spoken status report
function statusReport() {
  const parts = [];
  const p = curPos();
  if (simPos) parts.push("Using a simulated position.");
  else if (!fix) parts.push("Location is off or not yet available.");
  else parts.push(assessFix(fix, Date.now()).message);
  if (mapInfo && mapInfo.available && p) parts.push(mapView.inCoverage(p.lat, p.lon) ? `Inside the offline map of ${mapInfo.region}.` : "Outside the offline map area.");
  if (activeRoute) {
    const pr = projectOnPolyline(p || { lat: activeRoute.polyline[0][0], lon: activeRoute.polyline[0][1] }, activeRoute.polyline);
    parts.push(`Navigating to ${activeRoute.destName}, about ${formatDistance(Math.max(0, pr.total - pr.along))} remaining.`);
  } else if (dest) parts.push(`Destination set: ${dest.name}. Navigation not started.`);
  else parts.push("No destination.");
  parts.push(aStream ? `Camera awareness on, ${settings.describe ? "object description" : "walking guidance"}.` : "Camera awareness off.");
  parts.push(status.server === false ? "The laptop is not reachable." : "Connected to the laptop.");
  parts.push(!settings.cloudConsent ? "Online scene description: off." : status.vision && status.vision.configured ?
    "Online scene description: allowed, needs internet." : "Online scene description: not available.");
  return parts.join(" ");
}

// ------------------------------------------------------------------ voice commands (push-to-talk, offline Vosk on the laptop)
let vcInfo = null, listening = false;
const micLabel = (t) => { $("mic").querySelector(".miclabel").textContent = t; };
async function checkVoiceCommands() {
  try { vcInfo = await api("/api/voicecmd/status"); } catch (e) { vcInfo = { available: false, error: "server not reachable" }; }
  status.vc = vcInfo;
  $("vc-status").textContent = vcInfo.available ? `Voice commands ready: offline recogniser ${vcInfo.model} (Indian English).` :
    `Voice commands unavailable: ${vcInfo.error}.`;
  $("mic-status").textContent = vcInfo.available ? "Tap Speak, then say a command." : "Voice commands unavailable.";
  try { aInfo = await api("/api/awareness/status"); } catch (e) { aInfo = { available: false }; }
  status.aw = aInfo;
  renderDetector(aInfo && aInfo.detector);
  renderOffline();
}
async function listenOnce() {
  if (listening) return;
  voice.unlock();
  if (!vcInfo || !vcInfo.available) { voice.say("Voice commands are not available.", "system"); return; }
  listening = true;
  voice.stop();                                      // do not record our own speech
  const btn = $("mic"); btn.classList.add("listening"); micLabel("Listening");
  $("mic-status").textContent = "Listening… speak now.";
  try {
    const rec = await recordUtterance({ onLevel: () => {} });
    btn.classList.remove("listening"); btn.classList.add("busy"); micLabel("Thinking");
    if (!rec.heardSpeech) { $("mic-status").textContent = "No speech heard."; voice.say("I did not hear a command. Tap Speak and try again.", "info"); return; }
    const p = curPos();
    const res = await fetch("/api/voicecmd" + (p ? `?lat=${p.lat}&lon=${p.lon}` : ""), { method: "POST", headers: { "Content-Type": "audio/wav" }, body: rec.wav });
    const r = await res.json();
    if (!res.ok) throw new Error(r.error || `HTTP ${res.status}`);
    $("mic-status").textContent = `Heard: "${r.heard}" → ${r.intent.replace("_", " ")}`;
    await runIntent(r);
  } catch (e) {
    const msg = e.name === "NotAllowedError" ? "Microphone permission denied. Voice commands need the microphone." : "Voice command failed: " + e.message;
    $("mic-status").textContent = msg; voice.say(msg, "system");
  } finally {
    listening = false; btn.classList.remove("listening", "busy"); micLabel("Speak");
  }
}
async function runIntent(r) {
  logClientAlert("navigation", "system", `Voice command: ${r.intent}${r.query ? " (" + r.query + ")" : ""}`);
  switch (r.intent) {
    case "navigate":
    case "search": {
      if (!r.places.length) { voice.say(`No place found for "${r.query}". Try again, or type the name in Navigate.`, "info"); return; }
      const best = r.places[0], others = r.places.slice(1).map((x) => x.name);
      chooseDestination(best);
      showTab("tab-nav");
      let msg = `Destination: ${best.name}.` + (best.match === "sound-alike" ? " This was a best guess from your speech." : "");
      if (others.length) msg += ` Other matches: ${others.join(", ")}.`;
      voice.say(msg, "navigation");
      if (r.intent === "navigate") {
        const route = await planRoute(true);
        if (route) voice.say("Say start navigation to begin, or search again.", "navigation");
      }
      return;
    }
    case "start_navigation":
      if (!dest) { voice.say("No destination. Say navigate to, followed by a place.", "info"); return; }
      $("rt-start").click(); return;
    case "stop_navigation":
      if (!activeRoute) { voice.say("Navigation is not running.", "info"); return; }
      $("rt-stop").click(); return;
    case "repeat":
      voice.say(lastNavText || "There is no instruction to repeat yet.", "navigation", null, { force: true }); return;
    case "status":
      voice.say(statusReport(), "info", null, { force: true }); return;
    case "describe_scene": describeScene(""); return;
    case "ask_scene": describeScene(r.query || ""); return;
    case "awareness_on": startAwareness(); return;
    case "awareness_off": stopAwareness(); return;
    case "test_voice": $("v-test").click(); return;
    case "help":
    default:
      voice.say(r.message || vcInfo.help, "info", null, { force: true });
  }
}
$("mic").onclick = listenOnce;

// ------------------------------------------------------------------ permissions + offline status (Settings)
const PERM_TEXT = { granted: "allowed", denied: "denied — change in iPhone Settings", prompt: "will be asked" };
async function checkPermissions() {
  for (const [name, id] of [["camera", "perm-cam"], ["microphone", "perm-mic"], ["geolocation", "perm-loc"]]) {
    try {
      const s = await navigator.permissions.query({ name });
      $(id).textContent = PERM_TEXT[s.state] || s.state;
      s.onchange = () => { $(id).textContent = PERM_TEXT[s.state] || s.state; };
    } catch (e) { $(id).textContent = window.isSecureContext ? "asked when first used" : "needs the https:// address"; }
  }
}
async function askMedia(kind) {
  try {
    const s = await navigator.mediaDevices.getUserMedia(kind === "video" ? { video: { facingMode: "environment" } } : { audio: true });
    s.getTracks().forEach((t) => t.stop());
    voice.say(kind === "video" ? "Camera allowed." : "Microphone allowed.", "info", null, { force: true });
  } catch (e) {
    voice.say(`${kind === "video" ? "Camera" : "Microphone"} not allowed: ${e.name === "NotAllowedError" ? "permission denied" : e.message}.`, "system");
  }
  checkPermissions();
}
$("perm-ask-cam").onclick = () => { voice.unlock(); if (navigator.mediaDevices) askMedia("video"); };
$("perm-ask-mic").onclick = () => { voice.unlock(); if (navigator.mediaDevices) askMedia("audio"); };
$("perm-ask-loc").onclick = () => {
  voice.unlock();
  if (!("geolocation" in navigator)) return;
  navigator.geolocation.getCurrentPosition(() => { voice.say("Location allowed.", "info", null, { force: true }); checkPermissions(); },
    (e) => { onGeoError(e); checkPermissions(); }, { enableHighAccuracy: true, timeout: 20000 });
};
function renderOffline() {
  const rows = [
    ["Laptop server", status.server == null ? null : status.server, status.server === false ? "not reachable" : location.host],
    ["Neural voice (Piper)", status.tts && status.tts.available, status.tts ? (status.tts.available ? "on laptop" : "device voice used") : "…"],
    ["Voice commands (Vosk)", status.vc && status.vc.available, status.vc ? (status.vc.available ? "on laptop" : "unavailable") : "…"],
    ["Camera detector (SSDLite)", status.aw && status.aw.available, status.aw ? (status.aw.available ? "on laptop" : "unavailable") : "…"],
    ["Offline map", status.map && status.map.available, status.map ? (status.map.available ? status.map.region : "not installed") : "…"],
    ["Online scene description", status.vision && status.vision.configured && status.vision.breaker !== "open",
      !status.vision ? "…" : !status.vision.configured ? "not available" : !settings.cloudConsent ? "needs your permission" :
      status.vision.breaker === "open" ? "paused after failures" : "needs laptop internet"],
    ["Internet", true, "not needed for local guidance"],
  ];
  $("off-list").innerHTML = rows.map(([k, ok, v]) => `<li class="${ok == null ? "" : ok ? "ok" : "bad"}"><span>${escapeHtml(k)}</span><span>${escapeHtml(v)}</span></li>`).join("");
}

// ------------------------------------------------------------------ settings UI
function fillVoices() {
  const vs = voice.voices();
  $("v-voice").innerHTML = `<option value="">Default voice</option>` +
    vs.map((v) => `<option ${v.name === settings.voice ? "selected" : ""}>${escapeHtml(v.name)}</option>`).join("");
  updateVoiceBadge();
}
// The badge reflects what can actually speak, not just a setting.
function updateVoiceBadge() {
  const st = voice.status;
  if (!settings.speech) return badge("b-voice", "Voice off", "warn");
  if (st.speaking) return badge("b-voice", "Speaking", "ok");
  if (st.lastError) return badge("b-voice", "Voice error", "bad");
  if (voice.neuralAvailable && settings.engine !== "browser") return badge("b-voice", voice.unlocked ? "Voice ✓" : "Tap for sound", voice.unlocked ? "ok" : "warn");
  if (voice.supported) return badge("b-voice", "Device voice", "ok");
  badge("b-voice", "No voice", "bad");
}
voice.onStatus = (st) => {
  const el = $("v-speaking");
  el.className = "speaking" + (st.speaking ? " on" : st.lastError ? " err" : "");
  el.textContent = st.speaking ? `Speaking (${st.engine === "neural" ? "neural voice" : "device voice"}): ${st.text}` :
    st.lastError ? st.lastError : (st.lastOk || "Not speaking.");
  updateVoiceBadge();
};
voice.onReport = (r) => {   // lets the laptop see whether playback on the phone actually ran
  api("/api/voice/report", Object.assign({}, r, { user_agent: navigator.userAgent, via: location.host })).catch(() => {});
};
async function checkVoiceEngine() {
  try {
    const s = await api("/api/tts/status");
    status.tts = s;
    voice.neuralAvailable = !!s.available;
    $("v-engine-status").textContent = s.available ?
      `Neural voice ready: Piper ${s.engine_version}, voice ${s.voice} (${s.language}), generated on the laptop without internet.` :
      `Neural voice unavailable (${s.error || "not configured"}). Using this device's built-in voice.`;
  } catch (e) {
    voice.neuralAvailable = false; status.tts = { available: false };
    $("v-engine-status").textContent = "Neural voice unavailable (server not reachable). Using this device's built-in voice.";
  }
  updateVoiceBadge(); renderOffline();
}
$("v-engine").value = settings.engine;
$("v-engine").onchange = () => { settings.engine = $("v-engine").value; saveSettings(); updateVoiceBadge(); };
$("v-mode").value = settings.mode; $("a-mode-label").textContent = settings.mode;
$("v-mode").onchange = () => {
  settings.mode = $("v-mode").value; saveSettings(); $("a-mode-label").textContent = settings.mode;
  voice.say(settings.mode === "chest" ? "Chest mode. Messages describe the walking path." : "Handheld mode. Messages describe the camera view.", "info");
};
if (voice.supported) window.speechSynthesis.onvoiceschanged = fillVoices;
$("v-speech").checked = settings.speech; $("v-beeps").checked = settings.beeps;
$("v-rate").value = settings.rate; $("v-vol").value = settings.volume;
$("v-speech").onchange = () => { settings.speech = $("v-speech").checked; if (!settings.speech) voice.stop(); saveSettings(); fillVoices(); };
$("v-beeps").onchange = () => { settings.beeps = $("v-beeps").checked; saveSettings(); };
$("v-voice").onchange = () => { settings.voice = $("v-voice").value; saveSettings(); };
$("v-rate").onchange = () => { settings.rate = Number($("v-rate").value); saveSettings(); };
$("v-vol").onchange = () => { settings.volume = Number($("v-vol").value); saveSettings(); };
$("v-test").onclick = () => {
  voice.unlock();                                  // inside the tap: required on iOS
  if (!settings.speech) { settings.speech = true; $("v-speech").checked = true; saveSettings(); }
  $("v-result").textContent = `Playing with ${voice.neuralAvailable && settings.engine !== "browser" ? "the neural voice" : "the device voice"}…`;
  voice.say(TEST_SENTENCE, "system", null, { force: true });
};

setDescribe(settings.describe, false);
fillVoices();
updateNet();
renderGps();
// iOS: unlock audio + speech on the first tap anywhere (alerts arrive later from polling, outside a gesture),
// then say a short welcome so the user knows sound works.
let welcomed = false;
["pointerdown", "touchend", "keydown"].forEach((ev) => document.addEventListener(ev, () => {
  if (voice.unlocked) return;
  voice.unlock();
  updateVoiceBadge();
  if (!welcomed && settings.speech) {
    welcomed = true;
    setTimeout(() => voice.say("NeuroSonic ready. Sound is on." +
      (mapInfo && mapInfo.available ? ` Offline map of ${mapInfo.region} available.` : ""), "info"), 300);
  }
}, { passive: true }));
if (location.hash) showTab(location.hash.slice(1));
init().then(() => {
  pollEvents(); loadPlaces().catch(() => {}); checkVoiceEngine(); loadMap(); checkVoiceCommands(); checkVision();
  // demo convenience: ?autostart=eventsim opens the simulation and starts the camera (permission still required)
  if (new URLSearchParams(location.search).get("autostart") === "eventsim") { showTab("tab-sim"); $("sim-card").open = true; $("s-start").click(); }
});
// exported for debugging in the console and for the browser tests
window.neurosonic = { voice, distanceM, bearingDeg, compass, mapView, settings, get route() { return activeRoute; },
  get pathState() { return aState; }, setDescribe, showTab, describeScene, setCloudConsent, get vision() { return status.vision; },
  get awarenessLatency() { return aLatency.slice(); }, get awarenessInfo() { return aInfo; } };
