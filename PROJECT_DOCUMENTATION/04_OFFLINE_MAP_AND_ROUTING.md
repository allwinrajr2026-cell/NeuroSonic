# 4. Offline map: OpenStreetMap data, place search and A* routing

## 4.1 Problem

The user must be able to search for a place in Vellore and get a walking route **without internet**. Online
services such as Google Maps or OSRM servers are not allowed in the offline design.

## 4.2 Data source: OpenStreetMap via the Overpass API

* **What it is:** OpenStreetMap (OSM) is a free, community-made world map. Its data model has **nodes** (points
  with latitude/longitude), **ways** (ordered lists of nodes, e.g. a street) and **relations**. Each carries
  key=value **tags** (`highway=residential`, `name=Gandhi Road`).
* **Licence:** Open Database License (ODbL) 1.0. Attribution "© OpenStreetMap contributors" is required and is
  drawn on the map (`mapview.js::_draw`).
* **Download:** three queries to the Overpass API on 2026-11-02, for the bounding box
  **12.86–13.00 °N, 79.07–79.21 °E** (about 15.2 × 15.5 km: Vellore city, Fort, CMC, new bus stand, Katpadi,
  VIT, Sathuvachari, Bagayam). Stored in `F:\Projects\WOAD-Research\datasets\osm\vellore\`:

| File | Bytes | Content |
|---|---|---|
| `vellore_highways.osm.json` | 4,164,985 | all `highway=*` ways with their nodes (6,710 ways, 31,540 nodes) |
| `vellore_features.osm.json` | 548,032 | landuse, natural, water, waterways, railways, leisure, amenity areas |
| `vellore_places.osm.json` | 171,359 | named nodes and named non-road features |
| buildings | — | **not downloaded**: Overpass returned HTTP 502 "server at capacity"; the mirror was unreachable |

The OSM data timestamp is 2026-11-02T06:32Z.

*Why Overpass and not Geofabrik?* Geofabrik only offers whole regions (all of southern India, hundreds of MB)
and would need extra tools to cut out Vellore. Overpass returns exactly the bounding box.

## 4.3 Building the offline package: `tools/build_offline_map.py`

`build()` (L72–190) converts the raw files into four files in `maps/vellore/`:

| File | Bytes | Content |
|---|---|---|
| `map.json` | 1,052,137 | display layers: roads (major / medium / minor / foot), water, waterlines, green, landuse, rail, bbox, attribution |
| `graph.json` | 1,646,391 | walking graph: `nodes` [[lat, lon]], `edges` [[a, b, length_m, way_index]], `ways` [[name, highway]] |
| `places.json` | 96,374 | 813 searchable names (OSM places + 194 named streets) |
| `manifest.json` | — | provenance: raw file SHA-256s, OSM timestamp, counts, licence, what is not included |

* **Walking filter** (`walkable`, L51–58):
  * every `highway` is kept except those in `EXCLUDED_HIGHWAYS` (L26: motorway, construction, proposed, …);
  * ways tagged `foot=no` or `access=private|no` are dropped, unless also tagged `foot=yes|designated|permissive`.
  * 27 of 6,710 ways were excluded.
  * Trunk and primary roads are kept but flagged "major", because in this data many have no separate footway.
* **Edge length:** the haversine distance between consecutive nodes (`haversine` L35–40), rounded to cm.

**Result:** 31,439 graph nodes and 34,939 undirected edges. 99.2 % of the nodes form one connected network.

## 4.4 Loading and coverage: `neurosonic/maps.py::OfflineMap`

* **`__init__` (L59–90):**
  * loads `graph.json` into a NumPy array `nodes` and an adjacency list `adj[u] = [(v, length, way), …]`, in
    both directions;
  * loads `places.json`;
  * computes **connected components** with an iterative depth-first search, and remembers the main component.
* **`in_coverage` (L99–101):** a bounding-box test. Outside the box, routing raises `MapError` ("outside the
  offline map area"), and the client speaks it.
* **`nearest_node` (L103–108):** vectorised nearest neighbour. It computes the squared equirectangular distance
  to all 31,439 nodes, (Δlat)² + (Δlon·cos φ)², takes `argmin`, then reports the true haversine distance.
  Optionally restricted to one component.

## 4.5 Place search: `OfflineMap.search` (L111–137)

This is a simple ranked text search over `name`, `name:en` and `name:ta`:

* exact match = 100;
* prefix = 80;
* substring = 60;
* all query words contained = 40.

Ties are broken by distance from the user (haversine) when a position is known. There's no fuzzy matching here;
the sound-alike matching for voice input lives in `voicecmd.py` (document 06).

## 4.6 Routing algorithm: A* search

### Theory (for the viva)

* **The problem:** find the shortest path in a weighted graph. Nodes are street points; edge weights are
  lengths in metres.
* **Dijkstra's algorithm** expands nodes in order of their known distance g(n) from the start. It is correct,
  but explores in all directions.
* **A\*** expands nodes in order of f(n) = g(n) + h(n), where h(n) is a *heuristic* estimate of the remaining
  distance.
  * If h never over-estimates the true remaining distance (it is **admissible**), A* still returns the optimal
    path.
  * It explores far fewer nodes, because it is pulled towards the goal.
* **Our heuristic:** h(n) = the **great-circle (haversine) straight-line distance** from n to the destination.
  A walking path along streets can never be shorter than the straight line, so h is admissible. It is also
  **consistent**: h(u) ≤ length(u,v) + h(v), by the triangle inequality.

### Implementation: `OfflineMap._astar` (L184–205)

```python
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
```

* `heapq` is a binary min-heap ordered by f = g + h.
* The search stops as soon as the target is popped.
* `prev` stores the predecessor, the edge length and the way index, which are needed to rebuild the path and
  to name the streets.
* "Lazy deletion": stale heap entries are skipped through the `done` set.

### Route assembly: `OfflineMap.route` (L140–182)

1. Reject a start or destination outside coverage.
2. Snap both points to the nearest graph node. If they are in different components, snap the off-network end to
   the main network instead and add a **note**. Example: the paths inside **Vellore Fort** are an island in the
   OSM data, so the nearest connected street is 380 m away.
3. Fail if the snap distance exceeds `MAX_SNAP_M` = 250 m (or `MAX_ISLAND_SNAP_M` = 600 m for islands).
4. Run `_astar` and walk `prev` back from the target to rebuild the node path.
5. Build the output:
   * the polyline (start point + nodes + end point);
   * the distance (path + both snap distances);
   * the duration at `WALK_SPEED_MPS` = 1.2 m/s (about 4.3 km/h);
   * the metres on major roads;
   * the steps.

### Turn-by-turn steps: `OfflineMap._steps` (L222–313)

* **Grouping:** consecutive edges are grouped while the street name stays the same and the bearing change is
  below 60°. Unnamed segments are grouped while the change is below 35°, and tiny unnamed connectors are
  absorbed.
* **Turn words:** at each new group, the bearing change is turned into a word by `turn_word` (L41–51):
  * < 25° "continue straight";
  * < 60° "bear left/right";
  * < 135° "turn left/right";
  * otherwise "make a sharp … turn".
* **Example output:** "Turn right onto Krishnagiri - Ranipet Road (Old NH46), then continue for 610 metres.
  This is a major road; take care."

## 4.7 Verification (actual results)

| Check | Result | Where |
|---|---|---|
| A* returns the true shortest path | equals an independent Dijkstra on random pairs: max difference 0.000 m on 40 pairs (ad-hoc check); 8 pairs re-checked in the suite | `tests/test_voice_and_map.py::test_route_is_shortest_path` |
| Speed | mean 9.5 ms per A* query vs 13.0 ms for Dijkstra (40 random pairs, laptop CPU, ad-hoc measurement) | session measurement 2026-11-02 |
| Sample routes | Vellore Fort → CMC Hospital 1,981 m (straight line 786 m); new bus stand → CMC Hospital 1,981 m; Katpadi → VIT 3,031 m | ad-hoc runs |
| Works with internet blocked | yes, 0 network attempts | `TestOfflineMap.test_works_without_internet` |
| Outside coverage | `MapError`, HTTP 400 "outside the offline map area" | `test_route_content_and_island_note`, `test_map_endpoints` |
| Full browser walk | Katpadi → CMC Hospital, 264 simulated 20 m steps, spoken steps, arrival announced, 0 external requests | `tests/js/ui_voice_map_cdp.mjs` (PASS 2026-11-02) |

## 4.8 Limitations

* OSM data quality:
  * only 316 of 6,710 street segments are named, so instructions often say "the unnamed road";
  * only 193 footways are mapped;
  * there are no pavements, crossings or traffic data.
* Coverage is a box, not the municipal boundary. Buildings are missing.
* There are no pedestrian costs: every metre counts the same on a footway or a trunk road. Major-road metres
  are only *reported*.
* **No real walking test has been done.**

## 4.9 Likely questions

* *Why is A\* better than Dijkstra here?* Both give the same optimal path, and our test shows they are equal.
  A* expands fewer nodes because the haversine heuristic guides it towards the goal (9.5 vs 13.0 ms measured).
* *Is your heuristic admissible?* Yes. The straight-line great-circle distance is a lower bound of any path
  length on the Earth's surface.
* *What is the time complexity?* O((V + E) log V) with a binary heap in the worst case, the same as Dijkstra;
  in practice fewer nodes are expanded.
* *How do you find the nearest street to the user?* A vectorised nearest-node search over all nodes
  (`nearest_node`), linear in V (about 31k). That's fast enough in NumPy; a k-d tree would be the next step for
  bigger maps.
