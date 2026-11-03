# Live camera awareness detector (ordinary RGB camera)

| | |
|---|---|
| Weights | `ssdlite320_mobilenet_v3_large_coco-a79551df.pth`, 14,069,355 bytes (SHA-256 starts `a79551df`, matching the hash in the file name), downloaded 2026-11-02 from download.pytorch.org |
| Model | torchvision `ssdlite320_mobilenet_v3_large`, COCO, 3.4 M parameters, **box mAP 21.3 on COCO val2017** (a small, fast, modest detector) |
| Licence | torchvision code and weights BSD-3-Clause; COCO annotations CC BY 4.0 |
| Speed | about 40–55 ms per 320 px frame on this laptop's CPU |

## Use in NeuroSonic (`neurosonic/awareness.py`)

This is **not** the WOAD model. WOAD needs CS30 near-IR + depth, which ordinary cameras don't provide.

* **Classes announced:** only obstacle-relevant COCO classes: person, bicycle, car, motorcycle, bus, truck,
  dog, cow, horse, cat, bench, chair, sofa, table, potted plant, fire hydrant, stop sign, traffic light,
  suitcase, umbrella, refrigerator, TV, microwave.
* **It cannot detect** steps, kerbs, holes, poles, walls, barriers or uneven ground, and it gives **no
  distance**.
* **Confirmation:** alerts go through the WOAD alert engine, with a 2-of-3 frame confirmation, positions and
  cooldowns.
* **"Caution" alerts:** used when an object is in the middle third and covers at least 25 % of the image.
  That's an unvalidated heuristic for "large in view", not a distance.
* **Carrying mode:** chest mode says "ahead / on the left". Handheld mode says "in camera view, left" and never
  "ahead".

## Measured

* On real `detec_test` frames, which are near-IR images rather than colour: people and bicycles detected and
  confirmed alerts spoken.
* One false "Fire hydrant" (0.51) was seen.
* Through a real browser (Chrome fake camera), a spoken "Person …" alert followed.

**Accuracy on real phone-camera video in Vellore has not been measured.** It must not be relied on for safety.
