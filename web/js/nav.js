// Straight-line guidance maths (no routing). Pure functions, unit-tested in Node.

const R = 6371000; // mean Earth radius, metres
const rad = (d) => (d * Math.PI) / 180;
const deg = (r) => (r * 180) / Math.PI;

export function distanceM(a, b) {
  const dLat = rad(b.lat - a.lat), dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function bearingDeg(a, b) {
  const y = Math.sin(rad(b.lon - a.lon)) * Math.cos(rad(b.lat));
  const x = Math.cos(rad(a.lat)) * Math.sin(rad(b.lat)) - Math.sin(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.cos(rad(b.lon - a.lon));
  return (deg(Math.atan2(y, x)) + 360) % 360;
}

const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];
export function compass(bearing) {
  return COMPASS[Math.round(((bearing % 360) + 360) % 360 / 45) % 8];
}

export function formatDistance(m) {
  if (m < 1000) return `${Math.round(m / 5) * 5} metres`;
  return `${(m / 1000).toFixed(m < 10000 ? 1 : 0)} kilometres`;
}

// "51.5007, -0.1246" or "51.5007 -0.1246" -> {lat, lon}; null if invalid
export function parseCoords(text) {
  const m = String(text).trim().match(/^(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)$/);
  if (!m) return null;
  const lat = Number(m[1]), lon = Number(m[2]);
  if (!(lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180)) return null;
  return { lat, lon };
}

const acc = (pos) => (pos.accuracy == null ? 0 : pos.accuracy); // (no "??": keeps older iOS Safari working)

// Decide what (if anything) to say for a new position fix.
// state: {lastSpokenDistance, lastSpokenAt, arrived}; returns {text|null, state, info}
export function guidance(pos, dest, state, now, { repeatMs = 30000, stepM = 50, arriveM = 15, poorAccuracyM = 50 } = {}) {
  const d = distanceM(pos, dest);
  const b = bearingDeg(pos, dest);
  const info = { distance: d, bearing: b, direction: compass(b) };
  const s = { ...state };
  const arriveRadius = Math.max(arriveM, Math.min(acc(pos), 50));
  if (d <= arriveRadius) {
    if (!s.arrived) {
      s.arrived = true; s.lastSpokenAt = now; s.lastSpokenDistance = d;
      return { text: `You are near ${dest.name}. Within about ${formatDistance(Math.max(d, acc(pos)))}.`, state: s, info };
    }
    return { text: null, state: s, info };
  }
  s.arrived = false;
  const due = s.lastSpokenAt == null || now - s.lastSpokenAt >= repeatMs ||
    s.lastSpokenDistance == null || Math.abs(s.lastSpokenDistance - d) >= stepM;
  if (!due) return { text: null, state: s, info };
  s.lastSpokenAt = now; s.lastSpokenDistance = d;
  let text = `${dest.name}: ${formatDistance(d)} to the ${info.direction}, straight line.`;
  if (acc(pos) > poorAccuracyM) text += ` GPS accuracy is low, about ${Math.round(pos.accuracy)} metres.`;
  return { text, state: s, info };
}

// ---------------------------------------------------------------- following an offline route
// Local flat projection around a reference latitude (metres); accurate enough within a city.
function toXY(p, refLat) {
  const k = 111320;
  return [p.lon * k * Math.cos((refLat * Math.PI) / 180), p.lat * 110540];
}

// Closest point of a polyline ([[lat, lon], ...]) to pos: {distance, along (m from start), segment}
export function projectOnPolyline(pos, poly) {
  const refLat = poly[0][0];
  const P = toXY(pos, refLat);
  let best = { distance: Infinity, along: 0, segment: 0 }, acc = 0;
  for (let i = 0; i + 1 < poly.length; i++) {
    const A = toXY({ lat: poly[i][0], lon: poly[i][1] }, refLat), B = toXY({ lat: poly[i + 1][0], lon: poly[i + 1][1] }, refLat);
    const dx = B[0] - A[0], dy = B[1] - A[1], len2 = dx * dx + dy * dy, len = Math.sqrt(len2);
    const t = len2 > 0 ? Math.max(0, Math.min(1, ((P[0] - A[0]) * dx + (P[1] - A[1]) * dy) / len2)) : 0;
    const qx = A[0] + t * dx, qy = A[1] + t * dy, d = Math.hypot(P[0] - qx, P[1] - qy);
    if (d < best.distance) best = { distance: d, along: acc + t * len, segment: i };
    acc += len;
  }
  best.total = acc;
  return best;
}

// Point at a given distance (m) along a polyline; clamps to the ends. Returns {lat, lon}.
export function pointAtAlong(poly, along) {
  // same flat metric as projectOnPolyline, so pointAtAlong and projectOnPolyline are exact inverses
  const refLat = poly[0][0];
  let acc = 0;
  for (let i = 0; i + 1 < poly.length; i++) {
    const a = { lat: poly[i][0], lon: poly[i][1] }, b = { lat: poly[i + 1][0], lon: poly[i + 1][1] };
    const A = toXY(a, refLat), B = toXY(b, refLat), seg = Math.hypot(B[0] - A[0], B[1] - A[1]);
    if (acc + seg >= along && seg > 0) {
      const f = Math.max(0, (along - acc) / seg);
      return { lat: a.lat + (b.lat - a.lat) * f, lon: a.lon + (b.lon - a.lon) * f };
    }
    acc += seg;
  }
  const last = poly[poly.length - 1];
  return { lat: last[0], lon: last[1] };
}

// Prepare a route from the server for following: adds the position of each step along the polyline.
export function prepareRoute(route, destName) {
  const steps = route.steps.map((s) => Object.assign({}, s, {
    along: s.at ? projectOnPolyline({ lat: s.at[0], lon: s.at[1] }, route.polyline).along : null }));
  return Object.assign({}, route, { steps, destName });
}

// Decide what to say for a new position fix while following a prepared route.
// state: {announced: {stepIndex: "pre"|"now"}, offCount, arrived}. Returns {texts, state, offRoute, remaining, progress}.
export function followRoute(route, pos, state, { preM = 70, nowM = 25, offRouteM = 35, arriveM = 15 } = {}) {
  const s = { announced: Object.assign({}, state.announced || {}), offCount: state.offCount || 0, arrived: !!state.arrived };
  const texts = [];
  const pr = projectOnPolyline(pos, route.polyline);
  const remaining = Math.max(0, pr.total - pr.along);
  const accuracy = pos.accuracy == null ? 0 : pos.accuracy;
  const end = route.polyline[route.polyline.length - 1];
  const toEnd = distanceM(pos, { lat: end[0], lon: end[1] });
  if (s.arrived) return { texts, state: s, offRoute: false, remaining, progress: pr };
  if (toEnd <= Math.max(arriveM, Math.min(accuracy, 40))) {
    s.arrived = true;
    texts.push(`You have arrived near ${route.destName || "the destination"}.`);
    return { texts, state: s, offRoute: false, remaining: 0, progress: pr };
  }
  if (pr.distance > Math.max(offRouteM, accuracy * 1.5)) {
    s.offCount += 1;
    if (s.offCount >= 2) {
      s.offCount = 0;
      return { texts: ["You appear to be off the route. Recalculating."], state: s, offRoute: true, remaining, progress: pr };
    }
    return { texts, state: s, offRoute: false, remaining, progress: pr };
  }
  s.offCount = 0;
  for (let i = 1; i < route.steps.length; i++) {          // step 0 is spoken when the route starts
    const st = route.steps[i];
    if (st.along == null) continue;
    const ahead = st.along - pr.along;
    if (ahead < -10) { s.announced[i] = "now"; continue; } // already passed
    if (ahead <= nowM && s.announced[i] !== "now") {
      s.announced[i] = "now";
      texts.push(st.text);
      break;
    }
    if (ahead <= preM && !s.announced[i]) {
      s.announced[i] = "pre";
      // short pre-announcement ("In about 60 metres, turn left onto X.") when the server supplies the action
      texts.push(st.action ? `In about ${formatDistance(ahead)}, ${st.action.charAt(0).toLowerCase()}${st.action.slice(1)}.`
        : `In about ${formatDistance(ahead)}: ${st.text.charAt(0).toLowerCase()}${st.text.slice(1)}`);
      break;
    }
    if (ahead > preM) break;
  }
  return { texts, state: s, offRoute: false, remaining, progress: pr };
}

export function osmWalkingUrl(from, to) {
  return `https://www.openstreetmap.org/directions?engine=fossgis_osrm_foot&route=${from.lat.toFixed(6)}%2C${from.lon.toFixed(6)}%3B${to.lat.toFixed(6)}%2C${to.lon.toFixed(6)}`;
}

// ---------------------------------------------------------------- GPS fix quality (pure; unit-tested)
// The browser may deliver cached or very inaccurate fixes (Wi-Fi/cell positioning indoors). Guidance must not
// treat them as the user's current position.
export const GPS_LIMITS = { staleMs: 15000, poorM: 50, unusableM: 100 };
export function assessFix(fix, now, limits = GPS_LIMITS) {
  if (!fix || !Number.isFinite(fix.lat) || !Number.isFinite(fix.lon)) {
    return { use: false, level: "none", message: "No location yet." };
  }
  const age = now - (fix.timestamp != null ? fix.timestamp : fix.t);
  if (age > limits.staleMs) {
    return { use: false, level: "stale", age, message: `Location is ${Math.round(age / 1000)} seconds old. Waiting for a new fix.` };
  }
  const a = fix.accuracy == null ? Infinity : fix.accuracy;
  if (a > limits.unusableM) {
    return { use: false, level: "unusable", age, message: `Location too inaccurate (about ${Math.round(a)} metres). Guidance paused.` };
  }
  if (a > limits.poorM) {
    return { use: true, level: "poor", age, message: `GPS accuracy is low, about ${Math.round(a)} metres.` };
  }
  return { use: true, level: "good", age, message: `Location active, accuracy about ${Math.round(a)} metres.` };
}

// GPS loss / recovery while guidance is active. state: {lost, lastGoodT}. Returns {state, text|null}.
export function gpsWatch(state, now, lastGoodT, guidanceActive, lostMs = 20000) {
  const s = { lost: !!state.lost };
  if (!guidanceActive) return { state: { lost: false }, text: null };
  const gone = lastGoodT == null || now - lastGoodT > lostMs;
  if (gone && !s.lost) return { state: { lost: true }, text: "GPS signal lost. Guidance paused. Please stop and wait, or ask for help." };
  if (!gone && s.lost) return { state: { lost: false }, text: "GPS signal restored. Guidance continues." };
  return { state: s, text: null };
}

// Re-routing is rate-limited, so a wandering GPS position cannot cause a stream of "Recalculating" messages.
export function canReroute(lastRerouteT, now, minMs = 15000) {
  return lastRerouteT == null || now - lastRerouteT >= minMs;
}
