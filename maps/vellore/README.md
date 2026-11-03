# Offline map package: Vellore (Tamil Nadu, India)

Built by `tools/build_offline_map.py` from OpenStreetMap data. Provenance details are in `manifest.json`.

## Coverage

* Bounding box **12.86–13.00 °N, 79.07–79.21 °E**, about 15.2 km × 15.5 km.
* That covers Vellore city centre, Vellore Fort, CMC Hospital, the new bus stand, Katpadi (including Katpadi
  Junction station), VIT, Sathuvachari, Gandhi Nagar and Bagayam.
* **Anything outside this box is not included.** The app says so and offers only straight-line guidance there.

The raw downloads are in `../../../datasets/osm/vellore/`. They came from the Overpass API on 2026-11-02, with OSM
data timestamp 2026-11-02T06:32Z:

| File | Bytes | Content |
|---|---|---|
| `vellore_highways.osm.json` | 4,164,985 | all `highway=*` ways + their nodes (6,710 ways, 31,540 nodes) |
| `vellore_features.osm.json` | 548,032 | landuse, natural, water, waterways, railways, leisure, amenity areas (with geometry) |
| `vellore_places.osm.json` | 171,359 | named nodes and named non-road features (for search) |
| buildings | — | **not downloaded**: Overpass answered HTTP 502 "server at capacity", and the mirror overpass.kumi.systems was unreachable |

## Package (offline, used by the app)

| File | Bytes | Content |
|---|---|---|
| `map.json` | 1,052,137 | display layers: roads (major/medium/minor/foot), water, waterways, green, landuse, rail |
| `graph.json` | 1,646,391 | walking graph: 31,439 nodes and 34,939 edges from 6,683 walkable ways (27 excluded: private, `foot=no`, construction…) |
| `places.json` | 96,374 | 813 searchable names (619 places + 194 named streets) |

## Known data limits

* **99.2 %** of the walking graph is one connected network. 12 small islands exist. One example is the paths
  inside Vellore Fort, which are not linked to the streets in OSM. Routes snap such endpoints to the nearest
  connected street, up to 600 m away, and say so.
* Only 316 of 6,710 street segments carry a name, and only 193 are mapped footways. Routes mostly follow roads,
  and instructions often say "the unnamed road".
* Routes treat trunk/primary roads as walkable (there are few alternatives in the data) and warn "This is a
  major road; take care". The data has no information on pavements, crossings, traffic, construction or obstacles.
* Coverage is a box, not the municipal boundary.

## Licence

© OpenStreetMap contributors, **Open Database License (ODbL) 1.0**, https://www.openstreetmap.org/copyright.
The attribution is shown on the map. Any redistributed derived database must stay under ODbL.
