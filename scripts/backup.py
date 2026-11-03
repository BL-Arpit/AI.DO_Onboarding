"""Use SQLite's online backup API; do not copy only the main file while WAL is active."""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
from app.core.config import Settings

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination")
    args = parser.parse_args()
    target = Path(args.destination).resolve()
    if target.exists():
        parser.exit(1, "Destination exists; choose a new backup filename.\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with (
            sqlite3.connect(Settings.load().database) as source,
            sqlite3.connect(target) as destination,
        ):
            source.backup(destination)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    print("Consistent database backup created. Protect it as employee data.")
