"""Build NeuroSonic's offline map package from raw OpenStreetMap (Overpass JSON) downloads.

Input  (raw, as downloaded):  datasets/osm/<region>/{<region>_highways,_features,_places}.osm.json
Output (offline package):     maps/<region>/{map.json, graph.json, places.json, manifest.json}

  map.json     display layers (roads by class, water, green/landuse areas, railways) + coverage bbox
  graph.json   walking graph: nodes [lat, lon] and edges [a, b, length_m, way_index]; ways [name, highway]
  places.json  named places for offline search (name, name:en, name:ta, kind, lat, lon)
  manifest.json  provenance: source files + SHA-256, Overpass data timestamp, bbox, counts, licence (ODbL)

Walking network rules: every OSM highway except motorway/motorway_link/construction/proposed/raceway/bus_guideway,
and except ways tagged foot=no or access=private/no (unless foot=yes/designated/permissive). Trunk and primary roads
are kept (in Vellore many have no separate footway) but flagged "major" so guidance can mention it.

  python tools/build_offline_map.py --region vellore --raw ../datasets/osm/vellore --bbox 12.86,79.07,13.00,79.21
"""
import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_HIGHWAYS = {"motorway", "motorway_link", "construction", "proposed", "raceway", "bus_guideway", "platform"}
MAJOR = {"trunk", "trunk_link", "primary", "primary_link"}
ROAD_CLASS = {  # display class
    "trunk": "major", "trunk_link": "major", "primary": "major", "primary_link": "major", "motorway": "major",
    "secondary": "medium", "secondary_link": "medium", "tertiary": "medium", "tertiary_link": "medium",
    "footway": "foot", "path": "foot", "pedestrian": "foot", "steps": "foot", "cycleway": "foot", "track": "foot",
}


def haversine(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walkable(tags):
    hw = tags.get("highway")
    if hw is None or hw in EXCLUDED_HIGHWAYS or tags.get("area") == "yes":
        return False
    foot, access = tags.get("foot"), tags.get("access")
    if foot in ("yes", "designated", "permissive"):
        return True
    return not (foot == "no" or access in ("private", "no"))


def load(p):
    d = json.loads(Path(p).read_text(encoding="utf-8"))
    if d.get("remark"):
        raise SystemExit(f"{p}: Overpass reported an incomplete result: {d['remark']}")
    return d


def r6(x):
    return round(x, 6)


def build(region, raw, bbox, out):
    s, w, n, e = bbox
    files = {k: raw / f"{region}_{k}.osm.json" for k in ("highways", "features", "places")}
    for k, p in files.items():
        if not p.exists():
            raise SystemExit(f"missing raw file: {p}")
    hw = load(files["highways"])
    feats = load(files["features"])
    places_raw = load(files["places"])

    # ---------------- walking graph + road display layer
    coords = {el["id"]: (el["lat"], el["lon"]) for el in hw["elements"] if el["type"] == "node"}
    node_index, nodes, edges, ways_meta = {}, [], [], []
    roads = {"major": [], "medium": [], "minor": [], "foot": []}
    skipped = 0
    for el in hw["elements"]:
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        line = [coords[i] for i in el["nodes"] if i in coords]
        if len(line) >= 2:
            roads[ROAD_CLASS.get(tags.get("highway"), "minor")].append([[r6(lon), r6(lat)] for lat, lon in line])
        if not walkable(tags):
            skipped += 1
            continue
        wi = len(ways_meta)
        ways_meta.append([tags.get("name") or tags.get("name:en") or "", tags.get("highway", "")])
        prev = None
        for nid in el["nodes"]:
            if nid not in coords:
                prev = None
                continue
            if nid not in node_index:
                node_index[nid] = len(nodes)
                nodes.append([r6(coords[nid][0]), r6(coords[nid][1])])
            cur = node_index[nid]
            if prev is not None and prev != cur:
                (la1, lo1), (la2, lo2) = nodes[prev], nodes[cur]
                edges.append([prev, cur, round(haversine(la1, lo1, la2, lo2), 2), wi])
            prev = cur

    # ---------------- other display layers
    layers = {"water": [], "waterline": [], "green": [], "landuse": [], "rail": []}
    for el in feats["elements"]:
        tags = el.get("tags", {})
        geom = el.get("geometry")
        if el["type"] == "relation":
            for m in el.get("members", []):
                if m.get("role") == "outer" and m.get("geometry"):
                    layers["water"].append([[r6(p["lon"]), r6(p["lat"])] for p in m["geometry"]])
            continue
        if not geom or len(geom) < 2:
            continue
        pts = [[r6(p["lon"]), r6(p["lat"])] for p in geom]
        if tags.get("natural") == "water" or tags.get("landuse") in ("reservoir", "basin"):
            layers["water"].append(pts)
        elif "waterway" in tags:
            layers["waterline"].append(pts)
        elif "railway" in tags:
            layers["rail"].append(pts)
        elif tags.get("leisure") in ("park", "garden", "pitch", "playground") or tags.get("landuse") in (
                "grass", "forest", "meadow", "recreation_ground", "farmland", "orchard") or tags.get("natural") in ("wood", "scrub", "grassland"):
            layers["green"].append(pts)
        elif "landuse" in tags or "amenity" in tags:
            layers["landuse"].append(pts)

    # ---------------- places for search
    places, seen = [], set()
    for el in places_raw["elements"]:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("name:en")
        if not name:
            continue
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        if lat is None or not (s <= lat <= n and w <= lon <= e):
            continue
        kind = next((f"{k}={tags[k]}" for k in ("amenity", "shop", "tourism", "healthcare", "office", "place", "railway",
                                                 "public_transport", "highway", "building", "leisure", "historic") if k in tags), "place")
        key = (name.lower(), round(lat, 4), round(lon, 4))
        if key in seen:
            continue
        seen.add(key)
        places.append({"name": name, "name_en": tags.get("name:en"), "name_ta": tags.get("name:ta"), "kind": kind,
                       "lat": r6(lat), "lon": r6(lon)})
    # street names are searchable too (centre point of the longest piece of each named street)
    streets = {}
    for el in hw["elements"]:
        if el["type"] == "way" and el.get("tags", {}).get("name"):
            line = [coords[i] for i in el["nodes"] if i in coords]
            if line:
                nm = el["tags"]["name"]
                if nm not in streets or len(line) > len(streets[nm]):
                    streets[nm] = line
    for nm, line in streets.items():
        lat, lon = line[len(line) // 2]
        places.append({"name": nm, "name_en": None, "name_ta": None, "kind": "street", "lat": r6(lat), "lon": r6(lon)})

    out.mkdir(parents=True, exist_ok=True)
    meta = {"region": region, "bbox": {"south": s, "west": w, "north": n, "east": e},
            "attribution": "© OpenStreetMap contributors (ODbL 1.0)", "osm_timestamp": hw["osm3s"]["timestamp_osm_base"]}
    (out / "map.json").write_text(json.dumps({**meta, "roads": roads, **layers}, separators=(",", ":")), encoding="utf-8")
    (out / "graph.json").write_text(json.dumps({**meta, "nodes": nodes, "edges": edges, "ways": ways_meta},
                                               separators=(",", ":")), encoding="utf-8")
    (out / "places.json").write_text(json.dumps({**meta, "places": places}, ensure_ascii=False, separators=(",", ":")),
                                     encoding="utf-8")
    manifest = {
        **meta, "built": time.strftime("%Y-%m-%d %H:%M:%S"), "licence": "Open Database License (ODbL) 1.0 - "
        "https://www.openstreetmap.org/copyright. Attribution required: '© OpenStreetMap contributors'.",
        "source": {"provider": "Overpass API (overpass-api.de)", "files": {
            p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)} for p in files.values()}},
        "not_included": ["buildings (Overpass download failed: HTTP 502 'server at capacity'; mirror unreachable)"],
        "counts": {"graph_nodes": len(nodes), "graph_edges": len(edges), "walkable_ways": len(ways_meta),
                   "excluded_ways": skipped, "places": len(places), "named_streets": len(streets),
                   **{f"road_lines_{k}": len(v) for k, v in roads.items()}, **{k: len(v) for k, v in layers.items()}},
        "outputs": {f.name: f.stat().st_size for f in (out / "map.json", out / "graph.json", out / "places.json")},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="vellore")
    ap.add_argument("--raw", type=Path, default=ROOT.parent / "datasets" / "osm" / "vellore")
    ap.add_argument("--bbox", default="12.86,79.07,13.00,79.21", help="south,west,north,east (the downloaded box)")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    bbox = tuple(float(x) for x in a.bbox.split(","))
    m = build(a.region, a.raw, bbox, a.out or ROOT / "maps" / a.region)
    print(json.dumps({"counts": m["counts"], "outputs": m["outputs"], "osm_timestamp": m["osm_timestamp"]}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
