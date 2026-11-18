"""Local intent classification and optional response phrasing for onboarding."""

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from threading import Lock

import numpy as np

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
MAX_INPUT_TOKENS = 40

_EMAIL = re.compile(r"[^\s,;<>]+@[^\s,;<>]+\.[^\s,;<>]+")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)")
_TOKEN = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.UNICODE)
_reply_lock = Lock()


def tokenize(text: str) -> list[str]:
    text = _EMAIL.sub(" emailaddr ", text)
    text = _PHONE.sub(" phonenum ", text)
    return _TOKEN.findall(text.casefold().replace("’", "'"))[:MAX_INPUT_TOKENS]


def encode_tokens(tokens: list[str], vocabulary: dict[str, int]) -> np.ndarray:
    return np.array(
        [vocabulary.get(token, 1) for token in tokens]
        + [0] * (MAX_INPUT_TOKENS - len(tokens)),
        dtype=np.int32,
    )


def cnn_forward(ids, embedding, kernels, convolution_bias, output, output_bias):
    """Run a width-three convolution, ReLU, masked max pooling and a linear head."""
    batch_size, length = ids.shape
    padded = np.pad(ids, ((0, 0), (1, 1)))
    windows = np.lib.stride_tricks.sliding_window_view(padded, 3, axis=1)
    features = embedding[windows].reshape(batch_size, length, -1)
    activation = np.maximum(features @ kernels + convolution_bias, 0)
    activation = np.where(ids[..., None] != 0, activation, -1)
    indices = activation.argmax(axis=1)
    pooled = np.take_along_axis(activation, indices[:, None], axis=1)[:, 0]
    logits = pooled @ output + output_bias
    return logits, (windows, features, indices, pooled)


@lru_cache(maxsize=1)
def _load_intent_model():
    path = Path(os.getenv("TEXTCNN_MODEL_PATH", ROOT / "model" / "onboarding_intents.npz"))
    with np.load(path, allow_pickle=False) as artifact:
        vocabulary = {str(word): i for i, word in enumerate(artifact["vocabulary"])}
        labels = tuple(str(label) for label in artifact["labels"])
        weights = tuple(
            artifact[name]
            for name in ("embedding", "kernels", "convolution_bias", "output", "output_bias")
        )
    return vocabulary, labels, weights


def predict_intent(text: str) -> tuple[str, float]:
    """Return a predicted intent and an uncalibrated softmax score."""
    vocabulary, labels, weights = _load_intent_model()
    tokens = tokenize(text)
    if not tokens or all(token not in vocabulary for token in tokens):
        return "unknown", 1.0
    ids = encode_tokens(tokens, vocabulary)
    logits, _ = cnn_forward(ids[None, :], *weights)
    scores = np.exp(logits[0] - logits[0].max())
    best = int(scores.argmax())
    return labels[best], float(scores[best] / scores.sum())


def _bounded_env(key: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.getenv(key, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


@lru_cache(maxsize=1)
def _reply_model(path: str):
    from llama_cpp import Llama

    return Llama(
        model_path=path,
        n_ctx=_bounded_env("GGUF_CONTEXT_TOKENS", 512, 256, 2048),
        n_threads=_bounded_env("GGUF_THREADS", 1, 1, 4),
        n_threads_batch=_bounded_env("GGUF_THREADS", 1, 1, 4),
        n_batch=32,
        n_gpu_layers=0,
        use_mmap=True,
        verbose=False,
    )


def render_reply(reply: str, *, allow_model: bool = False) -> str:
    """Optionally phrase a generic response. Never pass records or user text here."""
    path = os.getenv("GGUF_MODEL_PATH", "").strip()
    if not allow_model or not path or len(reply) > 240:
        return reply
    if not _reply_lock.acquire(blocking=False):
        return reply
    try:
        result = _reply_model(path).create_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise onboarding assistant. Rewrite the supplied help text "
                        "in one or two natural sentences. Preserve its meaning and never claim "
                        "that a record was created, updated, approved, sent, or deleted. "
                        "Return only the revised text."
                    ),
                },
                {"role": "user", "content": reply},
            ],
            temperature=0.15,
            max_tokens=_bounded_env("GGUF_MAX_REPLY_TOKENS", 48, 16, 96),
        )
        choice = result["choices"][0]
        if choice["finish_reason"] != "stop":
            return reply
        generated = (choice["message"]["content"] or "").strip()
        return generated if 8 <= len(generated) <= 360 else reply
    except (ImportError, OSError, ValueError, RuntimeError, KeyError, TypeError, IndexError) as exc:
        logger.warning("Optional local reply model unavailable (%s)", type(exc).__name__)
        return reply
    finally:
        _reply_lock.release()
