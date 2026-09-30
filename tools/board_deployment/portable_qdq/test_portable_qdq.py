"""Synthetic only: no original graph, vectors, checkpoint or device access."""
import copy
import ctypes as C
import importlib.util
import math
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import onnx
from onnx import helper as H, numpy_helper as N, TensorProto as T

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('portable_generator',HERE/'generate.py')
g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

def toy(dims=(2,2,2,2,2)):
    nodes=[]; initial=[]
    def arr(name,value,dtype):
        initial.append(N.from_array(np.array(value,dtype=dtype),name)); return name
    def node(op,inputs,out,**attrs):
        nodes.append(H.make_node(op,inputs,[out],**attrs)); return out
    def constant(name,value,dtype):
        return node('Constant',[],name,value=N.from_array(np.array(value,dtype=dtype)))
    low=constant('zero64',0,np.float64); high=constant('one64',1,np.float64)
    literals=[]
    for i in range(3):
        literals.append([constant(f'levelmul{i}',4,np.float32),
                         constant(f'half{i}',0.5,np.float32),
                         constant(f'leveldiv{i}',4,np.float32)])
    for i in range(4):
        ni,no=dims[i:i+2]
        arr(f'w{i}',np.resize([[1,-1],[2,3]],(no,ni)),np.int8)
        arr(f'ws{i}',np.resize([.25,.125],no),np.float32); arr(f'wz{i}',np.resize([-1,1],no),np.int8)
        arr(f'b{i}',np.resize([2,-4],no),np.int32); arr(f'bs{i}',np.resize([.03125,.0625],no),np.float32)
        arr(f'bz{i}',np.zeros(no),np.int32)
        node('DequantizeLinear',[f'w{i}',f'ws{i}',f'wz{i}'],f'wd{i}',axis=0)
        node('DequantizeLinear',[f'b{i}',f'bs{i}',f'bz{i}'],f'bd{i}',axis=0)
    cast=[]
    for i in range(3):
        cast.append([node('Cast',[low],f'low{i}',to=1),node('Cast',[high],f'high{i}',to=1)])
    def qdq(value,name):
        s=arr(name+'s',.125,np.float32); z=arr(name+'z',-3,np.int8)
        q=node('QuantizeLinear',[value,s,z],name+'q')
        return node('DequantizeLinear',[q,s,z],name)
    current=qdq('input','inputdq')
    for i in range(4):
        current=node('Gemm',[current,f'wd{i}',f'bd{i}'],f'gemm{i}',alpha=1.,beta=1.,transB=1)
        current=qdq(current,'logits' if i==3 else f'affine{i}')
        if i<3:
            theta=arr(f'theta{i}',2.,np.float32)
            current=node('Div',[current,theta],f'div{i}')
            current=node('Clip',[current,*cast[i]],f'clip{i}')
            current=node('Mul',[current,literals[i][0]],f'mul{i}')
            current=node('Add',[current,literals[i][1]],f'add{i}')
            current=node('Floor',[current],f'floor{i}')
            current=node('Div',[current,literals[i][2]],f'div2{i}')
            current=node('Mul',[current,theta],f'mul2{i}')
            current=qdq(current,f'act{i}')
    graph=H.make_graph(nodes,'tiny', [H.make_tensor_value_info('input',T.FLOAT,[1,dims[0]])],
                       [H.make_tensor_value_info('logits',T.FLOAT,[1,dims[-1]])], initial)
    model=H.make_model(graph,opset_imports=[H.make_opsetid('',17)],ir_version=8)
    onnx.checker.check_model(model)
    return model

def parse(model): return g.parse_graph(model.SerializeToString(),(2,2,2,2,2))

class ParserTests(unittest.TestCase):
    def test_positive_complete_graph(self):
        p=parse(toy()); self.assertEqual(p['node_count'],66)
        self.assertEqual(sum(x['weights'].size for x in p['layers']),16)
        self.assertEqual(p['layers'][0]['weights'].dtype,np.int8)
        self.assertEqual(p['layers'][0]['weight_scale'].tolist(),[.25,.125])
    def test_emit_keeps_int8_and_hex_float(self):
        c=g.emit_c(parse(toy()))
        self.assertIn('static const int8_t l0_weights[4]',c)
        self.assertIn('0x1.0000000000000p-2f',c)
        self.assertNotIn('static const float l0_weights',c)
    def negative(self,change):
        m=toy(); change(m)
        with self.assertRaises((ValueError,onnx.onnx_cpp2py_export.checker.ValidationError)):
            parse(m)
    def test_unsupported_op_rejected(self):
        self.negative(lambda m:setattr(next(n for n in m.graph.node if n.op_type=='Floor'),'op_type','Relu'))
    def test_unknown_attribute_rejected(self):
        self.negative(lambda m:next(n for n in m.graph.node if n.op_type=='Gemm').attribute.append(H.make_attribute('transA',0)))
    def test_wrong_gemm_transpose_rejected(self):
        def mutate(m):
            next(a for n in m.graph.node if n.op_type=='Gemm' for a in n.attribute if a.name=='transB').i=0
        self.negative(mutate)
    def test_wrong_axis_rejected(self):
        self.negative(lambda m:setattr(next(a for n in m.graph.node for a in n.attribute if a.name=='axis'),'i',1))
    def test_extra_initializer_rejected(self):
        self.negative(lambda m:m.graph.initializer.append(N.from_array(np.array(0,np.float32),'unused')))
    def test_extra_node_rejected(self):
        self.negative(lambda m:m.graph.node.append(H.make_node('Identity',['logits'],['unused'])))
    def test_duplicate_initializer_rejected(self):
        self.negative(lambda m:m.graph.initializer.append(copy.deepcopy(m.graph.initializer[0])))
    def test_external_data_rejected(self):
        self.negative(lambda m:setattr(m.graph.initializer[0],'data_location',T.EXTERNAL))
    def test_bad_scale_rejected(self):
        def mutate(m):
            t=next(x for x in m.graph.initializer if x.name=='ws0')
            t.CopyFrom(N.from_array(np.array([.25,0],np.float32),'ws0'))
        self.negative(mutate)
    def test_int32_nonzero_zero_point_rejected(self):
        def mutate(m):
            t=next(x for x in m.graph.initializer if x.name=='bz0')
            t.CopyFrom(N.from_array(np.array([1,0],np.int32),'bz0'))
        self.negative(mutate)
    def test_shape_rejected(self):
        self.negative(lambda m:setattr(m.graph.input[0].type.tensor_type.shape.dim[1],'dim_value',3))
    def test_threshold_binding_rejected(self):
        def mutate(m):
            next(n for n in m.graph.node if n.output[0]=='mul20').input[1]='theta1'
        self.negative(mutate)
    def test_qdq_scale_binding_rejected(self):
        def mutate(m):
            next(n for n in m.graph.node if n.output[0]=='affine0').input[1]='inputdqs'
        self.negative(mutate)
    def test_nonfinite_rejected(self):
        def mutate(m):
            t=next(x for x in m.graph.initializer if x.name=='theta0')
            t.CopyFrom(N.from_array(np.array(np.nan,np.float32),'theta0'))
        self.negative(mutate)
    def test_wrong_opset_rejected(self):
        self.negative(lambda m:setattr(m.opset_import[0],'version',18))

def reference(row,model):
    # Independent tiny NumPy operator sequence; no original data / ORT invocation.
    def qdq(x,q):
        y=np.rint(np.divide(x,np.float32(q['scale']),dtype=np.float32))
        y=np.clip(y+np.float32(q['zero']),-128,127).astype(np.int8)
        return (y.astype(np.float32)-np.float32(q['zero']))*np.float32(q['scale'])
    x=qdq(np.array(row,np.float32),model['input_quant'])
    for i,p in enumerate(model['layers']):
        w=(p['weights'].astype(np.float32)-p['weight_zero'][:,None])*p['weight_scale'][:,None]
        x=np.matmul(w,x)+p['bias'].astype(np.float32)*p['bias_scale']
        x=qdq(x,p['output_quant'])
        if i<3:
            x=x/np.float32(p['threshold'])
            x=np.clip(x,np.float32(0),np.float32(1))
            x=x*np.float32(4); x=x+np.float32(.5); x=np.floor(x)
            x=x/np.float32(4); x=x*np.float32(p['threshold'])
            x=qdq(x,p['activation_quant'])
    return x

class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='portable-qdq-toy-')
        p=Path(cls.tmp.name); cls.model=parse(toy())
        (p/'toy.c').write_text(g.emit_c(cls.model)+
            '\nint tiny(const float*x,float*y){return pq_infer(&spikeids_qdq_model,x,2,y,2);}\n')
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-O2','-fPIC','-shared',
                        '-fno-fast-math','-ffp-contract=off','-fexcess-precision=standard',
                        '-I',str(HERE),str(HERE/'portable_qdq.c'),str(p/'toy.c'),'-lm','-o',str(p/'toy.so')],
                       check=True,timeout=30,capture_output=True)
        cls.lib=C.CDLL(str(p/'toy.so'))
        cls.lib.pq_quantize.argtypes=[C.c_float,C.c_float,C.c_int32,C.POINTER(C.c_int8)]
        cls.lib.tiny.argtypes=[C.POINTER(C.c_float),C.POINTER(C.c_float)]
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def test_environment(self): self.assertEqual(self.lib.pq_environment(),1)
    def test_signed_ties_even_not_roundf(self):
        for x,expected in [(-3.5,-4),(-2.5,-2),(-1.5,-2),(-.5,0),(.5,0),(1.5,2),(2.5,2),(3.5,4)]:
            with self.subTest(x=x):
                y=C.c_int8(99); self.assertEqual(self.lib.pq_quantize(x,1,0,C.byref(y)),0)
                self.assertEqual(y.value,expected)
    def test_round_before_odd_zero_point(self):
        y=C.c_int8(); self.assertEqual(self.lib.pq_quantize(.5,1,1,C.byref(y)),0)
        self.assertEqual(y.value,1)  # round(.5)+1, not round(.5+1)=2
    def test_saturation_and_finite_division_overflow(self):
        for x,scale,expected in [(1e30,1,127),(-1e30,1,-128),(1e30,1e-30,127),(-1e30,1e-30,-128)]:
            y=C.c_int8(); self.assertEqual(self.lib.pq_quantize(x,scale,-3,C.byref(y)),0)
            self.assertEqual(y.value,expected)
    def test_zero_scale_rejected(self):
        y=C.c_int8(99); self.assertNotEqual(self.lib.pq_quantize(1,0,0,C.byref(y)),0)
        self.assertEqual(y.value,99)
    def test_nonfinite_rejected(self):
        for x in [math.inf,-math.inf,math.nan]:
            y=C.c_int8(99); self.assertNotEqual(self.lib.pq_quantize(x,1,0,C.byref(y)),0)
            self.assertEqual(y.value,99)
    def test_tiny_all_output_words(self):
        for row in [[0,0],[1,-1],[.5,2],[-2,1.125],[20,-20],[.0625,-.0625]]:
            x=(C.c_float*2)(*row); y=(C.c_float*2)(99,99)
            self.assertEqual(self.lib.tiny(x,y),0)
            self.assertEqual(bytes(y),reference(row,self.model).tobytes())
    def test_alias_input_output(self):
        x=(C.c_float*2)(.5,2)
        self.assertEqual(self.lib.tiny(x,x),0)
        self.assertEqual(bytes(x),reference([.5,2],self.model).tobytes())
    def test_failure_no_partial_output(self):
        x=(C.c_float*2)(math.nan,2); y=(C.c_float*2)(99,-99)
        before=bytes(y); self.assertNotEqual(self.lib.tiny(x,y),0); self.assertEqual(bytes(y),before)

if __name__=='__main__': unittest.main()
