"""Local SQLite store: alert history and saved places. Local only; nothing leaves the device."""
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL,          -- unix time
    source TEXT NOT NULL,           -- replay | upload | eventsim | navigation
    kind TEXT NOT NULL,             -- object | system | motion | navigation
    text TEXT NOT NULL,
    class_name TEXT,
    position TEXT,
    confidence REAL,
    frame_id TEXT
);
CREATE INDEX IF NOT EXISTS alerts_created ON alerts(created);
CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    lat REAL NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon REAL NOT NULL CHECK (lon BETWEEN -180 AND 180),
    created REAL NOT NULL
);
"""

ALLOWED_SOURCES = {"replay", "upload", "eventsim", "navigation", "awareness", "voice", "vision"}
ALLOWED_KINDS = {"object", "system", "motion", "navigation", "path", "scene", "event"}


class Store:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()

    # ---- alerts
    def add_alert(self, source, kind, text, class_name=None, position=None, confidence=None, frame_id=None,
                  created=None):
        if source not in ALLOWED_SOURCES or kind not in ALLOWED_KINDS:
            raise ValueError("invalid source/kind")
        text = str(text)[:300]
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO alerts(created, source, kind, text, class_name, position, confidence, frame_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (created or time.time(), source, kind, text, class_name, position, confidence, frame_id))
            self._db.commit()
            return cur.lastrowid

    def history(self, limit=100):
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            rows = self._db.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def stats(self):
        with self._lock:
            by_class = self._db.execute(
                "SELECT class_name, COUNT(*) n FROM alerts WHERE kind='object' GROUP BY class_name").fetchall()
            by_kind = self._db.execute("SELECT kind, COUNT(*) n FROM alerts GROUP BY kind").fetchall()
            by_source = self._db.execute("SELECT source, COUNT(*) n FROM alerts GROUP BY source").fetchall()
            total = self._db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        return {"total": total, "objects_by_class": {r["class_name"]: r["n"] for r in by_class},
                "by_kind": {r["kind"]: r["n"] for r in by_kind}, "by_source": {r["source"]: r["n"] for r in by_source}}

    def clear_history(self):
        with self._lock:
            self._db.execute("DELETE FROM alerts")
            self._db.commit()

    # ---- places
    def add_place(self, name, lat, lon):
        name = str(name).strip()[:80]
        if not name:
            raise ValueError("name is required")
        lat, lon = float(lat), float(lon)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("latitude/longitude out of range")
        with self._lock:
            cur = self._db.execute("INSERT INTO places(name, lat, lon, created) VALUES (?,?,?,?)",
                                   (name, lat, lon, time.time()))
            self._db.commit()
            return cur.lastrowid

    def places(self):
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM places ORDER BY name").fetchall()]

    def delete_place(self, pid):
        with self._lock:
            n = self._db.execute("DELETE FROM places WHERE id=?", (int(pid),)).rowcount
            self._db.commit()
        return n > 0
