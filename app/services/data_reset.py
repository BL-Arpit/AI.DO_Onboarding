"""Explicit, once-per-ID maintenance reset for this application's stores."""

import hashlib
import logging
import os
import re
import time

import httpx
from pymongo import MongoClient

from app.repositories.database import connection, PostgresConnection
from app.schemas.employee import EmployeeInput

log = logging.getLogger(__name__)
# Exact application tables only. The reset ledger is deliberately excluded.
TABLES = (
    "employee_requests",
    "document_uploads",
    "documents",
    "audit",
    "auth_sessions",
    "auth_attempts",
    "chat_messages",
    "chat_conversations",
    "pending_actions",
    "imports",
    "document_previews",
    "employees",
    "users",
    "tenant_schema_versions",
    "tenants",
)


def _configuration():
    reset_id = os.getenv("AIDO_RESET_ID", "").strip()
    if not reset_id:
        return None
    if not re.fullmatch(r"[a-zA-Z0-9_-]{8,100}", reset_id):
        raise RuntimeError(
            "AIDO_RESET_ID must contain 8–100 letters, digits, underscores or hyphens."
        )
    if os.getenv("AIDO_RESET_CONFIRM") != "DELETE_ALL_AIDO_DATA":
        raise RuntimeError("Reset requires AIDO_RESET_CONFIRM=DELETE_ALL_AIDO_DATA.")
    EmployeeInput.email_clean(os.getenv("SUPER_ADMIN_EMAIL", ""))
    if not 8 <= len(os.getenv("SUPER_ADMIN_PASSWORD", "")) <= 256:
        raise RuntimeError("Reset requires SUPER_ADMIN_PASSWORD of 8–256 characters.")
    if os.getenv("SUPER_ADMIN_COMPANY_ID", "").strip():
        raise RuntimeError("Remove SUPER_ADMIN_COMPANY_ID before resetting the company.")
    mongo_uri = os.getenv("MONGODB_URI", "").strip()
    qdrant_url = os.getenv("QDRANT_URL", "").strip().rstrip("/")
    if not mongo_uri or not qdrant_url:
        raise RuntimeError("Reset requires MONGODB_URI and QDRANT_URL to clear all three stores.")
    database = os.getenv("MONGODB_DATABASE", "aido")
    collection = os.getenv("MONGODB_CONVERSATION_COLLECTION", "onboarding_private_threads_v1")
    indexes = {
        os.getenv("QDRANT_COLLECTION", "aido_employee_directory_v1"),
        os.getenv("QDRANT_CHAT_COLLECTION", "aido_private_chat_potion64_v1"),
    }
    if (
        not database
        or not collection
        or not all(re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", x) for x in indexes)
    ):
        raise RuntimeError("Reset database or collection names are invalid.")
    return (
        hashlib.sha256(reset_id.encode()).hexdigest(),
        mongo_uri,
        database,
        collection,
        qdrant_url,
        indexes,
    )


def _clear_external(config):
    _, uri, database, collection, url, indexes = config
    # Scope is the configured collection, never the entire Mongo cluster.
    with MongoClient(
        uri, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000, socketTimeoutMS=15000
    ) as mongo:
        mongo.admin.command("ping")
        mongo[database][collection].delete_many({})
    headers = {"api-key": os.environ["QDRANT_API_KEY"]} if os.getenv("QDRANT_API_KEY") else {}
    with httpx.Client(base_url=url, headers=headers, timeout=20) as client:
        for name in sorted(indexes):
            response = client.delete("/collections/" + name)
            if response.status_code != 404:
                response.raise_for_status()


def reset_if_requested():
    """Return True in reset mode, including already-completed reset IDs.

    SQL changes and completion marker commit together. External operations are
    idempotent. On failure startup stops; redeploy with the SAME ID to retry.
    """
    config = _configuration()
    if config is None:
        return False
    with connection() as db:
        postgres = isinstance(db, PostgresConnection)
        db.execute("BEGIN IMMEDIATE")
        if postgres:
            db.execute("SET LOCAL statement_timeout = '120s'")
            db.execute("SET LOCAL lock_timeout = '120s'")
        db.execute(
            "CREATE TABLE IF NOT EXISTS aido_reset_runs (id TEXT PRIMARY KEY, completed DOUBLE PRECISION NOT NULL)"
        )
        if db.execute("SELECT id FROM aido_reset_runs WHERE id=?", (config[0],)).fetchone():
            log.info("Requested AI.DO reset was already completed; data preserved.")
            return True
        if postgres:
            available = {
                r["tablename"]
                for r in db.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                ).fetchall()
            }
            tables = [t for t in TABLES if t in available]
            if tables:
                db.execute(
                    "TRUNCATE TABLE "
                    + ", ".join("public." + t for t in tables)
                    + " RESTART IDENTITY"
                )
        else:
            available = {
                r["name"]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            for table in TABLES:
                if table in available:
                    db.execute("DELETE FROM " + table)
        _clear_external(config)
        db.execute(
            "INSERT INTO aido_reset_runs(id,completed) VALUES(?,?)", (config[0], time.time())
        )
    log.warning("AI.DO reset completed. Configured super admin will be recreated at startup.")
    return True
