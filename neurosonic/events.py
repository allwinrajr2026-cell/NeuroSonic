"""Conservative temporal events from tracks (2026-11-03): an object ENTERING the walking path, or CROSSING in front.

Rules (all on motion RELATIVE TO THE BACKGROUND from neurosonic/tracking.py, so camera movement is compensated):
  * a track must be confirmed: >= MIN_HITS updates over >= MIN_AGE_S seconds;
  * no event while the camera moves too much (any frame in the window with shift > MAX_CAM_SHIFT of the image width,
    or scale change > MAX_CAM_SCALE, or no reliable camera-motion estimate): the motion of objects cannot be separated
    from the user's own movement then;
  * no event in the states UNCERTAIN / CAMERA_UNAVAILABLE (image unusable) or BLOCKED_VIEW (the urgent "Stop" message
    is already the right warning);
  * ENTERING: within the last WINDOW_S the box was outside the walking-path region and now overlaps it, and its
    horizontal relative speed towards the region centre is >= ENTER_SPEED (image widths per second);
  * CROSSING: the centre moved across the middle of the image (from < 0.35 to > 0.65 of the width or back) within
    CROSS_WINDOW_S, with relative horizontal speed >= CROSS_SPEED, and the box reaches the lower half of the image;
  * each event is spoken at most once per track, with at least GLOBAL_GAP_S between event announcements.
"Approaching" (objects coming straight at the user) is deliberately NOT announced: with a moving phone camera the
growth of a box is dominated by the user's own walking, and this would cause false alarms (future work, needs depth).
No message gives a distance or says that a path is safe.
"""
from .pathguide import BLOCKED_VIEW, CAMERA_UNAVAILABLE, UNCERTAIN, box_path_overlap

MIN_HITS = 3
MIN_AGE_S = 0.4
WINDOW_S = 1.5
CROSS_WINDOW_S = 3.0
ENTER_SPEED = 0.12
CROSS_SPEED = 0.15
MAX_CAM_SHIFT = 0.06
MAX_CAM_SCALE = 0.04
GLOBAL_GAP_S = 3.0
MOVERS = {"Person", "Bicycle", "Motorcycle", "Car", "Bus", "Truck", "Dog", "Cat", "Cow", "Horse"}


def _article(name):
    n = name.lower()
    return ("an " if n[0] in "aeiou" else "a ") + n


def _text(kind, name, side, direction, mode):
    obj = _article(name)
    obj = obj[0].upper() + obj[1:]
    if kind == "entering":
        return (f"Caution. {obj} is moving into your path from the {side}." if mode == "chest" else
                f"Caution. {obj} is moving into the centre of the camera view from the {side}.")
    return (f"{obj} is crossing in front of you, from {direction}." if mode == "chest" else
            f"{obj} is crossing the camera view, from {direction}.")


class PathEventDetector:
    def __init__(self, mode="chest"):
        self.mode = mode if mode in ("chest", "handheld") else "chest"
        self.last_event_t = None
        self.cam_history = []          # (t, shift, scale, ok)

    def _camera_stable(self, t0, t1):
        rows = [c for c in self.cam_history if t0 <= c[0] <= t1]
        return bool(rows) and all(ok and shift <= MAX_CAM_SHIFT and abs(scale - 1) <= MAX_CAM_SCALE
                                  for _, shift, scale, ok in rows)

    def update(self, tracks, t, width, height, cam, path_state):
        self.cam_history.append((t, cam.shift if cam else 0.0, cam.scale if cam else 1.0, bool(cam and cam.ok)))
        self.cam_history = [c for c in self.cam_history if t - c[0] <= CROSS_WINDOW_S + 0.5]
        if path_state in (UNCERTAIN, CAMERA_UNAVAILABLE, BLOCKED_VIEW):
            return []
        if self.last_event_t is not None and t - self.last_event_t < GLOBAL_GAP_S:
            return []
        out = []
        for tr in tracks:
            if tr.hits < MIN_HITS or tr.age < MIN_AGE_S or tr.class_name not in MOVERS:
                continue               # only objects that move by themselves (people, vehicles, animals)
            ev = self._entering(tr, t, width, height) or self._crossing(tr, t)
            if ev:
                tr.announced.add(ev["type"])
                out.append(ev)
                self.last_event_t = t
                break                  # one event per frame at most
        return out

    def _window(self, tr, t, span):
        return [h for h in tr.history if t - h[0] <= span]

    def _rel_speed_x(self, rows):
        if len(rows) < MIN_HITS:
            return 0.0
        dt = rows[-1][0] - rows[0][0]
        return sum(r[5] for r in rows[1:]) / dt if dt > 0 else 0.0

    def _entering(self, tr, t, width, height):
        if "entering" in tr.announced:
            return None
        rows = self._window(tr, t, WINDOW_S)
        if len(rows) < MIN_HITS or not self._camera_stable(rows[1][0], t):   # motion between samples only
            return None
        first, last = rows[0], rows[-1]

        def overlap(r):
            cx, cy, bw, bh = r[1] * width, r[2] * height, r[3] * width, r[4] * height
            return box_path_overlap([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], width, height)
        c0, i0 = overlap(first)
        c1, i1 = overlap(last)
        was_outside = c0 < 0.02 and i0 < 0.10
        now_inside = c1 >= 0.06 or i1 >= 0.35
        if not (was_outside and now_inside):
            return None
        vx = self._rel_speed_x(rows)
        side = "left" if first[1] < 0.5 else "right"
        towards = vx > 0 if side == "left" else vx < 0
        if not towards or abs(vx) < ENTER_SPEED:
            return None
        return {"type": "entering", "track_id": tr.id, "class_name": tr.class_name, "side": side,
                "speed": round(abs(vx), 3), "text": _text("entering", tr.class_name, side, None, self.mode)}

    def _crossing(self, tr, t):
        if "crossing" in tr.announced or "entering" in tr.announced or tr.class_name not in MOVERS:
            return None
        rows = self._window(tr, t, CROSS_WINDOW_S)
        if len(rows) < MIN_HITS or not self._camera_stable(rows[1][0], t):   # motion between samples only
            return None
        x0, x1 = rows[0][1], rows[-1][1]
        bottom = rows[-1][2] + rows[-1][4] / 2
        if bottom < 0.5:
            return None
        if x0 < 0.35 and x1 > 0.65:
            direction = "left to right"
        elif x0 > 0.65 and x1 < 0.35:
            direction = "right to left"
        else:
            return None
        vx = self._rel_speed_x(rows)
        if abs(vx) < CROSS_SPEED or (vx > 0) != (direction == "left to right"):
            return None
        return {"type": "crossing", "track_id": tr.id, "class_name": tr.class_name, "direction": direction,
                "speed": round(abs(vx), 3), "text": _text("crossing", tr.class_name, None, direction, self.mode)}
