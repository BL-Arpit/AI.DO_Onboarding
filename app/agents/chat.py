"""Local ANN intent inference. No API call, regex router or runtime training."""
import json
import re
from functools import lru_cache
from pathlib import Path
import numpy as np
import onnxruntime as ort
# Request the runtime telemetry opt-out before creating sessions.
ort.disable_telemetry_events()

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
    options=ort.SessionOptions();options.intra_op_num_threads=1
    session=ort.InferenceSession(str(MODEL_DIR/'intent_ann.onnx'),options,providers=['CPUExecutionProvider'])
    return meta,session

def chat_agent(text):
    meta,session=load_model()
    features=vectorize(text,meta['vocabulary'])
    scores=session.run(['probabilities'],{'features':features.reshape(1,-1)})[0][0]
    order=np.argsort(scores)[::-1];top=int(order[0]);confidence=float(scores[top])
    predicted=meta['labels'][top]
    # Low confidence/OOV messages never silently choose a task.
    route=predicted if features.any() and confidence>=THRESHOLD and confidence-float(scores[order[1]])>=MIN_MARGIN else 'unknown'
    return {'intent':route,'predicted_intent':predicted,'confidence':round(confidence,4),'model':'local_ann_onnx_v1','runtime':'onnxruntime','model_file':'intent_ann.onnx'}
