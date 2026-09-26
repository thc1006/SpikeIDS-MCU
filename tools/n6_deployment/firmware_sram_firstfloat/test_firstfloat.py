"""Actual C boundary, immutable generated descriptors and original ONNX controls.

Host controls do not certify NPU inference. No board access in this module.
"""
from pathlib import Path
import hashlib
import importlib.util
import re
import subprocess
import numpy as np
import pytest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
GEN=ROOT/'results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate'
ST=Path('/home/thc1006/opt/stedgeai/3.0/Middlewares/ST/AI/Npu/ll_aton')
EXPORT=ROOT/'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq'

def pinned(path,digest):
    value=path.read_bytes()
    assert hashlib.sha256(value).hexdigest()==digest
    return value

def generated():
    return pinned(GEN/'nsl_qcfs_seed0.c','8b7a8703240811f4b4f12517f33ce5c77bc004911c088514435340bc92c3b43e').decode()

HARNESS=r'''
#define _GNU_SOURCE
#include <sys/mman.h>
#include <stdio.h>
#include <stdlib.h>
#include <setjmp.h>
#include <math.h>
#define LL_ATON_PLATFORM LL_ATON_PLAT_STM32N6
#define LL_ATON_OSAL LL_ATON_OSAL_BARE_METAL
#include "COMPAT"
#include "PORTABLE"
#include "FIRST"
#include "SCHEDULE"
#define ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(x) (x)
DESCRIPTORS
static jmp_buf jump;
static int expected, failures;
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line%d: %s\n",__LINE__,#x);exit(91);}}while(0)
_Noreturn void s6_compat_fail(void){CHECK(expected);failures++;longjmp(jump,1);}
void __real_ll_sw_forward_dequantizelinear(void *p){(void)p;CHECK(0);}
void __real_ll_sw_forward_quantizelinear(void *p){(void)p;CHECK(0);}
static void quant(void){CHECK(__wrap_LL_ATON_LIB_Cast(Cast_inserted_id109_tensor_info_in_6,Cast_inserted_id109_tensor_info_out_6,2,3)==0);}
#define REJECT(call) do { \
    unsigned char snapshot[0x4000];memcpy(snapshot,(void *)0x34240000,sizeof snapshot); \
    int previous=failures;expected=1; \
    if(!setjmp(jump)){call;CHECK(0);}expected=0; \
    CHECK(failures==previous+1);CHECK(!memcmp(snapshot,(void *)0x34240000,sizeof snapshot)); \
}while(0)
int main(int argc,char **argv){
    CHECK(argc==5);
    void *p=mmap((void *)0x34200000,0x44000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    CHECK(p==(void *)0x34200000);
    FILE *f=fopen(argv[1],"rb");CHECK(f);CHECK(fread(p,1,145457,f)==145457 && fgetc(f)==EOF);fclose(f);
    int scenario=atoi(argv[2]);
    if(scenario==0){
        FILE *in=fopen(argv[3],"rb"),*out=fopen(argv[4],"wb");CHECK(in && out);
        for(unsigned row=0;row<1024;row++){
            unsigned char snapshot[0x4000];memset((void *)0x34240000,0xa5,0x4000);
            CHECK(fread((void *)0x34240000,4,41,in)==41);memcpy(snapshot,(void *)0x34240000,sizeof snapshot);
            __wrap_ll_sw_forward_conv(&conv3_sw_info);quant();
            CHECK(!memcmp(snapshot,(void *)0x34240000,1024));
            CHECK(!memcmp(snapshot+2048,(void *)0x34240800,0x4000-2048));
            CHECK(fwrite((void *)0x34240400,1,256,out)==256);
        }
        CHECK(fgetc(in)==EOF);CHECK(!fclose(in) && !fclose(out));
    }else if(scenario==1){
        Conv_sw_info saved=conv3_sw_info;
        Tensor_info *t[]={&conv3_sw_info.general.input,&conv3_sw_info.general.output,&conv3_sw_info.weights,
                         &conv3_sw_info.bias,&conv3_sw_info.scratch,&conv3_sw_info.weights_permuted};
        for(unsigned j=0;j<6;j++){
            uint32_t *fields[]={&t[j]->dim.tensor_b,&t[j]->dim.tensor_h,&t[j]->dim.tensor_w,&t[j]->dim.tensor_c,
                &t[j]->dim.num_elem,&t[j]->stride.b,&t[j]->stride.h,&t[j]->stride.w,&t[j]->stride.c};
            for(unsigned k=0;k<9;k++){(*fields[k])++;REJECT(__wrap_ll_sw_forward_conv(&conv3_sw_info));conv3_sw_info=saved;}
            t[j]->mem.start_offset=(unsigned char *)((uintptr_t)t[j]->mem.start_offset+1);
            REJECT(__wrap_ll_sw_forward_conv(&conv3_sw_info));conv3_sw_info=saved;
            t[j]->format.is_signed=!t[j]->format.is_signed;
            REJECT(__wrap_ll_sw_forward_conv(&conv3_sw_info));conv3_sw_info=saved;
        }
        REJECT(__wrap_ll_sw_forward_conv(NULL));
        conv3_sw_info.ngroup++;REJECT(__wrap_ll_sw_forward_conv(&conv3_sw_info));conv3_sw_info=saved;
        for(unsigned k=0;k<4;k++){
            conv3_sw_info.pads[k]++;REJECT(__wrap_ll_sw_forward_conv(&conv3_sw_info));conv3_sw_info=saved;
            conv3_sw_info.strides[k]++;REJECT(__wrap_ll_sw_forward_conv(&conv3_sw_info));conv3_sw_info=saved;
        }
        for(unsigned k=0;k<2;k++){conv3_sw_info.dilations[k]++;REJECT(__wrap_ll_sw_forward_conv(&conv3_sw_info));conv3_sw_info=saved;}
        conv3_sw_info.general.type=LL_SW_QUANTIZELINEAR;REJECT(__wrap_ll_sw_forward_conv(&conv3_sw_info));
    }else if(scenario==2){
        LL_Buffer_InfoTypeDef in=Cast_inserted_id109_tensor_info_in_6[0],out=Cast_inserted_id109_tensor_info_out_6[0];
        REJECT(__wrap_LL_ATON_LIB_Cast(NULL,&out,2,3));REJECT(__wrap_LL_ATON_LIB_Cast(&in,NULL,2,3));
        REJECT(__wrap_LL_ATON_LIB_Cast(&in,&out,3,3));REJECT(__wrap_LL_ATON_LIB_Cast(&in,&out,2,2));
        for(unsigned j=0;j<2;j++){
            LL_Buffer_InfoTypeDef *t=j?&out:&in,saved=*t;
#define BAD(field,value) do{t->field=value;REJECT(__wrap_LL_ATON_LIB_Cast(&in,&out,2,3));*t=saved;}while(0)
            BAD(addr_base.i,0);BAD(offset_start,1025);BAD(offset_end,0);BAD(offset_limit,0);
            BAD(is_user_allocated,1);BAD(is_param,1);BAD(epoch,0);BAD(batch,0);BAD(chpos,CHPos_Last);
            BAD(type,DataType_BOOL);BAD(Qm,20);BAD(Qn,20);BAD(Qunsigned,!t->Qunsigned);
            BAD(nbits,8);BAD(ndims,0);BAD(mem_ndims,0);BAD(per_channel,1);
            BAD(scale,(void *)1);BAD(offset,(void *)1);BAD(shape,NULL);BAD(mem_shape,NULL);
            uint32_t badshape[4];
            for(unsigned k=0;k<4;k++){
                memcpy(badshape,saved.shape,sizeof badshape);badshape[k]++;BAD(shape,badshape);
                memcpy(badshape,saved.mem_shape,sizeof badshape);badshape[k]++;BAD(mem_shape,badshape);
            }
#undef BAD
        }
    }else if(scenario==3){
        float values[]={NAN,INFINITY,-INFINITY};
        for(unsigned i=0;i<3;i++){
            for(unsigned k=0;k<41;k++){
                memset((void *)0x34240000,0,164);memcpy((void *)(uintptr_t)(0x34240000+4*k),&values[i],4);
                REJECT(__wrap_ll_sw_forward_conv(&conv3_sw_info));
            }
            for(unsigned k=0;k<256;k++){
                memset((void *)0x34240400,0,1024);memcpy((void *)(uintptr_t)(0x34240400+4*k),&values[i],4);REJECT(quant());
            }
        }
    }else if(scenario==4){
        EpochBlock_ItemTypeDef out[40],original[41],snapshot[41];
        memcpy(original,ll_atonn_rt_epoch_block_array,sizeof original);memcpy(snapshot,original,sizeof original);
#define ADAPT() first_float_schedule(original,out,LL_ATON_End_EpochBlock_6,LL_ATON_Start_EpochBlock_7,LL_ATON_End_EpochBlock_7)
        CHECK(ADAPT()==out);CHECK(!memcmp(snapshot,original,sizeof original));
        unsigned hw=0,sw=0;
        for(unsigned i=0,j=0;i<41;i++)if(i!=5){
            EpochBlock_ItemTypeDef wanted=original[i];if(i==4)wanted.flags=EpochBlock_Flags_epoch_start|EpochBlock_Flags_epoch_end|EpochBlock_Flags_pure_sw;
            CHECK(!memcmp(&wanted,&out[j++],sizeof wanted));hw+=!!(wanted.flags&EpochBlock_Flags_pure_hw);sw+=!!(wanted.flags&EpochBlock_Flags_pure_sw);
        }
        CHECK(hw==7 && sw==32);
        original[40].flags=0;REJECT((void)ADAPT());memcpy(original,snapshot,sizeof original);
        original[5].wait_mask=0;REJECT((void)ADAPT());memcpy(original,snapshot,sizeof original);
        original[4].flags=0;REJECT((void)ADAPT());memcpy(original,snapshot,sizeof original);
        original[5].end_epoch_block=LL_ATON_End_EpochBlock_6;REJECT((void)ADAPT());memcpy(original,snapshot,sizeof original);
        original[4].end_epoch_block=LL_ATON_End_EpochBlock_7;REJECT((void)ADAPT());memcpy(original,snapshot,sizeof original);
        for(unsigned i=0;i<40;i++){
            original[i].flags|=EpochBlock_Flags_last_eb;REJECT((void)ADAPT());memcpy(original,snapshot,sizeof original);
            original[i].flags^=EpochBlock_Flags_pure_hw;REJECT((void)ADAPT());memcpy(original,snapshot,sizeof original);
        }
    }else CHECK(0);
    CHECK(!munmap(p,0x44000));return 0;
}
'''

@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    source=generated()
    conv=re.findall(r'Conv_sw_info conv3_sw_info = \{.*?\n  \};',source,re.S)
    cast=re.findall(r'  static const (?:uint32_t|LL_Buffer_InfoTypeDef) Cast_inserted_id109.*?;',source,re.S)
    schedule=re.findall(r'  static const EpochBlock_ItemTypeDef ll_atonn_rt_epoch_block_array\[\] = \{.*?\n  \};',source,re.S)
    assert len(conv)==1 and len(cast)==6 and len(schedule)==1
    names=sorted(set(re.findall(r'LL_ATON_(?:Start|End)_EpochBlock_\d+',schedule[0])))
    definitions='\n'.join('static void '+n+'(const void *p){(void)p;}' for n in names)
    definitions+='\n'+conv[0]+'\n'+'\n'.join(cast)+'\n'+schedule[0]
    text=HARNESS.replace('COMPAT',str(HERE.parent/'firmware_sram_qcompat/compat.c')).replace('PORTABLE',str(ROOT/'tools/board_deployment/portable_qdq/portable_qdq.c')).replace('FIRST',str(HERE/'first_float.c')).replace('SCHEDULE',str(HERE/'schedule.c')).replace('DESCRIPTORS',definitions)
    temp=tmp_path_factory.mktemp('firstfloat');path=temp/'test.c';path.write_text(text)
    p=subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-clobbered','-ffp-contract=off','-fno-fast-math','-fexcess-precision=standard','-I'+str(ST),str(path),'-lm','-o',str(temp/'test')],capture_output=True,text=True,timeout=30)
    assert p.returncode==0,p.stderr
    return temp/'test'

@pytest.mark.parametrize('scenario',range(1,5))
def test_actual_contracts_and_schedule(binary,scenario):
    p=subprocess.run([str(binary),str(GEN/'nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw'),str(scenario),'/dev/null','/dev/null'],capture_output=True,text=True,timeout=10)
    assert p.returncode==0,p.stderr

def test_all_original_1024_first_layer_quantized_values(binary,tmp_path):
    import onnx
    import onnxruntime as ort
    raw=pinned(EXPORT/'model_qdq_int8.onnx','22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d')
    pinned(EXPORT/'validation_vectors.npz','cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb')
    weights=pinned(GEN/'nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw','cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec')
    m=onnx.shape_inference.infer_shapes(onnx.load_from_string(raw))
    arrays={v.name:onnx.numpy_helper.to_array(v) for v in m.graph.initializer}
    gemm=next(n for n in m.graph.node if n.op_type=='Gemm')
    producers={v:n for n in m.graph.node for v in n.output}
    bias=producers[gemm.input[2]];w=producers[gemm.input[1]]
    assert bias.op_type==w.op_type=='DequantizeLinear'
    bias_value=(arrays[bias.input[0]].astype('f4')-arrays[bias.input[2]].astype('f4'))*arrays[bias.input[1]]
    header=(HERE/'first_bias.h').read_text()
    words=re.findall(r'UINT32_C\(0x([0-9a-f]{8})\)',header.split('first_bias_bits')[1].split('};')[0])
    np.testing.assert_array_equal(np.array([int(v,16) for v in words],dtype='u4'),bias_value.view('u4'))
    scale=arrays[w.input[1]][:,None];zero=arrays[w.input[2]][:,None]
    w_value=(arrays[w.input[0]].astype('f4')-zero.astype('f4'))*scale
    np.testing.assert_array_equal(np.frombuffer(weights,dtype='<f4',count=10496,offset=65568).reshape(256,41).view('u4'),w_value.view('u4'))
    quant=next(n for n in m.graph.node if n.op_type=='QuantizeLinear' and n.input[0]==gemm.output[0])
    assert arrays[quant.input[1]].view('u4')==0x3e286b17 and arrays[quant.input[2]]==18
    wanted=[gemm.input[0],quant.output[0]]
    vi={v.name:v for v in list(m.graph.value_info)+list(m.graph.output)}
    for name in wanted:m.graph.output.append(vi[name])
    options=ort.SessionOptions();options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    options.intra_op_num_threads=1;options.inter_op_num_threads=1
    s=ort.InferenceSession(m.SerializeToString(),options,providers=['CPUExecutionProvider'])
    vectors=np.load(EXPORT/'validation_vectors.npz',allow_pickle=False)
    inputs=[];expected=[];final=[]
    for row in vectors['x']:
        result=s.run(None,{s.get_inputs()[0].name:row[None,:]})
        final.append(result[0]);inputs.append(result[-2]);expected.append(result[-1])
    np.testing.assert_array_equal(np.concatenate(final).view('u4'),vectors['reference_logits'].view('u4'))
    feed=tmp_path/'input.bin';output=tmp_path/'output.bin';np.concatenate(inputs).astype('<f4').tofile(feed)
    p=subprocess.run([str(binary),str(GEN/'nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw'),'0',str(feed),str(output)],capture_output=True,text=True,timeout=15)
    assert p.returncode==0,p.stderr
    actual=np.fromfile(output,dtype='i1').reshape(1024,256)
    np.testing.assert_array_equal(actual,np.concatenate(expected))

@pytest.fixture(scope='module')
def main_binary(tmp_path_factory):
    spec=importlib.util.spec_from_file_location('sm04_runtime_controls',HERE.parent/'firmware_sram_runtime/test_runtime.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    temp=tmp_path_factory.mktemp('sm04_main')
    (temp/'stm32n6xx.h').write_text('#pragma once\n'+module.fixtures.CMSIS)
    (temp/'stai_nsl_qcfs_seed0.h').write_text('#pragma once\n'+module.fixtures.STAI+
        '\n#define STAI_ERROR_NETWORK_INVALID_CONTEXT_HANDLE 0x30000\nint stai_runtime_init(void);\n')
    source=module.HARNESS.replace('MAIN_PATH',str(HERE/'main.c')).replace('0x534d3032','0x534d3034')
    source+='\nvoid __real_ll_sw_forward_quantizelinear(void *v){(void)v;abort();}\nvoid __real_ll_sw_forward_dequantizelinear(void *v){(void)v;abort();}\n'
    (temp/'test.c').write_text(source)
    p=subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-DLL_ATON_PLATFORM=LL_ATON_PLAT_STM32N6','-DLL_ATON_OSAL=LL_ATON_OSAL_BARE_METAL',
        '-ffp-contract=off','-fno-fast-math','-fexcess-precision=standard',
        '-I'+str(ST),'-I'+str(temp),str(temp/'test.c'),'-lm','-o',str(temp/'test')],capture_output=True,text=True,timeout=30)
    assert p.returncode==0,p.stderr
    return temp/'test'

@pytest.mark.parametrize('scenario',range(7))
def test_actual_sm04_main_old_loop_runtime_receipts(main_binary,scenario):
    p=subprocess.run([str(main_binary),str(scenario)],capture_output=True,text=True,timeout=3)
    assert p.returncode==0,p.stderr

def test_builder_identity_and_weight_report():
    import json
    spec=importlib.util.spec_from_file_location('sm04_builder_controls',HERE/'build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    b=module.engine()
    value={'kind':'n6_sram_offline_firmware_build','weights_path':'unrelated'}
    assert json.loads(b.encoded(value))['weights_path']==str(GEN/'nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw')
    assert value['weights_path']==str(GEN/'nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw')
    assert b.GEN==HERE/'generate' and b.INCLUDES[1]==GEN
    for flag in ['-ffp-contract=off','-fno-fast-math','-fexcess-precision=standard','-Wl,--wrap=ll_sw_forward_conv','-Wl,--wrap=LL_ATON_LIB_Cast']:
        assert flag in b.FLAGS
    with pytest.raises(RuntimeError):b.run(HERE.parent/'firmware_sram_qcompat/build_actual_01')
