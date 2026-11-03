"""Offline graph validation only; native runtime is not used by this adapter."""
import onnx
import numpy as np
from types import SimpleNamespace
from onnx.reference import ReferenceEvaluator
from onnx.reference.op_run import OpRun
class DequantizeLinear(OpRun):
    op_domain=''
    def _run(self,x,x_scale,x_zero_point=None,axis=1,block_size=0,output_dtype=0):
        if block_size or output_dtype:raise ValueError("Only opset-14 scalar/per-axis dequantization is supported.")
        scale=np.asarray(x_scale);zero=np.asarray(x_zero_point if x_zero_point is not None else 0)
        if scale.ndim==1 and scale.size>1:
            shape=[1]*x.ndim;shape[axis]=scale.size;scale=scale.reshape(shape)
            if zero.ndim:zero=zero.reshape(shape)
        return ((x.astype(np.float32)-zero.astype(np.float32))*scale,)
class ReferenceSession:
    def __init__(self,path,*args,**kwargs):
        self.graph=onnx.load(path);self.evaluator=ReferenceEvaluator(self.graph,new_ops=[DequantizeLinear])
    def run(self,outputs,inputs):return self.evaluator.run(outputs,inputs)
    def get_inputs(self):return [SimpleNamespace(name=x.name) for x in self.graph.graph.input]
