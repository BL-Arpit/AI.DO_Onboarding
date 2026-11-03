import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
from app.chat.providers import load_config
from app.core.config import Settings
from app.extraction.pipeline import DocumentPipeline

if __name__ == "__main__":
    try:
        settings = Settings.load()
        settings.validate()
        provider = load_config(settings)
        DocumentPipeline(settings).ready()
        print(
            "Local configuration checks passed. Provider configuration is structurally valid; no cloud API request was sent."
        )
    except Exception as exc:
        print("Configuration check failed: " + str(exc))
        sys.exit(1)
