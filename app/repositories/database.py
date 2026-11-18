import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.core.config import Settings


class DuplicateRecordError(Exception):
    pass


CONNECTION_CONFLICT_ERRORS = (sqlite3.IntegrityError, DuplicateRecordError)


class SQLiteConnection(sqlite3.Connection):
    row_order = "rowid"


class PostgresConnection:
    row_order = "position"

    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=()):
        from psycopg.errors import UniqueViolation

        if sql == "BEGIN IMMEDIATE":
            # Existing write transactions depend on taking a lock before their first read.
            # Transaction-scoped locking preserves that behavior across worker processes.
            return self.db.execute("SELECT pg_advisory_xact_lock(652514113)")
        try:
            return self.db.execute(sql.replace("?", "%s"), params) if params else self.db.execute(sql)
        except UniqueViolation as exc:
            raise DuplicateRecordError("Unique constraint failed.") from exc


@contextmanager
def connection():
    settings = Settings.load()
    if settings.database_url:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(
            settings.database_url,
            row_factory=dict_row,
            connect_timeout=5,
            options="-c statement_timeout=15000 -c lock_timeout=10000",
        ) as db:
            yield PostgresConnection(db)
        return

    path = settings.database
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15, factory=SQLiteConnection)
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
        if isinstance(db, PostgresConnection):
            db.execute("BEGIN IMMEDIATE")
            schema = Path(__file__).with_name("postgres_schema.sql").read_text()
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            db.execute("DELETE FROM auth_sessions WHERE expires<?", (time.time(),))
            return

        db.execute("PRAGMA journal_mode=WAL")
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='week2_uploads'"
        ).fetchone() and not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_uploads'"
        ).fetchone():
            db.execute("ALTER TABLE week2_uploads RENAME TO document_uploads")
        db.executescript((Path(__file__).with_name("schema.sql")).read_text())
        names = {r["name"] for r in db.execute("PRAGMA table_info(employees)")}
        if "deleted_at" not in names:
            db.execute("ALTER TABLE employees ADD COLUMN deleted_at REAL")
        user_columns = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
        if "must_change" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN must_change INTEGER NOT NULL DEFAULT 0")
        if "disabled" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")
        if "temp_expires" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN temp_expires REAL")
        db.execute("UPDATE users SET role='owner' WHERE role='operator' AND NOT EXISTS (SELECT 1 FROM users WHERE role='owner') AND id=(SELECT id FROM users WHERE role='operator' ORDER BY rowid LIMIT 1)")
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
    result.pop("position", None)
    for key in ("fields", "verification", "classification", "extraction"):
        if key in result:
            result[key] = json.loads(result[key])
    return result


def audit_record(row):
    result = dict(row)
    if isinstance(result.get("created"), datetime):
        result["created"] = result["created"].isoformat()
    return result


def audit(db, eid, actor, action, details=""):
    db.execute(
        "INSERT INTO audit(employee_id,actor,action,details) VALUES(?,?,?,?)",
        (eid, actor, action, details),
    )
