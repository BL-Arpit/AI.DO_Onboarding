"""Mean-pooled, normalized static Model2Vec embeddings on CPU."""

import os
from functools import lru_cache
from pathlib import Path

import numpy as np


@lru_cache(maxsize=1)
def components():
    from safetensors.numpy import load_file
    from tokenizers import Tokenizer

    root = Path(os.getenv("EMBEDDING_PATH", "/project/model/memory"))
    if not (root / "tokenizer.json").is_file():
        raise FileNotFoundError("Local memory encoder missing.")
    return Tokenizer.from_file(str(root / "tokenizer.json")), load_file(root / "model.safetensors")[
        "embeddings"
    ]


def embed(text):
    tokenizer, weights = components()
    ids = tokenizer.encode(text[:8000], add_special_tokens=False).ids
    vector = weights[ids].mean(axis=0) if ids else np.zeros(weights.shape[1], dtype=np.float32)
    return (vector / max(float(np.linalg.norm(vector)), 1e-9)).tolist()
