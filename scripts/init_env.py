"""Generate a private root environment; never overwrite an existing one."""

import argparse
import os
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", args.email):
        parser.error("Use a valid operator email.")
    template = ROOT / (".env.production.example" if args.production else ".env.example")
    content = (
        template.read_text()
        .replace(
            "APP_SECRET=GENERATE_WITH_INIT_ENV",
            "APP_SECRET=" + secrets.token_urlsafe(48),
        )
        .replace(
            "BOOTSTRAP_PASSWORD=GENERATE_WITH_INIT_ENV",
            "BOOTSTRAP_PASSWORD=" + secrets.token_urlsafe(24),
        )
    )
    content = re.sub(
        r"^BOOTSTRAP_EMAIL=.*$",
        lambda m: "BOOTSTRAP_EMAIL=" + args.email,
        content,
        flags=re.MULTILINE,
    )
    try:
        descriptor = os.open(ROOT / ".env", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(content)
    except FileExistsError:
        parser.exit(1, "A .env already exists; it was not changed. Edit it privately.\n")
    print(
        "Created .env with random secrets. Open it privately for the initial password. For production, set the actual origin, hosts, provider and credentials before startup."
    )
