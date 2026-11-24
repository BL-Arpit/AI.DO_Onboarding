"""Build-time retrieval of the pinned, local English memory encoder."""

import hashlib
import sys
from pathlib import Path
from urllib.request import urlopen

BASE = "https://huggingface.co/minishlab/potion-base-2M/resolve/389b9f64be5aa4ae7a6bc6fe95ef20ce485ae5da/"
FILES = {
    "tokenizer.json": "e67e803f624fb4d67dea1c730d06e1067e1b14d830e2c2202569e3ef0f70bb50",
    "model.safetensors": "f95ffde02ad06f63ae38eb9d400038cd5ccaf8411ec3cb650c6025113f96cbb8",
}
if __name__ == "__main__":
    root = Path(sys.argv[1])
    root.mkdir(exist_ok=True, parents=True)
    for name, expected in FILES.items():
        with urlopen(BASE + name, timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise SystemExit(f"Checksum mismatch for {name}")
        (root / name).write_bytes(data)
