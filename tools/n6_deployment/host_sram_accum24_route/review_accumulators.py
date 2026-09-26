"""Independent saved NumPy AND scalar actual-NPU dot review; no device access."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import numpy as np
import onnx
import onnxruntime as ort

ROOT=Path(__file__).resolve().parents[3]
EXPORT=ROOT/'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq'

def require(ok,msg):
    if not ok:raise ValueError(msg)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def review(path):
    p=Path(path);require(p.is_absolute() and p==p.resolve() and p.parent==ROOT/'results','Wrong saved root')
    held={f.name:sha(f) for f in p.iterdir() if f.is_file()}
    require('RESULT.json' in held and 'FAILED.json' not in held,'Need completed diagnostic,not failed partial')
    j=lambda n:json.loads((p/n).read_bytes())
    intent=j('INTENT.json');result=j('RESULT.json')
    require(intent['kind']=='SM06_one_row_NPU_accumulator_diagnostic_not_acceptance','Wrong diagnostic kind')
    require(intent['original_row_id']==result['original_row_id']==2656 and result['sequence']==1,'Wrong row/sequence')
    require(result['research_measurement_accepted'] is False and result['power_measured'] is False and result['latency_validated'] is False,'False research claim')
    for group in ['sources','model_inputs']:
        for n,digest in intent[group].items():require(sha(Path(n))==digest,'Source/input changed')
    require(j('cleanup.json')['errors']==[],'Bad cleanup')
    require(sha(EXPORT/'model_qdq_int8.onnx')=='22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d','Original model changed')
    require(sha(EXPORT/'validation_vectors.npz')=='cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb','Original vectors changed')
    z=np.load(EXPORT/'validation_vectors.npz',allow_pickle=False);require(int(z['validation_row_ids'][20])==2656,'Wrong original index')
    m=onnx.shape_inference.infer_shapes(onnx.load(EXPORT/'model_qdq_int8.onnx'));arrays={v.name:onnx.numpy_helper.to_array(v) for v in m.graph.initializer}
    extra=[f'/layers/layers.{k}/Mul_1_output_0_QuantizeLinear_Output' for k in [1,3,5]]+['logits_QuantizeLinear_Output']
    vi={v.name:v for v in list(m.graph.value_info)+list(m.graph.output)};m.graph.output.extend(vi[n] for n in extra)
    options=ort.SessionOptions();options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_DISABLE_ALL;options.intra_op_num_threads=1;options.inter_op_num_threads=1
    s=ort.InferenceSession(m.SerializeToString(),options,providers=['CPUExecutionProvider'])
    outputs=dict(zip([x.name for x in s.get_outputs()],s.run(None,{'input':z['x'][20:21]})))
    require(outputs['logits'].tobytes()==z['reference_logits'][20].tobytes(),'Diagnostic graph changed final reference')
    report=[]
    for index,(epoch,layer,width,count) in enumerate([(19,2,256,256),(31,4,256,128),(43,6,128,5)]):
        before=(p/f'SM05_Start_{epoch}_activation.bin').read_bytes();after=(p/f'SM05_Post_{epoch}_activation.bin').read_bytes()
        require(len(before)==len(after)==16384,'Short capture')
        inputs=np.frombuffer(before,dtype='u1',count=width).astype('i8')
        expected_input=outputs[extra[index]].reshape(-1).astype('i8')+128
        require(np.array_equal(inputs,expected_input),'Upstream QCFS/quant input differs from original')
        weights=arrays[f'layers.{layer}.weight_quantized'].astype('i8')
        require(np.all(arrays[f'layers.{layer}.weight_zero_point']==0),'Nonzero weight point')
        parts=np.frombuffer(after,dtype='u1',offset=8192,count=3*count).reshape(-1,3).astype('i8')
        actual=parts[:,0]+256*parts[:,1]+65536*parts[:,2];actual=np.where(actual>=2**23,actual-2**24,actual)
        expected=weights@inputs
        scalar=np.array([sum(int(a)*int(b) for a,b in zip(row,inputs)) for row in weights],dtype='i8')
        require(np.array_equal(expected,scalar),'Independent integer controls disagree')
        require(np.array_equal(actual,expected),'Actual NPU dot differs from original integer dot')
        report.append(dict(original_dense_layer=layer//2+1,values=count,exact_integer_matches=count,
            minimum=int(actual.min()),maximum=int(actual.max())))
    for name,address in intent['points']:
        raw=(p/(name+'_mailbox.bin')).read_bytes();w=struct.unpack('<128I',raw)
        require(w[3]==4 and w[5:7]==(1,0) and w[8]==2656 and w[31]==0x534d3036,'Wrong captured execution identity')
        require(raw[128:292]==z['x'][20].tobytes(),'Wrong captured original inputs')
        context=j(name+'_context.json');require(context['pc']==address and context['primask']==1,'Wrong breakpoint stop')
        fp=j(name+'_fp.json');require((fp['fpscr']|fp['fpdscr'])&0x07c80000==0,'Wrong FP environment')
    final=(p/'final_mailbox.bin').read_bytes();w=struct.unpack('<128I',final)
    require(w[3]==5 and w[5:7]==(1,1) and w[31]==0x534d3036 and w[8]==w[19]==2656,'Wrong final execution identity')
    require(final[128:292]==z['x'][20].tobytes() and w[11:19]==(0,)*8,'Final input/API failure')
    require(final[320:340].hex()==result['output_hex'] and result['reference_hex']==z['reference_logits'][20].tobytes().hex(),'Saved output/reference drift')
    require(final[320:340]==z['reference_logits'][20].tobytes(),'Final row not bitwise equal')
    last=(p/'LL_ATON_End_EpochBlock_44_activation.bin').read_bytes()
    require(last[128:133]==outputs['logits_QuantizeLinear_Output'].tobytes(),'Final requantization mismatch')
    require(held=={f.name:sha(f) for f in p.iterdir() if f.is_file()},'Evidence changed')
    for group in ['sources','model_inputs']:
        for n,digest in intent[group].items():require(sha(Path(n))==digest,'Late source/input changed')
    return dict(saved_only=True,original_row_id=2656,original_validation_index=20,npu_integer_layers=report,
        final_output_bitwise_equal_values=5,full_1024_validation_accepted=False,energy_measured=False,research_measurement_accepted=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path)
    print(json.dumps(review(p.parse_args().directory),sort_keys=True,indent=2))
