import json
import numpy as np
from app.agents.chat import embed,load_model,MODEL_DIR

def test_masked_pooling_is_normalized_and_meaningful():
    meta,head,encoder=load_model()
    vectors=embed(['Please register a new employee','Onboard a new staff member','What is the capital of France?'],encoder)
    assert vectors.shape==(3,384)
    np.testing.assert_allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-5)
    assert vectors[0]@vectors[1]>vectors[0]@vectors[2]
    assert head['weights'].shape==(384,len(meta['labels']))
    source=json.loads((MODEL_DIR/'source.json').read_text())
    assert source['variant']=='quint8_avx2'
    assert source['files']['model.onnx']['bytes']<25_000_000
