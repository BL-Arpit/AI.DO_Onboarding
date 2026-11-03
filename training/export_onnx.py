"""Export our trained ANN to ONNX; this does not download a pretrained model."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import json
import numpy as np
import onnx
from onnx import helper,TensorProto,numpy_helper

def export_model():
    folder=ROOT/'model/chat'
    with np.load(folder/'weights.npz',allow_pickle=False) as weights:
        values={k:weights[k].astype(np.float32) for k in weights.files}
    nodes=[helper.make_node('MatMul',['features','w1'],['linear1']),
           helper.make_node('Add',['linear1','b1'],['preactivation']),
           helper.make_node('Relu',['preactivation'],['hidden']),
           helper.make_node('MatMul',['hidden','w2'],['linear2']),
           helper.make_node('Add',['linear2','b2'],['logits']),
           helper.make_node('Softmax',['logits'],['probabilities'],axis=1)]
    graph=helper.make_graph(nodes,'aido_intent_ann',
        [helper.make_tensor_value_info('features',TensorProto.FLOAT,['batch',values['w1'].shape[0]])],
        [helper.make_tensor_value_info('probabilities',TensorProto.FLOAT,['batch',values['w2'].shape[1]])],
        [numpy_helper.from_array(v,k) for k,v in values.items()])
    model=helper.make_model(graph,producer_name='AI.DO local ANN training',opset_imports=[helper.make_opsetid('',17)])
    model.ir_version=10
    model.doc_string='Custom domain ANN trained using training/intents.json; no generative pretrained base.'
    onnx.checker.check_model(model)
    onnx.save(model,folder/'intent_ann.onnx')
    # Check every training and held-out phrase against the original NumPy weights.
    from app.agents.chat import vectorize
    import onnxruntime as ort
    ort.disable_telemetry_events()
    metadata=json.loads((folder/'metadata.json').read_text())
    texts=[]
    for filename in ('intents.json','evaluation.json'):
        texts += [text for group in json.loads((ROOT/'training'/filename).read_text()).values() for text in group]
    x=np.stack([vectorize(text,metadata['vocabulary']) for text in texts])
    logits=np.maximum(x@values['w1']+values['b1'],0)@values['w2']+values['b2']
    reference=np.exp(logits-logits.max(axis=1,keepdims=True));reference/=reference.sum(axis=1,keepdims=True)
    actual=ort.InferenceSession(str(folder/'intent_ann.onnx'),providers=['CPUExecutionProvider']).run(None,{'features':x})[0]
    np.testing.assert_allclose(actual,reference,rtol=1e-5,atol=1e-6)
    report={'model':'intent_ann.onnx','runtime':'onnxruntime','opset':17,'examples_checked':len(texts),
            'max_probability_difference':float(np.max(np.abs(actual-reference))),
            'predictions_identical':bool(np.array_equal(actual.argmax(axis=1),reference.argmax(axis=1))),
            'source':'Custom ANN weights trained with training/intents.json, not a pretrained chat LLM.'}
    (folder/'onnx_export.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
if __name__=='__main__':export_model()
