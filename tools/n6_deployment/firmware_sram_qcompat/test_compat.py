"""Compile actual adapter against installed metadata headers and generated sites.

Vendor calls are explicit host substitutes; these tests do not run ARM kernels.
"""
from pathlib import Path
import hashlib
import importlib.util
import re
import subprocess
import pytest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
GEN=ROOT/'results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate'
ST=Path('/home/thc1006/opt/stedgeai/3.0/Middlewares/ST/AI/Npu/ll_aton')
HARNESS=r'''
#define _GNU_SOURCE
#include <sys/mman.h>
#include <stdio.h>
#include <stdlib.h>
#include <setjmp.h>
#include <math.h>
#include "COMPAT_PATH"
#define ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(x) (x)
GENERATED_DESCRIPTORS
static jmp_buf jump;
static int expect_failure, calls, failures;
static General *current;
static unsigned current_quant;
#define CHECK(x) do { if(!(x)){fprintf(stderr,"line%d: %s\n",__LINE__,#x);exit(91);} } while(0)
_Noreturn void s6_compat_fail(void) {
    CHECK(expect_failure);failures++;longjmp(jump,1);
}
void __real_ll_sw_forward_dequantizelinear(void *v) {
    Dequantizelinear_sw_info p=*(Dequantizelinear_sw_info *)v;
    Dequantizelinear_sw_info *before=(void *)current;
    CHECK(!current_quant && p.is.format.is_signed==p.izp.format.is_signed);
    p.is.format.is_signed=before->is.format.is_signed;
    CHECK(memcmp(&p,before,sizeof p)==0);calls++;
}
void __real_ll_sw_forward_quantizelinear(void *v) {
    Quantizelinear_sw_info p=*(Quantizelinear_sw_info *)v;
    Quantizelinear_sw_info *before=(void *)current;
    CHECK(current_quant && p.os.format.is_signed==p.ozp.format.is_signed);
    p.os.format.is_signed=before->os.format.is_signed;
    CHECK(memcmp(&p,before,sizeof p)==0);calls++;
}
static void invoke(void *p,unsigned q) {
    current=p;current_quant=q;
    if(q)__wrap_ll_sw_forward_quantizelinear(p);
    else __wrap_ll_sw_forward_dequantizelinear(p);
}
static void reject(General *g,unsigned q) {
    unsigned char snapshot[0x4000];memcpy(snapshot,(void *)0x34240000,sizeof snapshot);
    int prior=calls,prev=failures;expect_failure=1;
    if(!setjmp(jump)){invoke(g,q);CHECK(0);}
    expect_failure=0;
    CHECK(calls==prior && failures==prev+1);
    CHECK(memcmp(snapshot,(void *)0x34240000,sizeof snapshot)==0);
}
int main(int argc,char **argv) {
    CHECK(argc==3);
    void *p=mmap((void *)0x34200000,0x44000,PROT_READ|PROT_WRITE,
                MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    CHECK(p==(void *)0x34200000);
    FILE *f=fopen(argv[1],"rb");CHECK(f);
    CHECK(fread(p,1,145457,f)==145457 && fgetc(f)==EOF);fclose(f);
    int scenario=atoi(argv[2]);
    if(scenario==0){
        for(unsigned k=0;k<9;k++) {
            unsigned char copy[sizeof(Quantizelinear_sw_info)];memcpy(copy,sites[k],sizeof copy);
            int prior=calls;invoke(sites[k],kinds[k]);
            CHECK(calls-prior==(k==1?0:1));CHECK(memcmp(copy,sites[k],sizeof copy)==0);
        }
    } else if(scenario==1) {
        for(int base=-32768;base<=32767;base+=41) {
            int16_t q[41];for(unsigned i=0;i<41;i++)q[i]=(int16_t)(base+(int)i>32767?32767:base+(int)i);
            memcpy((void *)0x342400b0,q,sizeof q);invoke(sites[1],0);
            float *a=(void *)0x34240000,scale;memcpy(&scale,(void *)0x34223700,4);
            for(unsigned i=0;i<41;i++) {
                float wanted=(float)((double)q[i]*(double)scale);
                CHECK(memcmp(&a[i],&wanted,4)==0);
            }
        }
        CHECK(calls==0);
    } else if(scenario==2) {
        for(unsigned k=0;k<9;k++) {
            Quantizelinear_sw_info saved;memcpy(&saved,sites[k],sizeof saved);
            General *g=sites[k];
            g->type=LL_SW_CONV;reject(g,kinds[k]);memcpy(g,&saved,sizeof saved);
            Tensor_info *t[]={&g->input,&g->output,&((Quantizelinear_sw_info *)g)->os,&((Quantizelinear_sw_info *)g)->ozp};
            for(unsigned j=0;j<4;j++) {
                uint32_t *fields[]={&t[j]->dim.tensor_b,&t[j]->dim.tensor_h,&t[j]->dim.tensor_w,&t[j]->dim.tensor_c,
                    &t[j]->dim.num_elem,&t[j]->stride.b,&t[j]->stride.h,&t[j]->stride.w,&t[j]->stride.c};
                for(unsigned h=0;h<9;h++) {(*fields[h])++;reject(g,kinds[k]);memcpy(g,&saved,sizeof saved);}
                t[j]->format.is_signed=!t[j]->format.is_signed;reject(g,kinds[k]);memcpy(g,&saved,sizeof saved);
                t[j]->mem.start_offset++;reject(g,kinds[k]);memcpy(g,&saved,sizeof saved);
            }
        }
        CHECK(failures==9*45);
    } else if(scenario==3) {
        for(unsigned k=0;k<9;k++) {
            Quantizelinear_sw_info *p=sites[k];
            unsigned char *ptrs[]={p->os.mem.start_offset,p->ozp.mem.start_offset};
            for(unsigned j=0;j<2;j++){*ptrs[j]^=1;reject((General *)p,kinds[k]);*ptrs[j]^=1;}
        }
    } else if(scenario==4) {reject(0,0);reject(0,1);}
    else CHECK(0);
    CHECK(munmap(p,0x44000)==0);return 0;
}
'''


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    source=GEN/'nsl_qcfs_seed0.c'
    assert hashlib.sha256(source.read_bytes()).hexdigest()=='8b7a8703240811f4b4f12517f33ce5c77bc004911c088514435340bc92c3b43e'
    assert hashlib.sha256((GEN/'nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw').read_bytes()).hexdigest()=='cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec'
    matches=list(re.finditer(r'(Quantizelinear|Dequantizelinear)_sw_info (\w+) = \{(.*?)\n  \};',source.read_text(),re.S))
    assert len(matches)==9
    definitions='\n'.join('static '+m.group(0) for m in matches)
    definitions+='\nstatic void *sites[]={'+','.join('&'+m.group(2) for m in matches)+'};'
    definitions+='\nstatic unsigned kinds[]={'+','.join(str(int(m.group(1)=='Quantizelinear')) for m in matches)+'};'
    temp=tmp_path_factory.mktemp('qcfs_compat');c=temp/'test.c';out=temp/'test'
    c.write_text(HARNESS.replace('COMPAT_PATH',str(HERE/'compat.c')).replace('GENERATED_DESCRIPTORS',definitions))
    result=subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffp-contract=off',
        '-fno-fast-math','-I'+str(ST),str(c),'-o',str(out)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    return out


@pytest.mark.parametrize('scenario',range(5))
def test_actual_adapter_fixed_descriptors_full_int16_domain_and_rejection(binary,scenario):
    result=subprocess.run([str(binary),str(GEN/'nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw'),str(scenario)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_builder_fixed_input_no_legacy_output():
    spec=importlib.util.spec_from_file_location('qcompat_build',HERE/'build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    b=module.engine()
    assert b.HERE==HERE and b.INCLUDES[0]==HERE
    assert '-Wl,--wrap=ll_sw_forward_quantizelinear' in b.FLAGS
    with pytest.raises(RuntimeError):b.run(HERE.parent/'firmware_sram_runtime/build_actual_01')


@pytest.fixture(scope='module')
def main_binary(tmp_path_factory):
    spec=importlib.util.spec_from_file_location('sm03_runtime_controls',HERE.parent/'firmware_sram_runtime/test_runtime.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    temp=tmp_path_factory.mktemp('sm03_main')
    (temp/'stm32n6xx.h').write_text('#pragma once\n'+module.fixtures.CMSIS)
    (temp/'stai_nsl_qcfs_seed0.h').write_text('#pragma once\n'+module.fixtures.STAI+
        '\n#define STAI_ERROR_NETWORK_INVALID_CONTEXT_HANDLE 0x30000\nint stai_runtime_init(void);\n')
    source=module.HARNESS.replace('MAIN_PATH',str(HERE/'main.c')).replace('0x534d3032','0x534d3033')
    source+='\nvoid __real_ll_sw_forward_quantizelinear(void *v){(void)v;abort();}\nvoid __real_ll_sw_forward_dequantizelinear(void *v){(void)v;abort();}\n'
    (temp/'test.c').write_text(source)
    result=subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(ST),'-I'+str(temp),
        str(temp/'test.c'),'-o',str(temp/'test')],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    return temp/'test'


@pytest.mark.parametrize('scenario',range(7))
def test_actual_sm03_main_keeps_runtime_order_errors_and_old_loop(main_binary,scenario):
    p=subprocess.run([str(main_binary),str(scenario)],capture_output=True,text=True,timeout=3)
    assert p.returncode==0,p.stderr
