"""Offline prototype review: no target connection, no NPU execution claim."""
from pathlib import Path
import hashlib
import re
import subprocess
import numpy as np
import pytest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
GEN=ROOT/'results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate'
EXPORT=ROOT/'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq'

HARNESS=r'''
#define _GNU_SOURCE
#include <sys/mman.h>
#include <stdio.h>
#include <stdlib.h>
#include <setjmp.h>
#include "PORTABLE"
#include "ACCUM"
static jmp_buf jump;
static int expect;
#define CHECK(v) do{if(!(v)){fprintf(stderr,"line%d %s\n",__LINE__,#v);exit(91);}}while(0)
_Noreturn void s6_compat_fail(void){CHECK(expect);longjmp(jump,1);}
static void reject(unsigned layer){
    unsigned char snapshot[0x4000];memcpy(snapshot,(void *)0x34240000,sizeof snapshot);
    expect=1;if(!setjmp(jump)){s6_requantize_accum(layer);CHECK(0);}expect=0;
    CHECK(!memcmp(snapshot,(void *)0x34240000,sizeof snapshot));
}
int main(int argc,char **argv){
    CHECK(argc==4);
    void *a=mmap((void *)0x34240000,0x4000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);CHECK(a==(void *)0x34240000);
    unsigned char *raw=(void *)0x34242000;
    unsigned n[3]={256,128,5},offset[3]={1024,512,128};int scenario=atoi(argv[1]);
    if(scenario==0){
        for(uint32_t u=0;u<UINT32_C(16777216);u++){
            unsigned char bytes[3]={(unsigned char)u,(unsigned char)(u>>8),(unsigned char)(u>>16)};
            int32_t expected=(int32_t)((int64_t)u-(u>=8388608?16777216:0));CHECK(signed24(bytes)==expected);
        }
    }else if(scenario==1){
        FILE *f=fopen(argv[2],"rb"),*o=fopen(argv[3],"wb");CHECK(f && o);
        for(unsigned row=0;row<1024;row++)for(unsigned layer=0;layer<3;layer++){
            unsigned char snapshot[0x4000];memset(a,0xa5,0x4000);
            CHECK(fread(raw,3,n[layer],f)==n[layer]);memcpy(snapshot,a,sizeof snapshot);
            s6_requantize_accum(layer);
            CHECK(!memcmp(snapshot,a,offset[layer]));
            CHECK(!memcmp(snapshot+offset[layer]+n[layer],(unsigned char *)a+offset[layer]+n[layer],0x4000-offset[layer]-n[layer]));
            CHECK(fwrite((unsigned char *)a+offset[layer],1,n[layer],o)==n[layer]);
        }
        CHECK(fgetc(f)==EOF);CHECK(!fclose(f) && !fclose(o));
    }else if(scenario==2){
        reject(3);reject(0xffffffffu);
        for(unsigned layer=0;layer<3;layer++)for(unsigned j=0;j<n[layer];j++)for(unsigned sign=0;sign<2;sign++){
            memset(raw,0,768);raw[3*j]=sign?0:255;raw[3*j+1]=sign?0:255;raw[3*j+2]=sign?128:127;
            reject(layer);
        }
    }else CHECK(0);
    CHECK(!munmap(a,0x4000));return 0;
}
'''

@pytest.fixture(scope='module')
def native(tmp_path_factory):
    p=tmp_path_factory.mktemp('signed24');c=p/'test.c'
    c.write_text(HARNESS.replace('PORTABLE',str(ROOT/'tools/board_deployment/portable_qdq/portable_qdq.c')).replace('ACCUM',str(HERE/'accum.c')))
    r=subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffp-contract=off','-fno-fast-math','-fexcess-precision=standard',str(c),'-lm','-o',str(p/'test')],capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stderr
    return p/'test'

@pytest.mark.parametrize('scenario',[0,2])
def test_all_signed24_words_and_out_of_bound_fail_closed(native,scenario):
    r=subprocess.run([str(native),str(scenario),'/dev/null','/dev/null'],capture_output=True,text=True,timeout=10)
    assert r.returncode==0,r.stderr

def test_1024_original_rows_native_requantization(native,tmp_path):
    import onnx
    import onnxruntime as ort
    raw=(EXPORT/'model_qdq_int8.onnx').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d'
    assert hashlib.sha256((EXPORT/'validation_vectors.npz').read_bytes()).hexdigest()=='cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb'
    m=onnx.shape_inference.infer_shapes(onnx.load_from_string(raw))
    arrays={v.name:onnx.numpy_helper.to_array(v) for v in m.graph.initializer}
    producers={o:n for n in m.graph.node for o in n.output}
    gemms=[n for n in m.graph.node if n.op_type=='Gemm'][1:]
    layers=[];extra=[]
    for n in gemms:
        attrs={a.name:onnx.helper.get_attribute_value(a) for a in n.attribute}
        assert attrs=={'alpha':1.0,'beta':1.0,'transB':1}
        inp,w=[producers[x] for x in n.input[:2]]
        assert arrays[inp.input[2]]==-128 and np.all(arrays[w.input[2]]==0)
        out=next(x.output[0] for x in m.graph.node if x.op_type=='QuantizeLinear' and x.input[0]==n.output[0])
        extra.extend([inp.input[0],out]);layers.append((inp,w,out))
        assert np.max(np.abs(arrays[w.input[0]].astype('i8')).sum(1)*255)<2**23
    vi={v.name:v for v in list(m.graph.value_info)+list(m.graph.output)}
    m.graph.output.extend(vi[n] for n in extra)
    options=ort.SessionOptions();options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    options.intra_op_num_threads=1;options.inter_op_num_threads=1
    s=ort.InferenceSession(m.SerializeToString(),options,providers=['CPUExecutionProvider'])
    vectors=np.load(EXPORT/'validation_vectors.npz',allow_pickle=False)
    feed=bytearray();expected=bytearray()
    for index,row in enumerate(vectors['x']):
        out=dict(zip([x.name for x in s.get_outputs()],s.run(None,{'input':row[None,:]})))
        np.testing.assert_array_equal(out['logits'].view('u4'),vectors['reference_logits'][index:index+1].view('u4'))
        for inp,w,name in layers:
            # Host integer reference only; real deployment must obtain this
            # from NPU. No CPU dot product exists in candidate accum.c.
            acc=(out[inp.input[0]].astype('i8')-arrays[inp.input[2]])@arrays[w.input[0]].astype('i8').T
            assert np.max(np.abs(acc))<2**23
            u=acc.reshape(-1)&0xffffff
            feed.extend(np.column_stack((u&255,(u>>8)&255,(u>>16)&255)).astype('u1').tobytes())
            expected.extend(out[name].tobytes())
    f=tmp_path/'input.bin';o=tmp_path/'output.bin';f.write_bytes(feed)
    r=subprocess.run([str(native),'1',str(f),str(o)],capture_output=True,text=True,timeout=10)
    assert r.returncode==0,r.stderr
    assert o.read_bytes()==expected and len(expected)==1024*(256+128+5)

def descriptors(text,typ):
    return re.findall(r'static const '+typ+r' .*?\n  \};',text,re.S)

def fields(text):return dict(re.findall(r'^    \.(\w+) = (-?\d+),$',text,re.M))

def test_independent_descriptor_routing_and_dma_diff():
    original=(GEN/'nsl_qcfs_seed0.c').read_text();derived=(HERE/'accum_epochs.c').read_text()
    assert hashlib.sha256(original.encode()).hexdigest()=='8b7a8703240811f4b4f12517f33ce5c77bc004911c088514435340bc92c3b43e'
    for e,n,k,dma,arith,conv,frames,old_offset in [(19,256,16,8,3,1,16,1024),(31,128,16,5,1,1,8,512),(43,5,5,2,3,0,1,128)]:
        old=re.search(rf'static void LL_ATON_Start_EpochBlock_{e}\(.*?\n\}}',original,re.S).group()
        new=re.search(rf'static void SM05_Start_{e}\(.*?\n\}}',derived,re.S).group()
        a=descriptors(old,'LL_Convacc_InitTypeDef');b=descriptors(new,'LL_Convacc_InitTypeDef')
        assert len(a)==len(b)==(1 if e==43 else 2)
        assert a[:-1]==b[:-1]
        diff={k:(fields(a[-1])[k],v) for k,v in fields(b[-1]).items() if v!=fields(a[-1])[k]}
        assert diff=={'rounding_o':('1','0'),'outbytes_o':('2','3'),'shift_o':(str(6 if e==19 else 5),'0')}
        a=descriptors(old,'LL_Streng_TensorInitTypeDef');b=descriptors(new,'LL_Streng_TensorInitTypeDef')
        assert len(a)==len(b) and a[:-1]==b[:-1]
        diff={k:(fields(a[-1])[k],v) for k,v in fields(b[-1]).items() if v!=fields(a[-1])[k]}
        assert set(diff)=={'offset_start','offset_end','offset_limit','frame_offset','nbits_in','nbits_out'}
        f=fields(b[-1]);assert [int(f[k]) for k in ('offset_start','offset_end','offset_limit','frame_offset','frame_tot_cnt','nbits_in','nbits_out')]==[8192,8192+3*k,8192+3*n+64,3*k,frames,24,24]
        assert int(f['offset_end'])+(frames-1)*int(f['frame_offset'])==8192+3*n<16384-64
        assert 'LL_Arithacc_Init(' not in new
        for kind in ('Start','End'):
            before=re.search(rf'static void LL_ATON_{kind}_EpochBlock_{e}\(.*?\n\}}',original,re.S).group()
            after=re.search(rf'static void SM05_{kind}_{e}\(.*?\n\}}',derived,re.S).group()
            # Compare all routing tokens ignoring inherited comments.
            extract=lambda s:[tuple(v) for v in re.findall(r'ATONN_DSTPORT\(STRSWITCH, 0, (\w+), (\d+), (\d+)\).*?ATONN_SRCPORT\(STRSWITCH, 0, (\w+), (\d+), (\d+)\)',s)]
            expected=[]
            for v in extract(before):
                if v[:3]==('ARITH',str(arith),'0'):continue
                if v[:3]==('STRENG',str(dma),'0'):v=(*v[:3],'CONVACC',str(conv),'0')
                expected.append(v)
            assert extract(after)==expected
            units=lambda s:re.findall(r'\{ \{(\w+), (\d+)\} \}',s)
            assert units(after)==[x for x in units(before) if x!=('ARITH',str(arith))]
            calls=re.findall(r'LL_(?:Switch_(?:Init|Deinit)|ATON_(?:Enable|Disable)Units_Init)\(\w+, (\d+)\);',after)
            assert list(map(int,calls))==([3,4] if e==43 else [6,6])
