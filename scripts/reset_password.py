"""Local administrator recovery. Requires access to the environment and database."""

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
from app.core.auth import hasher
from app.repositories.database import connection

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    password = getpass.getpass("New password (at least 16 characters): ")
    if len(password) < 16 or password != getpass.getpass("Repeat password: "):
        parser.exit(1, "Passwords must match and contain at least 16 characters.\n")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        user = db.execute("SELECT id FROM users WHERE email=?", (args.email.lower(),)).fetchone()
        if not user:
            parser.exit(1, "Account not found.\n")
        db.execute(
            "UPDATE users SET password=? WHERE id=?",
            (hasher.hash(password), user["id"]),
        )
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user["id"],))
    print("Password changed; all account sessions revoked.")
