"""Offline validation without importing native ONNX Runtime."""
import sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.chdir(ROOT)
from training.reference_encoder import ReferenceSession
from app.agents import chat
from app import classifier
from tokenizers import Tokenizer
from functools import lru_cache
@lru_cache(maxsize=1)
def encoder():
    tok=Tokenizer.from_file(str(chat.MODEL_DIR/'tokenizer.json'))
    tok.enable_truncation(max_length=256);tok.enable_padding(pad_id=0,pad_token='[PAD]')
    return ReferenceSession(chat.MODEL_DIR/'model.onnx'),tok
chat.load_encoder=encoder
@lru_cache(maxsize=1)
def document_encoder():
    import json
    return ReferenceSession(classifier._BASE/'doc_classifier.onnx'),json.loads((classifier._BASE/'labels.json').read_text())
classifier._load=document_encoder
import pytest
print('Offline graph interpreter: native ONNX Runtime is never imported.',flush=True)
result=pytest.main(['-q','tests'])
assert 'onnxruntime' not in sys.modules,'Native runtime was unexpectedly imported in offline mode.'
sys.exit(result)
