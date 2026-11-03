"""Local MiniLM INT8 sentence encoder plus a small trained intent head.

MiniLM encodes meaning; the router and onboarding agents provide grounded replies.
No external API, downloads or free-form generation run during chat.
"""
import json
import re
from functools import lru_cache
from pathlib import Path
import numpy as np
from tokenizers import Tokenizer
MODEL_DIR=Path(__file__).resolve().parents[2]/'model/minilm'
THRESHOLD=0.55
MIN_MARGIN=0.12

@lru_cache(maxsize=1)
def load_encoder():
    import onnxruntime as ort
    ort.disable_telemetry_events()
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(MODEL_DIR/'model.onnx'),options,providers=['CPUExecutionProvider'])
    tokenizer=Tokenizer.from_file(str(MODEL_DIR/'tokenizer.json'))
    tokenizer.enable_truncation(max_length=256);tokenizer.enable_padding(pad_id=0,pad_token='[PAD]')
    return session,tokenizer

def embed(texts,encoder=None):
    session,tokenizer=encoder or load_encoder()
    encoded=tokenizer.encode_batch(texts)
    mask=np.array([item.attention_mask for item in encoded],dtype=np.int64)
    inputs={'input_ids':np.array([item.ids for item in encoded],dtype=np.int64),
            'attention_mask':mask,'token_type_ids':np.array([item.type_ids for item in encoded],dtype=np.int64)}
    allowed={item.name for item in session.get_inputs()}
    hidden=session.run(None,{key:value for key,value in inputs.items() if key in allowed})[0]
    pooled=(hidden*mask[:,:,None]).sum(axis=1)/np.maximum(mask.sum(axis=1,keepdims=True),1)
    return (pooled/np.maximum(np.linalg.norm(pooled,axis=1,keepdims=True),1e-9)).astype(np.float32)

@lru_cache(maxsize=1)
def load_model():
    meta=json.loads((MODEL_DIR/'metadata.json').read_text())
    with np.load(MODEL_DIR/'intent_head.npz',allow_pickle=False) as data:
        head={key:data[key].copy() for key in data.files}
    return meta,head,load_encoder()

def predict(features,meta,head):
    logits=features@head['weights']+head['bias']
    scores=np.exp(logits-logits.max());scores/=scores.sum()
    order=np.argsort(scores)[::-1];top=int(order[0]);confidence=float(scores[top])
    similarity=float(np.max(features@head['examples'].T))
    predicted=meta['labels'][top]
    intent=predicted if confidence>=THRESHOLD and confidence-float(scores[order[1]])>=MIN_MARGIN and similarity>=0.35 else 'unknown'
    return {'intent':intent,'predicted_intent':predicted,'confidence':round(confidence,4),
            'similarity':round(similarity,4),'model':'minilm_int8_intent_v1','runtime':'onnxruntime',
            'model_file':'model/minilm/model.onnx','reply_mode':'agent_templates'}

def routing_text(text):
    # Employee field values belong to the onboarding agent, not the intent classifier.
    marker=re.search(r'\b(?:name|email|phone|mobile|client|track)\s*[:=]',text,re.I)
    if marker and text[:marker.start()].strip():return text[:marker.start()].strip()
    return text

def chat_agent(text):
    meta,head,encoder=load_model()
    return predict(embed([routing_text(text)],encoder)[0],meta,head)
