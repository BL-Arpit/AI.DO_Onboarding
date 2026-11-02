"""Local ANN intent inference. No API call, regex router or runtime training."""
import json
import re
from functools import lru_cache
from pathlib import Path
import numpy as np

MODEL_DIR=Path(__file__).resolve().parents[2]/'model'/'chat'
THRESHOLD=0.65
MIN_MARGIN=0.12

def tokens(text):
    text=re.sub(r'[^\s,;<>]+@[^\s,;<>]+\.[^\s,;<>]+',' emailvalue ',text.lower())
    text=re.sub(r'\+?\d[\d ()-]{6,}\d',' phonevalue ',text)
    words=re.findall(r'[a-z_]+',text)
    return words+[a+' '+b for a,b in zip(words,words[1:])]

def vectorize(text,vocabulary):
    vector=np.zeros(len(vocabulary),dtype=np.float32)
    for word in tokens(text):
        index=vocabulary.get(word)
        if index is not None:vector[index]=1
    norm=np.linalg.norm(vector)
    return vector/max(norm,1)

@lru_cache(maxsize=1)
def load_model():
    meta=json.loads((MODEL_DIR/'metadata.json').read_text())
    with np.load(MODEL_DIR/'weights.npz',allow_pickle=False) as values:
        weights={key:values[key].copy() for key in values.files}
    return meta,weights

def chat_agent(text):
    meta,weights=load_model()
    features=vectorize(text,meta['vocabulary'])
    hidden=np.maximum(features@weights['w1']+weights['b1'],0)
    logits=hidden@weights['w2']+weights['b2']
    scores=np.exp(logits-logits.max());scores/=scores.sum()
    order=np.argsort(scores)[::-1];top=int(order[0]);confidence=float(scores[top])
    predicted=meta['labels'][top]
    # Low confidence/OOV messages never silently choose a task.
    route=predicted if features.any() and confidence>=THRESHOLD and confidence-float(scores[order[1]])>=MIN_MARGIN else 'unknown'
    return {'intent':route,'predicted_intent':predicted,'confidence':round(confidence,4),'model':'local_ann_v1'}
