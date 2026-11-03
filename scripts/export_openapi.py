import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.main import create_app

if __name__ == "__main__":
    target = ROOT / "docs/openapi.json"
    target.write_text(json.dumps(create_app().openapi(), indent=2))
    print("Wrote docs/openapi.json; no server or model provider was started.")
