"""Actual new schedule/main, installed metadata and explicit host substitutes."""
from pathlib import Path
import importlib.util
import re
import subprocess
import pytest

HERE=Path(__file__).resolve().parent
ST=Path('/home/thc1006/opt/stedgeai/3.0/Middlewares/ST/AI/Npu/ll_aton')

def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

CONTROL=r'''
#include "SCHEDULE_PATH"
static void newstart0(const void *p){(void)p;}
static void newstart1(const void *p){(void)p;}
static void newstart2(const void *p){(void)p;}
static void newend0(const void *p){(void)p;}
static void newend1(const void *p){(void)p;}
static void newend2(const void *p){(void)p;}
static void post0(const void *p){(void)p;}
static void post1(const void *p){(void)p;}
static void post2(const void *p){(void)p;}
static void sm05_controls(void){
 EpochBlock_ItemTypeDef base[40],out[43],snapshot[40];
 const EpochBlock_FuncPtr_t os[]={LL_ATON_Start_EpochBlock_19,LL_ATON_Start_EpochBlock_31,LL_ATON_Start_EpochBlock_43};
 const EpochBlock_FuncPtr_t oe[]={LL_ATON_End_EpochBlock_19,LL_ATON_End_EpochBlock_31,LL_ATON_End_EpochBlock_43};
 EpochBlock_FuncPtr_t ns[]={newstart0,newstart1,newstart2},ne[]={newend0,newend1,newend2},post[]={post0,post1,post2};
 first_float_schedule(ll_atonn_rt_epoch_block_array,base,LL_ATON_End_EpochBlock_6,LL_ATON_Start_EpochBlock_7,LL_ATON_End_EpochBlock_7);
 memcpy(snapshot,base,sizeof snapshot);
#define ADAPT05() accum_schedule(base,out,os,oe,ns,ne,post)
 CHECK(ADAPT05()==out);CHECK(!memcmp(base,snapshot,sizeof base));
 unsigned at=0,matched=0,hw=0,sw=0;
 for(unsigned i=0;i<40;i++){
  EpochBlock_ItemTypeDef want=base[i];int selected=-1;
  for(unsigned j=0;j<3;j++)if(want.start_epoch_block==os[j])selected=(int)j;
  if(selected>=0){want.start_epoch_block=ns[selected];want.end_epoch_block=ne[selected];}
  CHECK(!memcmp(&want,&out[at++],sizeof want));
  if(selected>=0){
   CHECK(out[at].start_epoch_block==NULL && out[at].end_epoch_block==post[selected]);
   CHECK(out[at].flags==35 && out[at].wait_mask==0 && out[at].blob_address==0);at++;matched++;
  }
 }
 CHECK(at==43 && matched==3);
 for(unsigned i=0;i<42;i++){hw+=!!(out[i].flags&16);sw+=!!(out[i].flags&32);}
 CHECK(hw==7 && sw==35 && out[42].flags==8);
 for(unsigned i=0;i<39;i++){
  base[i].flags|=8;REJECT((void)ADAPT05());memcpy(base,snapshot,sizeof base);
  if(base[i].start_epoch_block==os[0] || base[i].start_epoch_block==os[1] || base[i].start_epoch_block==os[2]){
   base[i].wait_mask^=1;REJECT((void)ADAPT05());memcpy(base,snapshot,sizeof base);
   base[i].end_epoch_block=NULL;REJECT((void)ADAPT05());memcpy(base,snapshot,sizeof base);
   base[i].blob_address=1;REJECT((void)ADAPT05());memcpy(base,snapshot,sizeof base);
   base[i].start_epoch_block=newstart0;REJECT((void)ADAPT05());memcpy(base,snapshot,sizeof base);
  }
 }
 base[39].flags=0;REJECT((void)ADAPT05());memcpy(base,snapshot,sizeof base);
 for(unsigned j=0;j<3;j++){
  EpochBlock_FuncPtr_t saved=ns[j];ns[j]=NULL;REJECT((void)ADAPT05());ns[j]=saved;
  saved=ne[j];ne[j]=NULL;REJECT((void)ADAPT05());ne[j]=saved;
  saved=post[j];post[j]=NULL;REJECT((void)ADAPT05());post[j]=saved;
 }
}
'''

def test_actual_schedule_exact_insertions_and_negative_contracts(tmp_path):
    ff=module('sm05_first_fixtures',HERE.parent/'firmware_sram_firstfloat/test_firstfloat.py')
    source=ff.generated()
    conv=re.findall(r'Conv_sw_info conv3_sw_info = \{.*?\n  \};',source,re.S)
    cast=re.findall(r'  static const (?:uint32_t|LL_Buffer_InfoTypeDef) Cast_inserted_id109.*?;',source,re.S)
    schedule=re.findall(r'  static const EpochBlock_ItemTypeDef ll_atonn_rt_epoch_block_array\[\] = \{.*?\n  \};',source,re.S)
    assert len(conv)==1 and len(cast)==6 and len(schedule)==1
    names=sorted(set(re.findall(r'LL_ATON_(?:Start|End)_EpochBlock_\d+',schedule[0])))
    definitions='\n'.join('static void '+n+'(const void *p){(void)p;}' for n in names)
    definitions+='\n'+conv[0]+'\n'+'\n'.join(cast)+'\n'+schedule[0]
    text=ff.HARNESS.replace('COMPAT',str(HERE.parent/'firmware_sram_qcompat/compat.c')).replace('PORTABLE',str(ff.ROOT/'tools/board_deployment/portable_qdq/portable_qdq.c')).replace('FIRST',str(ff.HERE/'first_float.c')).replace('SCHEDULE',str(ff.HERE/'schedule.c')).replace('DESCRIPTORS',definitions)
    text=text.replace('int main(int argc',CONTROL.replace('SCHEDULE_PATH',str(HERE/'schedule.c'))+'\nint main(int argc')
    text=text.replace('int scenario=atoi(argv[2]);','sm05_controls();int scenario=atoi(argv[2]);')
    p=tmp_path/'schedule.c';p.write_text(text);exe=tmp_path/'schedule'
    r=subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-clobbered','-I'+str(ST),str(p),'-lm','-o',str(exe)],capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stderr
    r=subprocess.run([str(exe),str(ff.GEN/'nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw'),'4','/dev/null','/dev/null'],capture_output=True,text=True,timeout=5)
    assert r.returncode==0,r.stderr

@pytest.fixture(scope='module')
def main_executable(tmp_path_factory):
    m=module('sm05_runtime_fixtures',HERE.parent/'firmware_sram_runtime/test_runtime.py')
    p=tmp_path_factory.mktemp('sm05_main')
    (p/'stm32n6xx.h').write_text('#pragma once\n'+m.fixtures.CMSIS)
    (p/'stai_nsl_qcfs_seed0.h').write_text('#pragma once\n'+m.fixtures.STAI+'\n#define STAI_ERROR_NETWORK_INVALID_CONTEXT_HANDLE 0x30000\nint stai_runtime_init(void);\n')
    text=m.HARNESS.replace('MAIN_PATH',str(HERE/'main.c')).replace('0x534d3032','0x534d3035')
    text+='\nvoid __real_ll_sw_forward_quantizelinear(void *v){(void)v;abort();}\nvoid __real_ll_sw_forward_dequantizelinear(void *v){(void)v;abort();}\n'
    (p/'test.c').write_text(text)
    r=subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-DLL_ATON_PLATFORM=LL_ATON_PLAT_STM32N6','-DLL_ATON_OSAL=LL_ATON_OSAL_BARE_METAL','-I'+str(ST),'-I'+str(p),str(p/'test.c'),'-lm','-o',str(p/'test')],capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stderr
    return p/'test'

@pytest.mark.parametrize('scenario',range(7))
def test_actual_main_sm05_tag_and_old_runtime_protocol(main_executable,scenario):
    r=subprocess.run([str(main_executable),str(scenario)],capture_output=True,text=True,timeout=3)
    assert r.returncode==0,r.stderr
