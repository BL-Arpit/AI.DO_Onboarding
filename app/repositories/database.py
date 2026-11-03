import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from app.core.config import Settings


@contextmanager
def connection():
    path = Settings.load().database
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    with connection() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript((Path(__file__).with_name("schema.sql")).read_text())
        names = {r["name"] for r in db.execute("PRAGMA table_info(employees)")}
        if "deleted_at" not in names:
            db.execute("ALTER TABLE employees ADD COLUMN deleted_at REAL")
        # The new authentication store uses hashed tokens. Legacy sessions are invalidated once.
        if db.execute("PRAGMA user_version").fetchone()[0] < 2:
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'"
            ).fetchone():
                db.execute("DELETE FROM sessions")
            db.execute("PRAGMA user_version=2")
        db.execute("DELETE FROM auth_sessions WHERE expires<?", (time.time(),))
        db.execute("DELETE FROM document_previews WHERE expires<?", (time.time(),))
        db.execute("DELETE FROM pending_actions WHERE expires<?", (time.time(),))
        db.execute("DELETE FROM imports WHERE expires<?", (time.time(),))


def record(row):
    if row is None:
        return None
    result = dict(row)
    for key in ("fields", "verification", "classification", "extraction"):
        if key in result:
            result[key] = json.loads(result[key])
    return result


def audit(db, eid, actor, action, details=""):
    db.execute(
        "INSERT INTO audit(employee_id,actor,action,details) VALUES(?,?,?,?)",
        (eid, actor, action, details),
    )
