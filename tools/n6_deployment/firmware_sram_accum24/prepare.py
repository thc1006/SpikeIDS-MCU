"""Derive candidate sources from immutable model/generated files; stdout only.

No compiler/device access, no in-place edit, no reference-logit fitting.
Callers inspect/test derived files before building or any hardware operation.
"""
from pathlib import Path
import hashlib
import json
import re
import numpy as np
import onnx

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
GEN=ROOT/'results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate'
GRAPH=ROOT/'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq/model_qdq_int8.onnx'

def pinned(path,sha):
    b=path.read_bytes()
    if hashlib.sha256(b).hexdigest()!=sha:raise ValueError('Original changed: '+str(path))
    return b

def function(source,kind,epoch):
    pattern=rf'static void LL_ATON_{kind}_EpochBlock_{epoch}\(const void \*epoch_block\)\n\{{.*?\n\}}'
    matches=re.findall(pattern,source,re.S)
    if len(matches)!=1:raise ValueError('Unexpected fixed callback')
    return matches[0]

def replace_field(block,field,old,new):
    pattern=rf'(?m)^(    \.{field} = ){old},$'
    block,n=re.subn(pattern,rf'\g<1>{new},',block)
    if n!=1:raise ValueError('Unexpected field: '+field)
    return block

def derive():
    source=pinned(GEN/'nsl_qcfs_seed0.c','8b7a8703240811f4b4f12517f33ce5c77bc004911c088514435340bc92c3b43e').decode()
    m=onnx.load_from_string(pinned(GRAPH,'22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d'))
    arrays={v.name:onnx.numpy_helper.to_array(v) for v in m.graph.initializer}
    producers={o:n for n in m.graph.node for o in n.output}
    gemms=[n for n in m.graph.node if n.op_type=='Gemm'];assert len(gemms)==4
    params=['/* Derived from original ONNX only; no validation outputs used. */','#include <stdint.h>']
    for i,n in enumerate(gemms[1:]):
        inp,w,bias=[producers[x] for x in n.input]
        assert inp.op_type==w.op_type==bias.op_type=='DequantizeLinear'
        assert arrays[inp.input[2]]==-128 and np.all(arrays[w.input[2]]==0) and np.all(arrays[bias.input[2]]==0)
        q=next(x for x in m.graph.node if x.op_type=='QuantizeLinear' and x.input[0]==n.output[0])
        weights=arrays[w.input[0]];assert weights.shape==[(256,256),(128,256),(5,128)][i]
        # All possible unsigned activation inputs; stronger than observed data.
        bound=np.abs(weights.astype('i8')).sum(1)*255
        assert np.all(bound<2**23)
        values={'scale':arrays[w.input[1]],'bias':arrays[bias.input[0]].astype('f4')*arrays[bias.input[1]]}
        for key,a in values.items():
            words=','.join('UINT32_C(0x%08x)'%v for v in a.astype('<f4').view('<u4').reshape(-1))
            params.append(f'static const uint32_t accum_{key}_{i}[{len(a)}]={{'+words+'};')
        params.append(f'static const int32_t accum_bound_{i}[{len(bound)}]={{'+','.join(str(v) for v in bound)+'};')
        params.append(f'#define ACCUM_INPUT_SCALE_{i} UINT32_C(0x{int(arrays[inp.input[1]].view("u4")):08x})')
        params.append(f'#define ACCUM_OUTPUT_SCALE_{i} UINT32_C(0x{int(arrays[q.input[1]].view("u4")):08x})')
        params.append(f'#define ACCUM_OUTPUT_ZERO_{i} ({int(arrays[q.input[2]])})')
    functions=[]
    for epoch,n,kernels,out_id,arith_id,final_unit,frames,original_out in [(19,256,16,8,3,1,16,1024),(31,128,16,5,1,1,8,512),(43,5,5,2,3,0,1,128)]:
        for kind in ('Start','End'):
            f=function(source,kind,epoch)
            f=f.replace(f'LL_ATON_{kind}_EpochBlock_{epoch}',f'SM05_{kind}_{epoch}',1)
            if kind=='Start':
                # Keep every input/weight field and the first accumulation pipe.
                conv=list(re.finditer(r'  static const LL_Convacc_InitTypeDef .*?\n  \};',f,re.S))
                assert len(conv)==(1 if epoch==43 else 2)
                hit=conv[-1];block=hit.group()
                block=replace_field(block,'shift_o',str(6 if epoch==19 else 5),'0')
                block=replace_field(block,'outbytes_o','2','3')
                block=replace_field(block,'rounding_o','1','0')
                # Keep saturation at signed24; mathematical full-domain bound
                # proves correct inputs cannot reach it. Keep raw_o=0 unchanged.
                f=f[:hit.start()]+block+f[hit.end():]
                f,count=re.subn(rf'  static const LL_Arithacc_InitTypeDef .*?\n  \}};\n\n  /\* Unit=ARITH_ACC_V2 \*/\n  LL_Arithacc_Init\({arith_id}, &\w+\);', '',f,flags=re.S)
                assert count==1
                outputs=list(re.finditer(r'  static const LL_Streng_TensorInitTypeDef \w+_dma_init_out_0_\d+ = \{.*?\n  \};',f,re.S));assert len(outputs)==1
                hit=outputs[0];block=hit.group()
                for field,old,new in [('offset_start',original_out,8192),('offset_end',original_out+kernels,8192+3*kernels),('offset_limit',original_out+n+64,8192+3*n+64),('frame_offset',kernels,3*kernels),('nbits_in',8,24),('nbits_out',8,24)]:
                    if epoch==43 and field=='offset_limit':old=200
                    block=replace_field(block,field,str(old),str(new))
                f=f[:hit.start()]+block+f[hit.end():]
                # Cache remains disabled by strict runtime gate; nevertheless
                # describe actual DMA output region for future cache review.
                pattern=r'LL_ATON_Cache_MCU_Invalidate_Range\(.*?, \d+\);'
                f,count=re.subn(pattern,f'LL_ATON_Cache_MCU_Invalidate_Range((uintptr_t)0x34242000UL, {3*n});',f);assert count==1
            # Remove only bias ARITH route and enable/disable entry. Reroute
            # existing output DMA directly from final convolution accumulator.
            lines=f.splitlines();removed=0;new=[]
            for line in lines:
                if f'LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, ARITH, {arith_id}, 0)' in line:
                    removed+=1;continue
                if '{ {ARITH, '+str(arith_id)+'} }' in line:removed+=1;continue
                if f'LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, STRENG, {out_id}, 0)' in line:
                    assert f'ATONN_SRCPORT(STRSWITCH, 0, ARITH, {arith_id}, 0)' in line
                    line=line.replace(f'ATONN_SRCPORT(STRSWITCH, 0, ARITH, {arith_id}, 0)',f'ATONN_SRCPORT(STRSWITCH, 0, CONVACC, {final_unit}, 0)')
                new.append(line)
            assert removed==2
            f='\n'.join(new)
            previous_count=4 if epoch==43 else 7
            f,count=re.subn(rf'(LL_Switch_(?:Init|Deinit)\(switch_\w+_{epoch}, ){previous_count}(\);)',rf'\g<1>{previous_count-1}\2',f);assert count==1
            units=5 if epoch==43 else 7
            f,count=re.subn(rf'(LL_ATON_(?:Enable|Disable)Units_Init\(\w+_{epoch}_all_units, ){units}(\);)',rf'\g<1>{units-1}\2',f);assert count==1
            # Provenance comments may describe original source fields; explicitly
            # mark transformations rather than silently claiming compiler output.
            functions.append(f'/* SM05 derived epoch{epoch}: exact-width candidate, NOT vendor-generated unmodified output. */\n'+f)
    return {'accum_params.h':'\n'.join(params)+'\n','accum_epochs.c':'\n\n'.join(functions)+'\n'}

if __name__=='__main__':print(json.dumps(derive()))
