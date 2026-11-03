"""One process, one HTTP server; OCR and classification run as local modules."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("BIND_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        workers=1,
        access_log=False,
        proxy_headers=False,
        limit_concurrency=16,
        timeout_keep_alive=5,
        backlog=128,
    )
