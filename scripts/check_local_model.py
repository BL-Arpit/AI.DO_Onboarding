"""Run inside the built container to verify actual GGUF inference, without APIs."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.chat.smollm_agent import _generate

path = Path(os.getenv("GGUF_MODEL_PATH", "/project/model/replies.gguf"))
if not path.is_file():
    raise SystemExit("GGUF file missing: " + str(path))
print("Local model file bytes:", path.stat().st_size)
print(_generate([
    {"role": "system", "content": "You are a helpful assistant. Answer briefly."},
    {"role": "user", "content": "Say hello and introduce yourself."},
]))
