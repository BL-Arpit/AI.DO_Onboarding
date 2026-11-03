"""Train only the intent head; pretrained MiniLM INT8 stays frozen.
Use --reference for local validation without native ONNX Runtime execution.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import sys,json,hashlib,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np

def train(reference=False):
    from app.agents.chat import MODEL_DIR,embed,load_encoder,predict
    if reference:
        from training.reference_encoder import ReferenceSession
        from tokenizers import Tokenizer
        tokenizer=Tokenizer.from_file(str(MODEL_DIR/'tokenizer.json'))
        tokenizer.enable_truncation(max_length=256);tokenizer.enable_padding(pad_id=0,pad_token='[PAD]')
        encoder=(ReferenceSession(MODEL_DIR/'model.onnx'),tokenizer)
    else:encoder=load_encoder()
    training=json.loads((ROOT/'training/intents.json').read_text())
    heldout=json.loads((ROOT/'training/evaluation.json').read_text())
    labels=sorted(training);rows=[(text,labels.index(label)) for label,phrases in training.items() for text in phrases]
    features=[]
    for i in range(0,len(rows),16):
        features.append(embed([text for text,_ in rows[i:i+16]],encoder))
        print('Encoded',min(i+16,len(rows)),'/',len(rows),flush=True)
    x=np.concatenate(features);y=np.array([index for _,index in rows])
    rng=np.random.default_rng(42);weights=rng.normal(0,.02,(384,len(labels))).astype(np.float32);bias=np.zeros(len(labels),dtype=np.float32)
    parameters={'weights':weights,'bias':bias};m={k:np.zeros_like(v) for k,v in parameters.items()};v={k:np.zeros_like(value) for k,value in parameters.items()}
    for step in range(1,801):
        logits=x@weights+bias;scores=np.exp(logits-logits.max(axis=1,keepdims=True));scores/=scores.sum(axis=1,keepdims=True)
        target=np.full_like(scores,.03/len(labels));target[np.arange(len(y)),y]+=.97;grad=(scores-target)/len(y)
        gradients={'weights':x.T@grad+.0002*weights,'bias':grad.sum(axis=0)}
        for key in parameters:
            m[key]=.9*m[key]+.1*gradients[key];v[key]=.999*v[key]+.001*gradients[key]**2
            parameters[key]-=.02*(m[key]/(1-.9**step))/(np.sqrt(v[key]/(1-.999**step))+1e-8)
    head={**parameters,'examples':x}
    np.savez_compressed(MODEL_DIR/'intent_head.npz',**head)
    meta={'architecture':'Frozen MiniLM-L6-v2 INT8 -> masked mean pooling -> L2 normalization -> linear softmax intent head',
          'labels':labels,'training_examples':len(rows),'seed':42,'encoder_parameters_finetuned':False,
          'encoder_source':json.loads((MODEL_DIR/'source.json').read_text()),
          'training_sha256':hashlib.sha256((ROOT/'training/intents.json').read_bytes()).hexdigest()}
    (MODEL_DIR/'metadata.json').write_text(json.dumps(meta,indent=2))
    results=[]
    for label,phrases in heldout.items():
        encoded=embed(phrases,encoder)
        results.extend({'text':text,'expected':label,**predict(vector,meta,head)} for text,vector in zip(phrases,encoded))
    report={'training_examples':len(rows),'held_out_examples':len(results),'inference_for_validation':'onnx_reference' if reference else 'onnxruntime',
            'top1_accuracy':sum(r['predicted_intent']==r['expected'] for r in results)/len(results),
            'guarded_accuracy':sum(r['intent']==r['expected'] for r in results)/len(results),
            'accepted_coverage':sum(r['intent']!='unknown' for r in results if r['expected']!='unknown')/sum(r['expected']!='unknown' for r in results),
            'limitations':'Small English curated evaluation. No live CPU latency or native runtime validation in reference mode.', 'results':results}
    (MODEL_DIR/'evaluation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--reference',action='store_true');args=parser.parse_args();train(args.reference)
