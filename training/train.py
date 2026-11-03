"""Train a small, reproducible NumPy MLP for local onboarding intent recognition."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.agents.chat import tokens,vectorize,chat_agent,load_model,MODEL_DIR


def train():
    examples=json.loads((ROOT/'training/intents.json').read_text())
    labels=sorted(examples)
    vocabulary={word:i for i,word in enumerate(sorted({word for phrases in examples.values() for text in phrases for word in tokens(text)}))}
    rows=[(text,index) for index,label in enumerate(labels) for text in examples[label]]
    x=np.stack([vectorize(text,vocabulary) for text,_ in rows]);y=np.array([label for _,label in rows])
    rng=np.random.default_rng(42);hidden=48
    parameters={'w1':rng.normal(0,.12,(x.shape[1],hidden)).astype(np.float32),'b1':np.zeros(hidden,dtype=np.float32),
                'w2':rng.normal(0,.12,(hidden,len(labels))).astype(np.float32),'b2':np.zeros(len(labels),dtype=np.float32)}
    # Full-batch Adam; train only on the explicit training file, never held-out text.
    m={key:np.zeros_like(value) for key,value in parameters.items()};v={key:np.zeros_like(value) for key,value in parameters.items()}
    for step in range(1,1201):
        pre=x@parameters['w1']+parameters['b1'];h=np.maximum(pre,0)
        logits=h@parameters['w2']+parameters['b2'];p=np.exp(logits-logits.max(axis=1,keepdims=True));p/=p.sum(axis=1,keepdims=True)
        # Mild label smoothing reduces extreme confidence on small data.
        target=np.full_like(p,.04/len(labels));target[np.arange(len(y)),y]+=.96
        grad=(p-target)/len(y)
        dh=(grad@parameters['w2'].T)*(pre>0)
        gradients={'w2':h.T@grad+.0004*parameters['w2'],'b2':grad.sum(axis=0),
                   'w1':x.T@dh+.0004*parameters['w1'],'b1':dh.sum(axis=0)}
        for key in parameters:
            m[key]=.9*m[key]+.1*gradients[key];v[key]=.999*v[key]+.001*gradients[key]**2
            parameters[key]-=.008*(m[key]/(1-.9**step))/(np.sqrt(v[key]/(1-.999**step))+1e-8)
    MODEL_DIR.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(MODEL_DIR/'weights.npz',**parameters)
    metadata={'architecture':'L2-normalized word/bigram inputs -> Dense(48, ReLU) -> Dense(17, softmax)',
              'seed':42,'labels':labels,'vocabulary':vocabulary,'training_examples':len(rows),
              'parameters':sum(p.size for p in parameters.values()),'epochs':1200,
              'training_sha256':hashlib.sha256((ROOT/'training/intents.json').read_bytes()).hexdigest()}
    (MODEL_DIR/'metadata.json').write_text(json.dumps(metadata,indent=2))
    from training.export_onnx import export_model
    export_model();load_model.cache_clear()
    heldout=json.loads((ROOT/'training/evaluation.json').read_text())
    results=[{'text':text,'expected':label,**chat_agent(text)} for label,phrases in heldout.items() for text in phrases]
    report={'training_examples':len(rows),'held_out_examples':len(results),
            'top1_accuracy':sum(r['predicted_intent']==r['expected'] for r in results)/len(results),
            'guarded_accuracy':sum(r['intent']==r['expected'] for r in results)/len(results),
            'accepted_coverage':sum(r['intent']!='unknown' for r in results if r['expected']!='unknown')/sum(r['expected']!='unknown' for r in results),
            'limitations':'Small curated English domain dataset, not a production language benchmark. Confidence is not a calibrated probability.',
            'results':results}
    (MODEL_DIR/'evaluation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({key:value for key,value in report.items() if key!='results'},indent=2))
    print('Weights:',(MODEL_DIR/'weights.npz').stat().st_size,'bytes')
if __name__=='__main__':train()
