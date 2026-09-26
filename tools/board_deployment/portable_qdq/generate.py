"""Strict fixed QDQ -> portable constants. No inference, training or export.

parse_graph accepts tiny structurally identical fixtures for tests. The CLI has
no graph/shape/source override and accepts ONLY the literal selected bundle.
"""
import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

import numpy as np
import onnx
from onnx import helper, numpy_helper, TensorProto as T, AttributeProto as A

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BUNDLE = ROOT / 'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq'
MODEL_SHA = '22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d'
VECTORS_SHA = 'cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb'
DIMS = (41, 256, 256, 128, 5)

def require(ok, label):
    if not ok:
        raise ValueError(label)

def parse_graph(raw, dims=DIMS):
    require(len(dims)==5 and all(type(x) is int and 0<x<=256 for x in dims), 'dimensions')
    m=onnx.load_model_from_string(raw)
    require([(x.domain,x.version) for x in m.opset_import]==[('',17)], 'opset')
    require(not m.functions and not m.training_info and not m.graph.sparse_initializer, 'graph extensions')
    g=m.graph
    require(len(g.input)==len(g.output)==1, 'I/O count')
    for v,width in ((g.input[0],dims[0]),(g.output[0],dims[-1])):
        ty=v.type.tensor_type
        require(ty.elem_type==T.FLOAT and [x.dim_value for x in ty.shape.dim]==[1,width]
                and all(not x.dim_param for x in ty.shape.dim), 'I/O shape/type')
    used_nodes=set(); used_tensors=set(); producers={}; tensors={}
    def array(t):
        require(t.data_location==T.DEFAULT and not t.external_data, 'external tensor')
        require(t.data_type in (T.FLOAT,T.DOUBLE,T.INT8,T.INT32), 'tensor dtype')
        x=numpy_helper.to_array(t)
        require(np.isfinite(x).all(), 'nonfinite tensor')
        return x
    for t in g.initializer:
        require(t.name and t.name not in tensors and t.name!=g.input[0].name, 'initializer duplicate')
        tensors[t.name]=array(t)
    for i,n in enumerate(g.node):
        require(n.domain=='' and len(n.output)==1 and n.output[0] and
                n.output[0] not in producers and n.output[0] not in tensors and
                n.output[0]!=g.input[0].name, 'node output/domain')
        require(not any(a.type in (A.GRAPH,A.GRAPHS,A.TENSORS,A.SPARSE_TENSOR,A.SPARSE_TENSORS)
                        for a in n.attribute), 'nested attributes')
        producers[n.output[0]]=(i,n)
    def attrs(n, expected):
        require(len(n.attribute)==len(expected), 'attribute count')
        actual={a.name:(a.type,helper.get_attribute_value(a)) for a in n.attribute}
        require(len(actual)==len(n.attribute) and actual==expected, 'attributes')
    def node(name, op, arity, expected=None):
        require(name in producers, 'missing producer')
        i,n=producers[name]
        require(n.op_type==op and len(n.input)==arity and all(n.input), 'operator/arity')
        attrs(n, {} if expected is None else expected)
        used_nodes.add(i)
        return n
    def const(name):
        if name in tensors:
            used_tensors.add(name); return tensors[name]
        require(name in producers, 'missing constant')
        i,n=producers[name]
        if n.op_type=='Constant':
            require(not n.input and len(n.attribute)==1 and n.attribute[0].name=='value'
                    and n.attribute[0].type==A.TENSOR, 'constant form')
            used_nodes.add(i); return array(n.attribute[0].t)
        n=node(name,'Cast',1,{'to':(A.INT,T.FLOAT)})
        x=const(n.input[0]); require(x.shape==() and x.dtype==np.float64, 'cast source')
        y=x.astype(np.float32); require(np.isfinite(y).all(), 'cast overflow'); return y
    def scalar(name, dtype):
        x=const(name); require(x.shape==() and x.dtype==np.dtype(dtype), 'scalar type/shape')
        return x.item()
    def qparams(scale,zero):
        s=scalar(scale,np.float32); z=scalar(zero,np.int8)
        require(s>0, 'quantization scale'); return {'scale':s,'zero':z}
    def qdq(output):
        dq=node(output,'DequantizeLinear',3)
        q=node(dq.input[0],'QuantizeLinear',3)
        require(list(q.input[1:])==list(dq.input[1:]), 'QDQ parameter identity')
        return q.input[0],qparams(*q.input[1:])
    def param(output, shape, dtype):
        n=node(output,'DequantizeLinear',3,{'axis':(A.INT,0)})
        v,s,z=(const(x) for x in n.input)
        require(v.shape==shape and v.dtype==np.dtype(dtype), 'parameter type/shape')
        require(s.shape==(shape[0],) and s.dtype==np.float32 and (s>0).all(), 'per-channel scale')
        require(z.shape==s.shape and z.dtype==v.dtype, 'per-channel zero')
        if v.dtype==np.int32:
            require((z==0).all(), 'int32 DQ zero must be zero')
        return v,s,z
    def qcfs(output):
        # Walk real connectivity backwards, retaining every scalar rather than
        # guessing stage labels or assuming that Div/Mul threshold are equal.
        mul=node(output,'Mul',2); threshold_name=mul.input[1]
        div=node(mul.input[0],'Div',2)
        floor=node(div.input[0],'Floor',1)
        add=node(floor.input[0],'Add',2)
        levels=node(add.input[0],'Mul',2)
        clip=node(levels.input[0],'Clip',3)
        first=node(clip.input[0],'Div',2)
        require(first.input[1]==threshold_name, 'threshold identity')
        p=dict(threshold=scalar(threshold_name,np.float32),
               clip_low=scalar(clip.input[1],np.float32),clip_high=scalar(clip.input[2],np.float32),
               levels_mul=scalar(levels.input[1],np.float32),half=scalar(add.input[1],np.float32),
               levels_div=scalar(div.input[1],np.float32))
        require(p['threshold']>0 and [p[k] for k in ('clip_low','clip_high','levels_mul','half','levels_div')]
                ==[0.0,1.0,4.0,0.5,4.0], 'QCFS recipe')
        return first.input[0],p
    current=g.output[0].name; layers=[]
    for index in reversed(range(4)):
        current,oq=qdq(current)
        n=node(current,'Gemm',3,{'alpha':(A.FLOAT,1.0),'beta':(A.FLOAT,1.0),'transB':(A.INT,1)})
        w,ws,wz=param(n.input[1],(dims[index+1],dims[index]),np.int8)
        b,bs,_=param(n.input[2],(dims[index+1],),np.int32)
        layer=dict(inputs=dims[index],outputs=dims[index+1],weights=w,weight_scale=ws,
                   weight_zero=wz,bias=b,bias_scale=bs,output_quant=oq)
        layers.insert(0,layer); current=n.input[0]
        if index:
            current,aq=qdq(current)
            current,recipe=qcfs(current)
            # This activation belongs to preceding layer, filled after reversal.
            layer['preceding_activation']=(aq,recipe)
    current,iq=qdq(current)
    require(current==g.input[0].name, 'input chain')
    for index in range(3):
        aq,recipe=layers[index+1].pop('preceding_activation')
        layers[index].update(recipe); layers[index]['activation_quant']=aq
    require(used_nodes==set(range(len(g.node))) and used_tensors==set(tensors), 'unconsumed graph content')
    require(len(g.node)==66, 'fixed operator count')
    return dict(input_quant=iq,layers=layers,graph_sha256=hashlib.sha256(raw).hexdigest(),
                node_count=len(g.node),initializer_count=len(tensors))

def f32(value):
    require(np.isfinite(value), 'C float nonfinite')
    return float(np.float32(value)).hex()+'f'

def emit_c(model):
    lines=['/* Generated constants; original INT8 storage, no model re-export. */',
           '#include "portable_qdq.h"',
           f'const char spikeids_qdq_sha256[65]="{model["graph_sha256"]}";',
           f'const char spikeids_validation_sha256[65]="{VECTORS_SHA}";']
    array_fields=(('weights','int8_t'),('weight_zero','int8_t'),('weight_scale','float'),
                  ('bias','int32_t'),('bias_scale','float'))
    for index,layer in enumerate(model['layers']):
        for key,ctype in array_fields:
            values=layer[key].reshape(-1)
            literals=[f32(x) if ctype=='float' else str(int(x)) for x in values]
            lines.append(f'static const {ctype} l{index}_{key}[{len(values)}]={{')
            lines.extend(','.join(literals[i:i+16])+',' for i in range(0,len(values),16))
            lines.append('};')
    def qtext(q): return '{'+f32(q['scale'])+','+str(q['zero'])+'}'
    lines.append('const pq_model spikeids_qdq_model={.input_quant='+qtext(model['input_quant'])+',.layers={')
    for index,layer in enumerate(model['layers']):
        fields=[f'.inputs={layer["inputs"]}',f'.outputs={layer["outputs"]}']
        fields += [f'.{key}=l{index}_{key}' for key,_ in array_fields]
        fields.append('.output_quant='+qtext(layer['output_quant']))
        if index<3:
            fields += [f'.{key}={f32(layer[key])}' for key in
                       ('threshold','clip_low','clip_high','levels_mul','half','levels_div')]
            fields.append('.activation_quant='+qtext(layer['activation_quant']))
        lines.append('{'+','.join(fields)+'},')
    lines.append('}};')
    return '\n'.join(lines)+'\n'

def snapshot(path):
    p=Path(path); require(p.is_absolute() and p.resolve()==p and p.is_file(), 'canonical file')
    before=p.stat(); raw=p.read_bytes(); after=p.stat()
    fields=('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
    require(all(getattr(before,k)==getattr(after,k) for k in fields), 'file changed during read')
    return raw,dict(sha256=hashlib.sha256(raw).hexdigest(),**{k:getattr(before,k) for k in fields})

def final_stats(pins):
    for path,pin in pins.items():
        p=Path(path); require(p.resolve()==p, 'late symlink')
        st=p.stat(follow_symlinks=False)
        require(all(getattr(st,k)==v for k,v in pin.items() if k.startswith('st_')), 'late file change')

def owned(directory, identity):
    st=directory.stat(follow_symlinks=False)
    require(directory.resolve()==directory and stat.S_ISDIR(st.st_mode) and
            (st.st_dev,st.st_ino)==identity, 'owned directory changed')

def create_output(output):
    output=Path(output).absolute()
    require(not output.exists() and not output.is_symlink() and
            output.parent.resolve()==output.parent and output.parent.is_dir(), 'fresh canonical output')
    fd=os.open(output.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    parent=os.fstat(fd)
    return output,fd,(parent.st_dev,parent.st_ino)

def publish_directory(output, fd, parent_identity):
    owned(output.parent,parent_identity)
    os.mkdir(output.name,dir_fd=fd)
    st=output.stat(follow_symlinks=False)
    identity=(st.st_dev,st.st_ino)
    owned(output,identity)
    return identity

def write_new(directory,identity,name,data):
    require(Path(name).name==name, 'flat output name')
    owned(directory,identity)
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        require((os.fstat(fd).st_dev,os.fstat(fd).st_ino)==identity, 'output descriptor identity')
        out=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        with os.fdopen(out,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
    finally: os.close(fd)

def generate(output):
    output,parent_fd,parent_identity=create_output(output)
    identity=None
    pins={}
    try:
        for p in (HERE/'generate.py',HERE/'portable_qdq.c',HERE/'portable_qdq.h',
                  BUNDLE/'model_qdq_int8.onnx',BUNDLE/'validation_vectors.npz'):
            raw,pins[str(p)]=snapshot(p)
        require(pins[str(BUNDLE/'model_qdq_int8.onnx')]['sha256']==MODEL_SHA and
                pins[str(BUNDLE/'validation_vectors.npz')]['sha256']==VECTORS_SHA, 'fixed inputs')
        graph,again=snapshot(BUNDLE/'model_qdq_int8.onnx')
        require(again==pins[str(BUNDLE/'model_qdq_int8.onnx')], 'graph changed')
        model=parse_graph(graph)
        generated=emit_c(model).encode()
        require(all(snapshot(p)[1]==pin for p,pin in pins.items()), 'input bookend')
        identity=publish_directory(output,parent_fd,parent_identity)
        write_new(output,identity,'model.c',generated)
        record=dict(schema_version=1,kind='portable_qdq_source_candidate',original_pins=pins,
                    graph_sha256=MODEL_SHA,validation_sha256=VECTORS_SHA,
                    nodes=model['node_count'],initializers=model['initializer_count'],
                    model_c_sha256=hashlib.sha256(generated).hexdigest(),
                    int8_weight_elements=sum(x['weights'].size for x in model['layers']),
                    inference_executed=False,numerical_parity_accepted=False,hardware_accepted=False)
        require(all(snapshot(p)[1]==pin for p,pin in pins.items()), 'final input bookend')
        write_new(output,identity,'MANIFEST.json',(json.dumps(record,sort_keys=True,indent=2)+'\n').encode())
        output_pins={str(output/n):snapshot(output/n)[1] for n in ('model.c','MANIFEST.json')}
        require(all(snapshot(p)[1]==pin for p,pin in pins.items()), 'last input hashes')
        owned(output.parent,parent_identity); owned(output,identity)
        require(set(os.listdir(output))=={'model.c','MANIFEST.json'}, 'output namespace')
        final_stats(pins|output_pins)
        return record
    except Exception as e:
        if identity is not None:
            try:
                write_new(output,identity,'FAILED.json',json.dumps({'kind':'source_generation_failure','error':str(e)}).encode())
            except (OSError,ValueError): pass  # Never write a marker in a foreign root.
        raise
    finally: os.close(parent_fd)

if __name__=='__main__':
    ap=argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument('--output-dir',required=True)
    args=ap.parse_args()
    print(json.dumps(generate(args.output_dir),sort_keys=True))
