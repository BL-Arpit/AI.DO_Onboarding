"""No live service or native ONNX Runtime sessions: execute ONNX graphs in NumPy."""
import sys
from pathlib import Path
from types import SimpleNamespace
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
import os
os.chdir(root)
import onnx
from onnx.reference import ReferenceEvaluator
import onnxruntime as ort
class OfflineSession:
    def __init__(self,path,*args,**kwargs):
        self.graph=onnx.load(path)
        self.evaluator=ReferenceEvaluator(self.graph)
    def run(self,outputs,inputs):return self.evaluator.run(outputs,inputs)
    def get_inputs(self):return [SimpleNamespace(name=x.name) for x in self.graph.graph.input]
ort.InferenceSession=OfflineSession
import pytest
print('OFFLINE ONNX reference evaluator; native ONNX Runtime validation excluded.',flush=True)
sys.exit(pytest.main(['-q','tests','-k','not chat_runs_onnx_and_matches_training_weights']))
