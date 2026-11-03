// Offline map renderer: draws NeuroSonic's local OSM extract (maps/<region>/map.json) on a <canvas>.
// No tiles, no external libraries, no network. Drag / pinch / wheel to move and zoom.

const M_PER_DEG_LAT = 110540;
const M_PER_DEG_LON = 111320;

export class MapView {
  constructor(canvas) {
    this.c = canvas;
    this.g = canvas.getContext("2d");
    this.data = null;
    this.center = { lat: 12.93, lon: 79.14 };
    this.mpp = 8;               // metres per CSS pixel
    this.position = null;       // {lat, lon, accuracy}
    this.destination = null;    // {lat, lon, name}
    this.route = null;          // [[lat, lon], ...]
    this.follow = false;        // keep the map centred on the position (during guidance)
    this._centredOnce = false;  // first real position: centre on it once
    this._pending = false;
    this._pointers = new Map();
    this._bind();
    this.resize();
  }

  // ------------------------------------------------------------------ data / state
  setData(d) {
    this.data = d;
    const b = d.bbox;
    this.center = { lat: (b.south + b.north) / 2, lon: (b.west + b.east) / 2 };
    this.fitBounds(b.south, b.west, b.north, b.east);
  }
  inCoverage(lat, lon) {
    const b = this.data && this.data.bbox;
    return !!b && lat >= b.south && lat <= b.north && lon >= b.west && lon <= b.east;
  }
  fitBounds(s, w, n, e) {
    const r = this.c.getBoundingClientRect();
    const hm = (n - s) * M_PER_DEG_LAT, wm = (e - w) * M_PER_DEG_LON * Math.cos((this.center.lat * Math.PI) / 180);
    this.center = { lat: (s + n) / 2, lon: (w + e) / 2 };
    this.mpp = Math.max(0.5, Math.max(wm / Math.max(r.width - 20, 50), hm / Math.max(r.height - 20, 50)));
    this.redraw();
  }
  setPosition(p) {
    this.position = p;
    // initial view: the first position inside the map is centred at street zoom; during guidance the map follows
    if (p && (this.follow || (!this._centredOnce && !this.route && this.inCoverage(p.lat, p.lon)))) {
      this._centredOnce = true;
      this.center = { lat: p.lat, lon: p.lon };
      if (!this.follow) this.mpp = Math.min(this.mpp, 3);
    }
    this.redraw();
  }
  setFollow(on) { this.follow = !!on; if (on && this.position) this.centerOn(this.position.lat, this.position.lon, Math.min(this.mpp, 2.5)); }
  setDestination(p) { this.destination = p; this.redraw(); }
  setRoute(poly) {
    this.route = poly;
    if (poly && poly.length > 1) {
      let s = 90, n = -90, w = 180, e = -180;
      poly.forEach(([la, lo]) => { s = Math.min(s, la); n = Math.max(n, la); w = Math.min(w, lo); e = Math.max(e, lo); });
      const pad = 0.002;
      this.fitBounds(s - pad, w - pad, n + pad, e + pad);
    } else this.redraw();
  }
  centerOn(lat, lon, mpp) { this.center = { lat, lon }; if (mpp) this.mpp = mpp; this.redraw(); }
  zoom(f) { this.mpp = Math.min(60, Math.max(0.3, this.mpp / f)); this.redraw(); }

  // ------------------------------------------------------------------ projection
  _xy(lat, lon) {
    const k = Math.cos((this.center.lat * Math.PI) / 180);
    return [this.w / 2 + ((lon - this.center.lon) * M_PER_DEG_LON * k) / this.mpp,
      this.h / 2 - ((lat - this.center.lat) * M_PER_DEG_LAT) / this.mpp];
  }
  _ll(x, y) {
    const k = Math.cos((this.center.lat * Math.PI) / 180);
    return { lat: this.center.lat - ((y - this.h / 2) * this.mpp) / M_PER_DEG_LAT,
      lon: this.center.lon + ((x - this.w / 2) * this.mpp) / (M_PER_DEG_LON * k) };
  }

  // ------------------------------------------------------------------ interaction
  _bind() {
    const c = this.c;
    c.style.touchAction = "none";
    c.addEventListener("pointerdown", (e) => { c.setPointerCapture(e.pointerId); this._pointers.set(e.pointerId, [e.clientX, e.clientY]); });
    c.addEventListener("pointermove", (e) => {
      if (!this._pointers.has(e.pointerId)) return;
      const prev = this._pointers.get(e.pointerId);
      if (this._pointers.size === 1) {
        this.follow = false;            // the user moved the map: stop following until "My position"
        const k = Math.cos((this.center.lat * Math.PI) / 180);
        this.center.lon -= ((e.clientX - prev[0]) * this.mpp) / (M_PER_DEG_LON * k);
        this.center.lat += ((e.clientY - prev[1]) * this.mpp) / M_PER_DEG_LAT;
      } else if (this._pointers.size === 2) {
        const other = [...this._pointers.entries()].find(([id]) => id !== e.pointerId)[1];
        const d0 = Math.hypot(prev[0] - other[0], prev[1] - other[1]), d1 = Math.hypot(e.clientX - other[0], e.clientY - other[1]);
        if (d0 > 0) this.mpp = Math.min(60, Math.max(0.3, (this.mpp * d0) / d1));
      }
      this._pointers.set(e.pointerId, [e.clientX, e.clientY]);
      this.redraw();
    });
    const up = (e) => this._pointers.delete(e.pointerId);
    c.addEventListener("pointerup", up); c.addEventListener("pointercancel", up);
    c.addEventListener("wheel", (e) => { e.preventDefault(); this.zoom(e.deltaY < 0 ? 1.25 : 0.8); }, { passive: false });
    window.addEventListener("resize", () => this.resize());
    // The canvas may be created inside a hidden tab (size 0): re-measure whenever it becomes visible / resizes,
    // and re-fit the view the first time it gets a real size.
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(() => {
        const wasTiny = this.w < 50;
        this.resize();
        if (wasTiny && this.w >= 50) this._refit();
      }).observe(c);
    }
  }
  _refit() {
    if (this.route && this.route.length > 1) this.setRoute(this.route);
    else if (this.data) { const b = this.data.bbox; this.fitBounds(b.south, b.west, b.north, b.east); }
  }
  // call when the map's tab becomes visible (fallback for browsers without ResizeObserver)
  shown() { const wasTiny = this.w < 50; this.resize(); if (wasTiny && this.w >= 50) this._refit(); }
  resize() {
    const r = this.c.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    this.w = Math.max(r.width, 10); this.h = Math.max(r.height, 10);
    const W = Math.round(this.w * dpr), H = Math.round(this.h * dpr);
    if (this.c.width === W && this.c.height === H) { this.redraw(); return; }   // avoid needless canvas resets
    this.c.width = W; this.c.height = H;
    this.g.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.redraw();
  }
  redraw() {
    if (this._pending) return;
    this._pending = true;
    requestAnimationFrame(() => { this._pending = false; this._draw(); });
  }

  // ------------------------------------------------------------------ drawing
  _path(pts, close) {
    const g = this.g;
    g.beginPath();
    for (let i = 0; i < pts.length; i++) {
      const [x, y] = this._xy(pts[i][1], pts[i][0]);   // stored as [lon, lat]
      if (i) g.lineTo(x, y); else g.moveTo(x, y);
    }
    if (close) g.closePath();
  }
  _draw() {
    const g = this.g, d = this.data;
    g.fillStyle = "#1a1f2e"; g.fillRect(0, 0, this.w, this.h);    // outside coverage
    if (!d) { this._label("Offline map not loaded.", 12, 24); return; }
    const b = d.bbox;
    const [x0, y0] = this._xy(b.north, b.west), [x1, y1] = this._xy(b.south, b.east);
    g.fillStyle = "#0e1424"; g.fillRect(x0, y0, x1 - x0, y1 - y0);   // covered area
    const fill = (list, color) => { g.fillStyle = color; list.forEach((p) => { this._path(p, true); g.fill(); }); };
    const stroke = (list, color, width, dash) => {
      g.strokeStyle = color; g.lineWidth = width; g.setLineDash(dash || []);
      list.forEach((p) => { this._path(p, false); g.stroke(); });
      g.setLineDash([]);
    };
    fill(d.landuse || [], "#161d33"); fill(d.green || [], "#13301f"); fill(d.water || [], "#12325a");
    stroke(d.waterline || [], "#2a5d9a", 1.5);
    stroke(d.rail || [], "#8a8fa8", 1.5, [6, 4]);
    const z = Math.max(0.6, Math.min(2.2, 6 / this.mpp));
    stroke(d.roads.minor || [], "#4a5375", 1 * z);
    stroke(d.roads.foot || [], "#9fb2d9", 1 * z, [3, 3]);
    stroke(d.roads.medium || [], "#c9cfe6", 2 * z);
    stroke(d.roads.major || [], "#ffb020", 3 * z);
    // coverage boundary
    g.strokeStyle = "#ffd23f"; g.lineWidth = 2; g.setLineDash([8, 6]); g.strokeRect(x0, y0, x1 - x0, y1 - y0); g.setLineDash([]);
    // route
    if (this.route && this.route.length > 1) {
      g.strokeStyle = "#3ddc97"; g.lineWidth = 6; g.lineJoin = "round"; g.beginPath();
      this.route.forEach(([la, lo], i) => { const [x, y] = this._xy(la, lo); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
      g.stroke();
      const [sx, sy] = this._xy(this.route[0][0], this.route[0][1]);     // route start: small white ring
      g.strokeStyle = "#fff"; g.lineWidth = 3; g.beginPath(); g.arc(sx, sy, 6, 0, 7); g.stroke();
    }
    if (this.destination) {
      const [x, y] = this._xy(this.destination.lat, this.destination.lon);
      g.fillStyle = "#ff5d5d"; g.beginPath(); g.arc(x, y, 9, 0, 7); g.fill();
      g.strokeStyle = "#fff"; g.lineWidth = 2; g.stroke();
      if (this.destination.name) this._label(String(this.destination.name).slice(0, 28), x + 12, y + 4);
    }
    if (this.position) {
      const [x, y] = this._xy(this.position.lat, this.position.lon);
      if (this.position.accuracy) {
        g.fillStyle = "rgba(80,160,255,0.18)"; g.beginPath(); g.arc(x, y, this.position.accuracy / this.mpp, 0, 7); g.fill();
      }
      g.fillStyle = this.position.simulated ? "#c084fc" : "#4ea8ff"; g.beginPath(); g.arc(x, y, 8, 0, 7); g.fill();
      g.strokeStyle = "#fff"; g.lineWidth = 2; g.stroke();
    }
    // scale bar + attribution
    const nice = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000].find((m) => m / this.mpp > 60) || 5000;
    g.fillStyle = "#fff"; g.fillRect(10, this.h - 22, nice / this.mpp, 3);
    this._label(nice >= 1000 ? `${nice / 1000} km` : `${nice} m`, 10, this.h - 28);
    this._label(d.attribution || "© OpenStreetMap contributors", this.w - 8, this.h - 8, "right");
  }
  _label(t, x, y, align) {
    const g = this.g;
    g.font = "12px system-ui, sans-serif"; g.textAlign = align || "left";
    g.fillStyle = "rgba(0,0,0,0.6)"; const w = g.measureText(t).width;
    g.fillRect(align === "right" ? x - w - 4 : x - 2, y - 12, w + 6, 16);
    g.fillStyle = "#fff"; g.fillText(t, x, y);
    g.textAlign = "left";
  }
}
