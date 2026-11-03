import json
import numpy as np
import onnxruntime as ort
from app.agents.chat import MODEL_DIR,load_model,vectorize,chat_agent

def test_chat_runs_onnx_and_matches_training_weights():
    meta,session=load_model()
    assert isinstance(session,ort.InferenceSession)
    texts=['add','list','export','hello','do not approve','zzzz','please onboard a person']
    x=np.stack([vectorize(text,meta['vocabulary']) for text in texts])
    with np.load(MODEL_DIR/'weights.npz',allow_pickle=False) as values:
        logits=np.maximum(x@values['w1']+values['b1'],0)@values['w2']+values['b2']
    expected=np.exp(logits-logits.max(axis=1,keepdims=True));expected/=expected.sum(axis=1,keepdims=True)
    actual=session.run(None,{'features':x})[0]
    np.testing.assert_allclose(actual,expected,atol=1e-6,rtol=1e-5)
    assert chat_agent('add')['runtime']=='onnxruntime'
    assert chat_agent('add')['model_file']=='intent_ann.onnx'
    report=json.loads((MODEL_DIR/'onnx_export.json').read_text())
    assert report['predictions_identical']
