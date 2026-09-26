"""Real C wrapper and original main, with explicit host-only CMSIS/STAI stubs."""
import importlib.util
from pathlib import Path
import subprocess
import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('s6_trace_host_fixtures', HERE.parent/'firmware_sram_trace/test_main_independent.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
static void *mapped_copy(void *,const void *,size_t);
#define memcpy mapped_copy
#define main firmware_entry
#include "MAIN_PATH"
#undef main
#undef memcpy
fake_scb_t fake_scb={.CPUID=0x411fd221};
fake_dwt_t fake_dwt;
fake_debug_t fake_debug;
static jmp_buf done;
static int scenario, events[16], count, loops;
static uint32_t io[41];
#define CHECK(x) do {if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(90);}}while(0)
static void event(int id){CHECK(count<16);events[count++]=id;}
static void *mapped_copy(void *d,const void *s,size_t n){
 if((uintptr_t)d==0x34240000)d=io;
 if((uintptr_t)s==0x34240000)s=io;
 return memcpy(d,s,n);
}
void observe_barrier(int k){
 if(k==2 && g_mailbox.state==S6_DONE && g_mailbox.response_sequence==1) longjmp(done,1);
}
void observe_nop(void){
 CHECK(++loops<8);
 if(g_mailbox.state==S6_ERROR)longjmp(done,1);
 if(g_mailbox.state==S6_WAIT_PLATFORM){
  CHECK(count==0 && g_mailbox.input_padding[0]==0);
  if(scenario==3)longjmp(done,1);
  g_mailbox.platform_ack=S6_PLATFORM_ACK;return;
 }
 CHECK(g_mailbox.state==S6_READY && count==5);
 g_mailbox.row_id=20;g_mailbox.input_count=41;g_mailbox.command=1;
 for(unsigned i=0;i<41;i++)g_mailbox.input_words[i]=0x3f000000u+i;
 g_mailbox.request_sequence=1;
}
int stai_runtime_init(void){
 CHECK(count==0 && g_mailbox.platform_ack==S6_PLATFORM_ACK);
 CHECK(g_mailbox.state==S6_INITIALIZING && g_mailbox.stage==6);
 CHECK(g_mailbox.input_padding[0]==S6_RUNTIME_RECEIPT);
 CHECK(g_mailbox.input_padding[1]==0x80000000 && g_mailbox.input_padding[2]==1);
 event(1);return scenario==1?-17:0;
}
int stai_nsl_qcfs_seed0_init(stai_network *n){
 CHECK(n && count==1 && events[0]==1 && g_mailbox.stage==1);
 CHECK(g_mailbox.input_padding[1]==0);event(2);return scenario==2?-23:0;
}
int stai_nsl_qcfs_seed0_get_info(stai_network *n,stai_network_info *i){
 static const int ish[2]={1,41},osh[2]={1,5};
 static const stai_tensor in={1,164,{2,ish},{0,0},{0,0}},out={1,20,{2,osh},{0,0},{0,0}};
 (void)n;event(3);*i=(stai_network_info){1,1,&in,&out};return scenario==5?-31:0;
}
int stai_nsl_qcfs_seed0_get_inputs(stai_network *n,stai_ptr *p,stai_size *s){(void)n;event(4);*p=(void *)(uintptr_t)0x34240000;*s=1;return 0;}
int stai_nsl_qcfs_seed0_get_outputs(stai_network *n,stai_ptr *p,stai_size *s){(void)n;event(5);*p=(void *)(uintptr_t)0x34240000;*s=1;return 0;}
int stai_nsl_qcfs_seed0_run(stai_network *n,int mode){
 CHECK(n && mode==9 && count==5);event(6);
 for(unsigned i=0;i<41;i++)CHECK(io[i]==0x3f000000u+i);
 for(unsigned i=0;i<5;i++)io[i]=0x3f800000u+i;
 return 0;
}
int stai_nsl_qcfs_seed0_get_error(stai_network *n){(void)n;event(7);return 0;}
int main(int argc,char **argv){
 CHECK(argc==2);scenario=atoi(argv[1]);CHECK(scenario>=0 && scenario<=6);
 if(scenario==4)fake_scb.CCR=SCB_CCR_DC_Msk;
 if(!setjmp(done))firmware_entry();
 CHECK(g_mailbox.deployment_tag==0x534d3032 && sizeof(g_mailbox)==512);
 if(scenario==0 || scenario==6){
  CHECK(count==7 && g_mailbox.state==S6_DONE && g_mailbox.response_sequence==1);
  CHECK(g_mailbox.input_padding[0]==S6_RUNTIME_RECEIPT && g_mailbox.input_padding[1]==0 && g_mailbox.input_padding[2]==1);
  for(unsigned i=0;i<5;i++)CHECK(g_mailbox.output_words[i]==0x3f800000u+i);
  if(scenario==6){
   g_mailbox.state=S6_INITIALIZING;g_mailbox.stage=1;
   CHECK(initialize_runtime_then_model((stai_network *)context)==STAI_ERROR_NETWORK_INVALID_CONTEXT_HANDLE);
   CHECK(count==7 && g_mailbox.input_padding[2]==1);
  }
 }else if(scenario==3){CHECK(count==0 && g_mailbox.state==S6_WAIT_PLATFORM);}
 else{
  CHECK(g_mailbox.state==S6_ERROR && g_mailbox.response_sequence==0);
  CHECK(count==(scenario==1?1:scenario==2?2:scenario==4?0:3));
  if(scenario==1)CHECK(g_mailbox.stage==6 && g_mailbox.input_padding[1]==(uint32_t)-17 && g_mailbox.api_status[0]==-17);
  if(scenario==2)CHECK(g_mailbox.stage==1 && g_mailbox.input_padding[1]==0 && g_mailbox.api_status[0]==-23);
 }
 return 0;
}
'''


@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    temp = tmp_path_factory.mktemp('s6_runtime_host_control')
    (temp/'stm32n6xx.h').write_text('#pragma once\n'+fixtures.CMSIS)
    (temp/'stai_nsl_qcfs_seed0.h').write_text('#pragma once\n'+fixtures.STAI+
        '\n#define STAI_ERROR_NETWORK_INVALID_CONTEXT_HANDLE 0x30000\nint stai_runtime_init(void);\n')
    (temp/'test.c').write_text(HARNESS.replace('MAIN_PATH',str(HERE/'main.c')))
    out=temp/'test'
    result=subprocess.run(['gcc','-std=c11','-Wall','-Wextra','-Werror','-O2','-I',str(temp),str(temp/'test.c'),'-o',str(out)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    return out


@pytest.mark.parametrize('scenario',range(7))
def test_actual_main_runtime_order_and_errors(executable,scenario):
    result=subprocess.run([str(executable),str(scenario)],capture_output=True,text=True,timeout=3)
    assert result.returncode==0,result.stderr


def test_frozen_builder_and_new_directory():
    spec=importlib.util.spec_from_file_location('runtime_build',HERE/'build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    b=module.engine()
    assert b.HERE==HERE and b.INCLUDES[0]==HERE
    assert b.REPO==HERE.parents[2]
    with pytest.raises(RuntimeError): b.run(HERE.parent/'firmware_sram/build_actual_01')
