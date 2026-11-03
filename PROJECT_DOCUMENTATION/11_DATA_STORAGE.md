# 11. Database and data storage

## 11.1 Overview of everything that is stored

| What | Where | Format | Written by | Notes |
|---|---|---|---|---|
| Alert history | `data/neurosonic.sqlite3`, table `alerts` | SQLite | `neurosonic/store.py::Store.add_alert` (L47–58), called by `service.EventLog.add` (`service.py` L77–87) | every spoken alert from replay, upload, camera awareness, event simulation and navigation |
| Saved places | same file, table `places` | SQLite | `Store.add_place` (L82–93) | user-named destinations, e.g. "Home" |
| Recent events (for polling) | memory | Python `deque(maxlen=300)` | `EventLog` (`service.py` L68–96) | lost on restart; the history table keeps them permanently |
| Speech audio cache | `data/tts_cache/<sha256>.wav` | WAV | `PiperTTS.synthesize` (`tts.py` L95–130) | at most 400 files (`CACHE_FILES`), oldest deleted first; 7.4 MB at the time of writing |
| TLS material | `data/tls/` | PEM | `neurosonic/tls.py::ensure_certificates` (L86–130) | **contains private keys: keep private** (see document 12) |
| Client settings | the browser's `localStorage["neurosonic.settings"]` | JSON | `web/js/app.js` L14–15 | voice engine, voice, rate, volume, speech on/off, tones, carrying mode |
| Offline map package | `maps/vellore/*.json` | JSON | `tools/build_offline_map.py` | read-only at runtime |
| Models / checkpoint | `weights/`, `models/` | binary | downloads | read-only at runtime |
| Run outputs of the CLIs | `outputs/<run>/` | JSON, JPEG | `woad_detect.py`, `woad_replay.py`, `tools/evaluate.py` | auto-incremented folders, never overwritten |

## 11.2 SQLite schema (`neurosonic/store.py`, `SCHEMA` L6–26)

```sql
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
```

* **Allowed values** are enforced in code (`ALLOWED_SOURCES` L28, `ALLOWED_KINDS` L29).
  * The current sources are `replay, upload, eventsim, navigation, awareness, voice`.
  * The SQL comment in the schema still lists only the first four. It is a comment, not a constraint, so
    behaviour is unaffected.
* **Thread safety:** one connection opened with `check_same_thread=False` and protected by a `threading.Lock`,
  because the HTTP server is multi-threaded.
* **SQL injection:** every statement uses `?` placeholders.
* **Validation:** names are trimmed to 80 characters; texts are cut at 300 characters; coordinates are
  range-checked in Python (`add_place` L82–93) *and* by `CHECK` constraints.

## 11.3 Why SQLite?

* It's built into Python (`sqlite3`), with no server process: a single file that is easy to back up or delete.
* It's transactional (ACID), so a crash does not corrupt the history.
* It works fully offline. The requirement "local database using SQLite" was part of the product
  specification.

## 11.4 Privacy

* **Location trace:** the server does **not** store GPS positions. Navigation messages are stored as text
  only.
* **Audio and camera:** voice-command audio and camera frames are processed in memory and **not stored**.
* **Deleting the history:** `POST /api/history/clear` or the History tab's "Clear history".
