"""Offline map services: coverage check, place search and walking routes (A*) on a local OSM extract.

Everything here reads local files (maps/<region>/); nothing uses the network. Limits (stated honestly):
  * Routes follow the OSM street graph. In Vellore few footways/sidewalks are mapped, so routes mostly follow roads,
    and the data says nothing about pavement quality, crossings, traffic or obstacles.
  * Coverage = the downloaded bounding box. Outside it, no offline route or search is possible.
  * Turn instructions are derived from geometry (angles) and OSM names; many streets are unnamed in OSM.
"""
import heapq
import json
import math
from pathlib import Path

import numpy as np

WALK_SPEED_MPS = 1.2          # ~4.3 km/h; for time estimates only
MAX_SNAP_M = 250.0            # start/end must be within this distance of the walking network
MAX_ISLAND_SNAP_M = 600.0     # ...or of the main network when the nearest path is on a disconnected island (noted)
MAJOR = {"trunk", "trunk_link", "primary", "primary_link"}


class MapError(ValueError):
    pass


def haversine(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def bearing(lat1, lon1, lat2, lon2):
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1)))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def turn_word(delta):
    """delta = new bearing - old bearing, normalised to (-180, 180]."""
    a = abs(delta)
    if a < 25:
        return "continue straight"
    side = "right" if delta > 0 else "left"
    if a < 60:
        return f"bear {side}"
    if a < 135:
        return f"turn {side}"
    return f"make a sharp {side} turn"


def fmt_m(m):
    return f"{int(round(m / 10.0) * 10)} metres" if m < 1000 else f"{m / 1000:.1f} kilometres"


class OfflineMap:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.manifest = json.loads((self.folder / "manifest.json").read_text(encoding="utf-8"))
        g = json.loads((self.folder / "graph.json").read_text(encoding="utf-8"))
        self.bbox = g["bbox"]
        self.nodes = np.asarray(g["nodes"], dtype=np.float64)              # [lat, lon]
        self.ways = g["ways"]                                               # [name, highway]
        self.adj = [[] for _ in range(len(self.nodes))]
        for a, b, length, wi in g["edges"]:
            self.adj[a].append((b, length, wi))
            self.adj[b].append((a, length, wi))
        self.places = json.loads((self.folder / "places.json").read_text(encoding="utf-8"))["places"]
        self._cos = math.cos(math.radians((self.bbox["south"] + self.bbox["north"]) / 2))
        # connected components: OSM data contains small islands (e.g. paths inside Vellore Fort not linked to the
        # street network); endpoints on an island are snapped to the main network instead
        self.comp = np.full(len(self.nodes), -1, dtype=np.int32)
        sizes = []
        for start in range(len(self.nodes)):
            if self.comp[start] >= 0:
                continue
            cid, stack, n = len(sizes), [start], 0
            self.comp[start] = cid
            while stack:
                u = stack.pop()
                n += 1
                for v, _, _ in self.adj[u]:
                    if self.comp[v] < 0:
                        self.comp[v] = cid
                        stack.append(v)
            sizes.append(n)
        self.main_comp = int(np.argmax(sizes)) if sizes else 0
        self.main_share = (max(sizes) / len(self.nodes)) if sizes else 0.0

    # ------------------------------------------------------------------ info / coverage
    def info(self):
        c = self.manifest["counts"]
        return {"available": True, "region": self.manifest["region"], "bbox": self.bbox,
                "attribution": self.manifest["attribution"], "osm_timestamp": self.manifest["osm_timestamp"],
                "graph_nodes": c["graph_nodes"], "places": c["places"], "main_network_share": round(self.main_share, 3), "not_included": self.manifest.get("not_included", [])}

    def in_coverage(self, lat, lon):
        b = self.bbox
        return b["south"] <= lat <= b["north"] and b["west"] <= lon <= b["east"]

    def nearest_node(self, lat, lon, component=None):
        d2 = (self.nodes[:, 0] - lat) ** 2 + ((self.nodes[:, 1] - lon) * self._cos) ** 2
        if component is not None:
            d2 = np.where(self.comp == component, d2, np.inf)
        i = int(np.argmin(d2))
        return i, haversine(lat, lon, self.nodes[i, 0], self.nodes[i, 1])

    # ------------------------------------------------------------------ search
    def search(self, query, limit=10, near=None):
        q = " ".join(str(query).lower().split())
        if len(q) < 2:
            return []
        words = q.split()
        out = []
        for p in self.places:
            names = [x for x in (p["name"], p.get("name_en"), p.get("name_ta")) if x]
            best = 0
            for nm in names:
                low = nm.lower()
                if low == q:
                    score = 100
                elif low.startswith(q):
                    score = 80
                elif q in low:
                    score = 60
                elif all(wd in low for wd in words):
                    score = 40
                else:
                    continue
                best = max(best, score)
            if best:
                dist = haversine(near[0], near[1], p["lat"], p["lon"]) if near else None
                out.append((best, -(dist or 0), p, dist))
        out.sort(key=lambda t: (-t[0], -t[1], t[2]["name"]))
        return [{**p, "distance_m": None if d is None else round(d)} for _, _, p, d in out[:limit]]

    # ------------------------------------------------------------------ routing
    def route(self, start, end):
        """start/end: (lat, lon). Returns dict with polyline [[lat, lon]], distance, duration, steps."""
        for name, (lat, lon) in (("start", start), ("destination", end)):
            if not self.in_coverage(lat, lon):
                raise MapError(f"The {name} is outside the offline map area ({self.manifest['region']}).")
        s, ds = self.nearest_node(*start)
        t, dt = self.nearest_node(*end)
        notes, limit = [], {"start": MAX_SNAP_M, "destination": MAX_SNAP_M}
        if self.comp[s] != self.comp[t]:   # different islands: use the main street network for the off-network end(s)
            for which in ("start", "destination"):
                i = s if which == "start" else t
                if self.comp[i] != self.main_comp:
                    j, dj = self.nearest_node(*(start if which == "start" else end), component=self.main_comp)
                    notes.append(f"The nearest mapped path to the {which} is not connected to the street network in "
                                 f"the map data; the route uses the nearest connected street, {fmt_m(dj)} away.")
                    limit[which] = MAX_ISLAND_SNAP_M
                    if which == "start":
                        s, ds = j, dj
                    else:
                        t, dt = j, dj
        if ds > limit["start"]:
            raise MapError(f"The start is {fmt_m(ds)} from the nearest mapped path; no offline route.")
        if dt > limit["destination"]:
            raise MapError(f"The destination is {fmt_m(dt)} from the nearest mapped path; no offline route.")
        prev = self._astar(s, t)
        if prev is None:
            raise MapError("No walking connection between these points in the offline map data.")
        path = [t]
        while path[-1] != s:
            path.append(prev[path[-1]][0])
        path.reverse()
        legs = []   # (from, to, length, way index)
        for a, b in zip(path, path[1:]):
            length, wi = prev[b][1], prev[b][2]
            legs.append((a, b, length, wi))
        dist = sum(l[2] for l in legs) + ds + dt
        poly = [[float(start[0]), float(start[1])]] + [[float(self.nodes[i, 0]), float(self.nodes[i, 1])] for i in path] + \
               [[float(end[0]), float(end[1])]]
        steps = self._steps(legs, ds, dt)
        return {"distance_m": round(dist), "duration_s": round(dist / WALK_SPEED_MPS), "polyline": poly, "steps": steps,
                "snap_m": {"start": round(ds), "destination": round(dt)}, "notes": notes,
                "major_road_m": round(sum(l[2] for l in legs if self.ways[l[3]][1] in MAJOR)),
                "source": "offline OSM walking graph", "attribution": self.manifest["attribution"]}

    def _astar(self, s, t):
        tl, tn = self.nodes[t]
        lat, lon = self.nodes[:, 0], self.nodes[:, 1]
        best = {s: 0.0}
        prev = {s: (None, 0.0, None)}
        heap = [(0.0, s)]
        done = set()
        while heap:
            _, u = heapq.heappop(heap)
            if u == t:
                return prev
            if u in done:
                continue
            done.add(u)
            for v, length, wi in self.adj[u]:
                nd = best[u] + length
                if nd < best.get(v, math.inf):
                    best[v] = nd
                    prev[v] = (u, length, wi)
                    h = haversine(lat[v], lon[v], tl, tn)
                    heapq.heappush(heap, (nd + h, v))
        return None

    # turn detection compares the walking direction over this distance before and after a junction, so small
    # wiggles in the OSM geometry are not announced as turns
    TURN_PROBE_M = 20.0
    TURN_MIN_DEG = 30.0      # smaller direction changes are not announced as turns
    MICRO_STEP_M = 12.0      # shorter steps are merged into the next one (no "walk 10 metres" instructions)

    def _point_at(self, cum, pts, s):
        """Point (lat, lon) at path distance s, by linear interpolation along the node path."""
        s = min(max(s, 0.0), cum[-1])
        k = int(np.searchsorted(cum, s, side="right")) - 1
        k = min(max(k, 0), len(pts) - 2)
        seg = cum[k + 1] - cum[k]
        f = 0.0 if seg <= 0 else (s - cum[k]) / seg
        return (pts[k][0] + (pts[k + 1][0] - pts[k][0]) * f, pts[k][1] + (pts[k + 1][1] - pts[k][1]) * f)

    def _steps(self, legs, ds, dt):
        """Turn the leg list into spoken steps.

        1. Candidate step boundaries are the places where the path changes from one OSM way to another.
        2. At each, the turn angle is measured between the direction over ~20 m before and ~20 m after the
           junction. A boundary is kept if the angle is >= 30 deg (a turn) or a *named* street begins
           ("Continue onto X"); otherwise the two parts are merged.
        3. Steps shorter than 12 m are merged into the next step (the net turn is recomputed).
        """
        if not legs:
            return [{"text": "You have reached the destination area.", "action": "You have arrived", "at": None,
                     "distance_m": 0, "street": None, "highway": None, "turn": "arrive"}]
        pts = [tuple(self.nodes[legs[0][0]])] + [tuple(self.nodes[b]) for _, b, _, _ in legs]
        cum = np.concatenate([[0.0], np.cumsum([l for _, _, l, _ in legs])])
        P = self.TURN_PROBE_M

        def turn_angle(s):
            a = self._point_at(cum, pts, s - P)
            j = self._point_at(cum, pts, s)
            d = self._point_at(cum, pts, s + P)
            if a == j or j == d:
                return 0.0
            return (bearing(*j, *d) - bearing(*a, *j) + 540) % 360 - 180

        # 1. runs of legs on the same way
        runs = []
        for k, (a, b, length, wi) in enumerate(legs):
            if runs and runs[-1]["wi"] == wi:
                runs[-1]["length"] += length
                runs[-1]["end_k"] = k + 1
            else:
                runs.append({"wi": wi, "start_k": k, "end_k": k + 1, "length": length})
        # 2. merge runs into steps
        steps = []
        for r in runs:
            name, hw = self.ways[r["wi"]]
            s0 = float(cum[r["start_k"]])
            if not steps:
                steps.append({"name": name, "highway": hw, "length": r["length"], "start_s": s0, "angle": None})
                continue
            ang = turn_angle(s0)
            prev = steps[-1]
            new_name = bool(name) and name != prev["name"]
            if abs(ang) >= self.TURN_MIN_DEG or new_name:
                steps.append({"name": name, "highway": hw, "length": r["length"], "start_s": s0, "angle": ang})
            else:
                prev["length"] += r["length"]
                if hw in MAJOR:
                    prev["highway"] = hw
        # 3. merge micro-steps into the following step (net turn from before the micro-step to after it)
        merged = []
        i = 0
        while i < len(steps):
            st = steps[i]
            if 0 < i < len(steps) - 1 and st["length"] < self.MICRO_STEP_M:
                nxt = steps[i + 1]
                nxt["start_s"] = st["start_s"]
                nxt["length"] += st["length"]
                nxt["angle"] = turn_angle(st["start_s"] + st["length"] / 2.0)
                if abs(nxt["angle"]) < self.TURN_MIN_DEG and not (nxt["name"] and nxt["name"] != merged[-1]["name"]):
                    merged[-1]["length"] += nxt["length"]          # the jog cancels out: just keep walking
                    i += 2
                    continue
                i += 1
                continue
            merged.append(st)
            i += 1
        out = []
        for idx, st in enumerate(merged):
            on = f" on {st['name']}" if st["name"] else ""
            onto = f" onto {st['name']}" if st["name"] else ""
            major = " This is a main road. Take care." if st["highway"] in MAJOR else ""
            at = self._point_at(cum, pts, st["start_s"])
            if idx == 0:
                head = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][
                    int((bearing(*at, *self._point_at(cum, pts, st["start_s"] + P)) + 22.5) // 45) % 8]
                action = f"Head {head}{on}"
                text = f"{action} for {fmt_m(st['length'])}.{major}"
                turn = None
            else:
                ang = st["angle"]
                turn = turn_word(ang) if abs(ang) >= self.TURN_MIN_DEG else "continue"
                action = (f"Continue{onto}" if turn == "continue" else f"{turn.capitalize()}{onto}")
                text = f"{action} and walk {fmt_m(st['length'])}.{major}"
            out.append({"text": text, "action": action, "at": [float(at[0]), float(at[1])],
                        "distance_m": round(st["length"]), "street": st["name"] or None, "highway": st["highway"],
                        "turn": turn, "turn_angle": None if st["angle"] is None else round(st["angle"])})
        out.append({"text": "You have reached the destination area." if dt < 30 else
                    f"The destination is about {fmt_m(dt)} from the end of the mapped path.",
                    "action": "You have arrived", "at": None, "distance_m": 0, "street": None, "highway": None,
                    "turn": "arrive", "turn_angle": None})
        return out
