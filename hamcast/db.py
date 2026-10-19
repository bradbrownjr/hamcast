"""Every transmission hamcast hears, in <data_dir>/hamcast.db (SQLite).

One row per transmission: net, start, length, talker, gateway, mode,
transcript and its status, and the name of its audio file in
<data_dir>/recordings/<net>/ (NULL once the audio is deleted: too short to
keep, or past HAMCAST_AUDIO_DAYS). Rows are kept forever.

The connection is shared by the event loop and the web server's worker
threads, so every call takes a lock.
"""

import json
import sqlite3
import threading
from pathlib import Path

from .stream import Heard

SCHEMA = """
CREATE TABLE IF NOT EXISTS transmissions (
    id INTEGER PRIMARY KEY,
    stream_id TEXT NOT NULL,
    started REAL NOT NULL,
    seconds REAL NOT NULL,
    talker TEXT NOT NULL,
    gateway TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '',
    audio TEXT,
    transcript TEXT,
    transcript_status TEXT,
    segments TEXT
);
CREATE INDEX IF NOT EXISTS transmissions_stream_started ON transmissions (stream_id, started);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_COLUMNS = "id, started, seconds, talker, gateway, mode, audio, transcript, transcript_status"


class HistoryDB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    # ========== WRITES ==========

    def add(self, stream_id: str, heard: Heard) -> None:
        """Store a finished transmission; sets heard.id."""
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO transmissions (stream_id, started, seconds, talker, gateway, mode, audio,"
                " transcript, transcript_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (stream_id, heard.started, round(heard.seconds, 1), heard.talker, heard.gateway or "",
                 heard.mode or "", _audio(heard), heard.transcript, heard.transcript_status))
            heard.id = cur.lastrowid

    def update(self, heard: Heard, segments: list | None = None) -> None:
        """Save a transmission's audio file and transcript as they are now."""
        with self._lock, self._db:
            self._db.execute(
                "UPDATE transmissions SET audio = ?, transcript = ?, transcript_status = ?,"
                " segments = COALESCE(?, segments) WHERE id = ?",
                (_audio(heard), heard.transcript, heard.transcript_status,
                 json.dumps(segments) if segments is not None else None, heard.id))

    def drop_audio(self, row_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE transmissions SET audio = NULL WHERE id = ?", (row_id,))

    # ========== READS ==========

    def page(self, stream_id: str, directory: Path, before: float | None = None,
             limit: int = 50) -> tuple[list[Heard], bool]:
        """Up to `limit` transmissions, newest first, that started before
        `before` if given. Also says whether older ones remain."""
        sql = f"SELECT {_COLUMNS} FROM transmissions WHERE stream_id = ?"
        args: list = [stream_id]
        if before is not None:
            sql += " AND started < ?"
            args.append(before)
        sql += " ORDER BY started DESC LIMIT ?"
        args.append(limit + 1)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [_heard(r, directory) for r in rows[:limit]], len(rows) > limit

    def unfinished(self, stream_id: str, directory: Path) -> list[Heard]:
        """Transmissions whose audio is still a WAV: not yet transcribed or
        compressed, usually because hamcast stopped first. Oldest first."""
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_COLUMNS} FROM transmissions WHERE stream_id = ? AND audio LIKE '%.wav'"
                " ORDER BY started", (stream_id,)).fetchall()
        return [_heard(r, directory) for r in rows]

    def audio_before(self, cutoff: float) -> list[tuple[int, str, str]]:
        """(id, stream_id, audio file) for audio from transmissions before `cutoff`."""
        with self._lock:
            return self._db.execute(
                "SELECT id, stream_id, audio FROM transmissions WHERE audio IS NOT NULL AND started < ?",
                (cutoff,)).fetchall()

    # ========== ONE-TIME FLAGS ==========

    def flag(self, key: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM meta WHERE key = ?", (key,)).fetchone() is not None

    def set_flag(self, key: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, '1')", (key,))

    def close(self) -> None:
        self._db.close()


def _audio(heard: Heard) -> str | None:
    return Path(heard.recording).name if heard.recording else None


def _heard(row, directory: Path) -> Heard:
    row_id, started, seconds, talker, gateway, mode, audio, transcript, status = row
    return Heard(talker=talker, gateway=gateway, started=started, ended=started + seconds, mode=mode,
                 recording=str(directory / audio) if audio else None, transcript=transcript,
                 transcript_status=status, id=row_id)
