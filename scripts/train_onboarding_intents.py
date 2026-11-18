"""Retrain the bundled small TextCNN using NumPy on a CPU."""

import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.chat.local_models import cnn_forward, encode_tokens, tokenize


def read_examples(path):
    examples = []
    label = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            label = line[1:-1]
        elif line and label:
            examples.append((label, line))
    return examples


def train(examples):
    rng = np.random.default_rng(29)
    prefixes = ("", "", "could you", "can you", "would you", "please", "i need to")
    suffixes = ("", "", "please", "for me", "today")
    augmented = []
    for label, phrase in examples:
        for _ in range(6):
            sentence = f"{rng.choice(prefixes)} {phrase} {rng.choice(suffixes)}"
            augmented.append((label, tokenize(sentence)))
    counts = Counter(token for _, tokens in augmented for token in tokens)
    vocabulary = {t: i for i, t in enumerate(["[PAD]", "[UNK]", *sorted(counts)])}
    labels = sorted({label for label, _ in examples})
    x = np.stack([encode_tokens(tokens, vocabulary) for _, tokens in augmented])
    y = np.array([labels.index(label) for label, _ in augmented])
    dimensions, filters = 24, 56
    def normal(shape, scale):
        return (rng.standard_normal(shape, dtype=np.float32) * scale).astype(np.float32)
    weights = [
        normal((len(vocabulary), dimensions), 0.16),
        normal((3 * dimensions, filters), 0.12),
        np.zeros(filters, dtype=np.float32),
        normal((filters, len(labels)), 0.14),
        np.zeros(len(labels), dtype=np.float32),
    ]
    weights[0][0] = 0
    # Maintain moments for Adam, explicitly keeping padding outside the learned vocabulary.
    mean = [np.zeros_like(weight) for weight in weights]
    variance = [np.zeros_like(weight) for weight in weights]
    steps = 0
    for _ in range(30):
        for batch in np.array_split(rng.permutation(len(x)), 38):
            ids = x[batch].copy()
            ids[(rng.random(ids.shape) < 0.06) & (ids != 0)] = 1
            logits, (windows, features, indices, pooled) = cnn_forward(ids, *weights)
            probs = np.exp(logits - logits.max(axis=1, keepdims=True))
            probs /= probs.sum(axis=1, keepdims=True)
            probs[np.arange(len(batch)), y[batch]] -= 1
            dlogits = probs / len(batch)
            dpooled = (dlogits @ weights[3].T) * (pooled > 0)
            dconv = np.zeros((*ids.shape, filters), np.float32)
            rows = np.arange(len(batch))[:, None]
            channels = np.arange(filters)
            dconv[rows, indices, channels] = dpooled
            dfeatures = (dconv @ weights[1].T).reshape(*windows.shape, dimensions)
            dembedding = np.zeros_like(weights[0])
            np.add.at(dembedding, windows.flatten(), dfeatures.reshape(-1, dimensions))
            dembedding[0] = 0
            gradients = (
                dembedding, features.reshape(-1, 3 * dimensions).T @ dconv.reshape(-1, filters),
                dconv.sum(axis=(0, 1)), pooled.T @ dlogits, dlogits.sum(axis=0),
            )
            steps += 1
            for weight, gradient, m, v in zip(weights, gradients, mean, variance, strict=True):
                m *= 0.9
                m += 0.1 * gradient
                v *= 0.999
                v += 0.001 * gradient ** 2
                weight -= 0.003 * (m / (1 - 0.9 ** steps)) / (
                    np.sqrt(v / (1 - 0.999 ** steps)) + 1e-8
                )
    return vocabulary, labels, weights


if __name__ == "__main__":
    words, intents, parameters = train(read_examples(ROOT / "config" / "intent_examples.txt"))
    destination = ROOT / "model" / "onboarding_intents.npz"
    np.savez_compressed(
        destination,
        vocabulary=np.array(list(words)),
        labels=np.array(intents),
        **dict(zip(("embedding", "kernels", "convolution_bias", "output", "output_bias"),
                   parameters, strict=True)),
    )
    print(f"Wrote {destination.relative_to(ROOT)} ({destination.stat().st_size:,} bytes)")
