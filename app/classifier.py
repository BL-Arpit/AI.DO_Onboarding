import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

IMG_SIZE = 224
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
THRESHOLD = 0.70

_BASE = Path(__file__).resolve().parent.parent / "model"
_session = None
_labels = None


def _load():
    global _session, _labels
    if _session is None:
        import onnxruntime as ort
        ort.disable_telemetry_events()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        _session = ort.InferenceSession(
            str(_BASE / "doc_classifier.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        _labels = json.loads((_BASE / "labels.json").read_text())
    return _session, _labels


def classify(data: bytes) -> dict:
    session, labels = _load()
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB").resize((IMG_SIZE, IMG_SIZE))
    arr = (np.asarray(img, dtype=np.float32) / 255.0 - MEAN) / STD
    inp = np.expand_dims(arr.transpose(2, 0, 1), 0).astype(np.float32)

    logits = session.run(None, {session.get_inputs()[0].name: inp})[0][0]
    e = np.exp(logits - logits.max())
    probs = e / e.sum()

    top = int(np.argmax(probs))
    conf = float(probs[top])
    return {
        "doc_type": labels[str(top)],
        "confidence": round(conf, 4),
        "needs_review": conf < THRESHOLD,
        "all_scores": {labels[str(i)]: round(float(p), 4) for i, p in enumerate(probs)},
    }
