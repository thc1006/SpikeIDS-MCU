"""Bounded host-C main wiring controls. No ARM build, USB, MMIO or model.

Actual main.c/mailbox.h are compiled unchanged by host GCC. CMSIS, STAI and
the already reviewed callback helper are explicit opaque providers. memcpy
maps the literal activation address to a local byte array, never target RAM.
Barriers are observation hooks, not a model of ARM memory ordering.
"""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
INPUTS = ("main.c", "mailbox.h", "startup.c", "syscalls.c", "linker.ld", "ABI.json", "build.py", "README.md")

CMSIS = r'''
#include <stdint.h>
typedef struct { uint32_t CPUID, CCR, CPACR; } fake_scb_t;
typedef struct { uint32_t CYCCNT, CTRL; } fake_dwt_t;
typedef struct { uint32_t DEMCR; } fake_debug_t;
extern fake_scb_t fake_scb;
extern fake_dwt_t fake_dwt;
extern fake_debug_t fake_debug;
#define SCB (&fake_scb)
#define DWT (&fake_dwt)
#define CoreDebug (&fake_debug)
#define SCB_CCR_DC_Msk (1u<<16)
#define CoreDebug_DEMCR_TRCENA_Msk (1u<<24)
#define DWT_CTRL_CYCCNTENA_Msk 1u
void observe_barrier(int kind);
void observe_nop(void);
#define __DMB() observe_barrier(1)
#define __DSB() observe_barrier(2)
#define __ISB() observe_barrier(3)
#define __NOP() observe_nop()
'''

STAI = r'''
#include <stdint.h>
#define LL_ATON_RT_MODE 1
#define LL_ATON_RT_POLLING 1
#define STAI_NSL_QCFS_SEED0_IN_NUM 1
#define STAI_NSL_QCFS_SEED0_OUT_NUM 1
#define STAI_NSL_QCFS_SEED0_IN_1_SIZE_BYTES 164
#define STAI_NSL_QCFS_SEED0_OUT_1_SIZE_BYTES 20
#define STAI_NSL_QCFS_SEED0_IN_1_FORMAT 1
#define STAI_NSL_QCFS_SEED0_OUT_1_FORMAT 1
#define STAI_NSL_QCFS_SEED0_IN_1_ALIGNMENT 32
#define STAI_NSL_QCFS_SEED0_CONTEXT_SIZE 128
#define STAI_FORMAT_FLOAT32 1
#define STAI_SUCCESS 0
#define STAI_MODE_SYNC 9
typedef int stai_return_code;
typedef void stai_network;
typedef void *stai_ptr;
typedef unsigned stai_size;
typedef struct { unsigned size; const int *data; } fake_shape_t;
typedef struct { int format, size_bytes; fake_shape_t shape, scale, zeropoint; } stai_tensor;
typedef struct { unsigned n_inputs,n_outputs; const stai_tensor *inputs,*outputs; } stai_network_info;
stai_return_code stai_nsl_qcfs_seed0_init(stai_network *);
stai_return_code stai_nsl_qcfs_seed0_get_info(stai_network *, stai_network_info *);
stai_return_code stai_nsl_qcfs_seed0_get_inputs(stai_network *,stai_ptr *,stai_size *);
stai_return_code stai_nsl_qcfs_seed0_get_outputs(stai_network *,stai_ptr *,stai_size *);
stai_return_code stai_nsl_qcfs_seed0_run(stai_network *,int);
stai_return_code stai_nsl_qcfs_seed0_get_error(stai_network *);
'''

TRACE = r'''
typedef uint32_t (*npu_trace_counter_fn)(void *);
typedef struct {
 uint32_t magic,version,run_id,active,complete,error;
 uint32_t received,stored,matched,completed_epochs;
 uint32_t completed_pure_hw,completed_hybrid,completed_pure_sw,completed_lifecycle;
 uint32_t counter_present,counter_wrap_observed,runtime_return_code;
 uint32_t hardware_independently_proven,performance_accepted;
 uint32_t events[162][10];
} npu_trace_log_t;
typedef struct { unsigned opaque; } npu_trace_context_t;
int npu_trace_bind(stai_network *,npu_trace_context_t *,volatile npu_trace_log_t *,npu_trace_counter_fn,void *);
int npu_trace_begin(npu_trace_context_t *,uint32_t);
int npu_trace_finish(npu_trace_context_t *,int);
'''

HARNESS = r'''
#include <stdint.h>
#include <stddef.h>
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
fake_scb_t fake_scb={.CPUID=0x411fd220};
fake_dwt_t fake_dwt;
fake_debug_t fake_debug;
static jmp_buf leave;
static int scenario,steps[20],count,finished_rc=999,commit_barrier,loops;
static uint32_t io_words[41];
static const uint32_t expected_out[5]={0x3f800001,0xbf000002,0x00000001,0x80000000,0x40000005};
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(90); } } while(0)
static uint32_t input_word(unsigned i) { return 0x3e800000u+i; }
static void event(int n) { CHECK(count<20);steps[count++]=n; }
static void *mapped_copy(void *dst,const void *src,size_t n) {
 if ((uintptr_t)dst==0x34240000u) dst=io_words;
 if ((uintptr_t)src==0x34240000u) src=io_words;
 return memcpy(dst,src,n);
}
void observe_barrier(int kind) {
 if (kind==1 && g_mailbox.state==S6_DONE) {
  CHECK(g_mailbox.response_sequence==0 && g_mailbox.output_count==5);
  CHECK(g_mailbox.trace_run_id==1 && g_mailbox.trace_complete==1 && g_mailbox.trace_error==0);
  for (unsigned i=0;i<5;i++) CHECK(g_mailbox.output_words[i]==expected_out[i]);
  commit_barrier++;
 }
 if (kind==2 && g_mailbox.state==S6_DONE && g_mailbox.response_sequence==1) longjmp(leave,1);
}
void observe_nop(void) {
 CHECK(++loops<10);
 if (g_mailbox.state==S6_ERROR) longjmp(leave,1);
 if (g_mailbox.state==S6_WAIT_PLATFORM) { CHECK(g_mailbox.magic==0x54364e36);g_mailbox.platform_ack=S6_PLATFORM_ACK;return; }
 if (g_mailbox.state==S6_READY) {
  CHECK(g_mailbox.request_sequence==0);
  g_mailbox.row_id=947;g_mailbox.input_count=41;g_mailbox.command=1;
  for (unsigned i=0;i<41;i++) g_mailbox.input_words[i]=input_word(i);
  if (scenario==11) g_mailbox.input_words[40]=0x7f800000;
  g_mailbox.request_sequence=1;return;
 }
 CHECK(0);
}
int stai_nsl_qcfs_seed0_init(stai_network *n) { CHECK(n);event(1);return scenario==1?-23:0; }
int npu_trace_bind(stai_network *n,npu_trace_context_t *c,volatile npu_trace_log_t *log,npu_trace_counter_fn f,void *cookie) {
 CHECK(n && c && log==&g_npu_trace && f && count==1 && steps[0]==1);event(2);
 CHECK(log->run_id==0 && log->complete==0);CHECK(f(cookie)==0);
 if (scenario==2) { log->error=10;return -17; } return 0;
}
int stai_nsl_qcfs_seed0_get_info(stai_network *n,stai_network_info *i) {
 static const int ishape[2]={1,41},oshape[2]={1,5};
 static const stai_tensor in={1,164,{2,ishape},{0,0},{0,0}},out={1,20,{2,oshape},{0,0},{0,0}};
 (void)n;event(3);*i=(stai_network_info){1,1,&in,&out};return 0;
}
int stai_nsl_qcfs_seed0_get_inputs(stai_network *n,stai_ptr *p,stai_size *s) { (void)n;event(4);*p=(void *)(uintptr_t)0x34240000;*s=1;return 0; }
int stai_nsl_qcfs_seed0_get_outputs(stai_network *n,stai_ptr *p,stai_size *s) { (void)n;event(5);*p=(void *)(uintptr_t)0x34240000;*s=1;return 0; }
int npu_trace_begin(npu_trace_context_t *c,uint32_t runid) {
 (void)c;event(6);CHECK(runid==1);
 for (unsigned i=0;i<41;i++) CHECK(io_words[i]==input_word(i));
 if (scenario==3) return 3;
 g_npu_trace.run_id=runid;g_npu_trace.active=1;return 0;
}
int stai_nsl_qcfs_seed0_run(stai_network *n,int mode) {
 (void)n;event(7);CHECK(mode==9 && g_npu_trace.active==1);
 for(unsigned i=0;i<5;i++) io_words[i]=expected_out[i];
 if(scenario==9) io_words[4]=0x7f800000;
 if(scenario==10) g_mailbox.input_words[40]^=1;
 return scenario==4?-37:0;
}
int npu_trace_finish(npu_trace_context_t *c,int rc) {
 (void)c;event(8);CHECK(steps[count-2]==7);finished_rc=rc;
 g_npu_trace.runtime_return_code=(uint32_t)rc;g_npu_trace.active=0;
 g_npu_trace.complete=rc==0;g_npu_trace.error=rc?9:0;
 if(scenario==6) {g_npu_trace.complete=0;g_npu_trace.error=8;return 8;}
 if(scenario==7) g_npu_trace.complete=0;
 if(scenario==8) g_npu_trace.error=9;
 return rc?9:0;
}
int stai_nsl_qcfs_seed0_get_error(stai_network *n) { (void)n;event(9);CHECK(finished_rc!=999);return scenario==5?-41:0; }
int main(int argc,char **argv) {
 CHECK(argc==2);scenario=atoi(argv[1]);CHECK(scenario>=0 && scenario<=11);
 if(!setjmp(leave)) firmware_entry();
 CHECK(g_mailbox.magic==0x54364e36 && g_mailbox.deployment_tag==0x54523031);
 CHECK(g_mailbox.trace_address==0x340f8200 && g_mailbox.trace_bytes==6556);
 CHECK(offsetof(s6_mailbox_t,trace_status)==496 && offsetof(s6_mailbox_t,trace_error)==508);
 if(scenario==0) {
  CHECK(g_mailbox.state==S6_DONE && g_mailbox.response_sequence==1);
  CHECK(g_mailbox.completed_row_id==947 && commit_barrier==1 && count==9);
 } else CHECK(g_mailbox.state==S6_ERROR && g_mailbox.response_sequence==0 && commit_barrier==0);
 if(scenario>=4 && scenario<=10) {
  CHECK(count==9 && finished_rc==(scenario==4?-37:0));
  CHECK(g_mailbox.api_status[4]==finished_rc && g_mailbox.api_status[5]==(scenario==5?-41:0));
  CHECK(g_mailbox.output_count==5 && g_mailbox.trace_run_id==1);
  for(unsigned i=0;i<5;i++) CHECK(g_mailbox.output_words[i]==((scenario==9 && i==4)?0x7f800000:expected_out[i]));
 } else if(scenario) {
  CHECK(finished_rc==999 && g_mailbox.output_count==0 && g_mailbox.trace_run_id==0);
  CHECK(count==(scenario==1?1:scenario==2?2:scenario==3?6:5));
 }
 if(scenario==1) CHECK(g_mailbox.api_status[0]==-23 && g_mailbox.trace_bind_status==INT32_MIN);
 if(scenario==2) CHECK(g_mailbox.trace_bind_status==-17 && g_mailbox.trace_error==10);
 if(scenario==3) CHECK(g_mailbox.trace_status==3 && g_mailbox.adapter_error==-8);
 if(scenario>=6 && scenario<=8) CHECK(g_mailbox.adapter_error==-8);
 if(scenario==9) CHECK(g_mailbox.adapter_error==-6);
 if(scenario==10) CHECK(g_mailbox.adapter_error==-4);
 puts("host-C main wiring passed; opaque providers, no target execution");return 0;
}
'''


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    before = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in INPUTS}
    temp = tmp_path_factory.mktemp("trace_main_host_c")
    for name, source in (("stm32n6xx.h", CMSIS), ("stai_nsl_qcfs_seed0.h", STAI), ("npu_trace.h", TRACE)):
        (temp / name).write_text(source)
    source = temp / "harness.c"
    source.write_text(HARNESS.replace("MAIN_PATH", str(HERE / "main.c")))
    executable = temp / "host_control"
    result = subprocess.run(["gcc", "-std=c11", "-O0", "-Wall", "-Wextra", "-Werror", "-I", str(temp), str(source), "-o", str(executable)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    yield executable
    assert before == {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in INPUTS}


@pytest.mark.parametrize("scenario", range(12), ids=("success", "init_failure", "bind_failure", "begin_failure", "run_failure", "get_error_failure", "finish_failure", "incomplete", "latched_trace_error", "fifth_output_nonfinite", "last_input_changed", "last_input_nonfinite"))
def test_actual_main_host_wiring(harness, scenario):
    result = subprocess.run([str(harness), str(scenario)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


def test_abi_memory_and_honest_retention_scope():
    abi = json.loads((HERE / "ABI.json").read_bytes())
    assert abi["trace_address"] + abi["trace_bytes"] == 0x340F9B9C
    regions = [(0x34064000, 0x340F0000), (0x340F0000, 0x340F8000), (abi["mailbox_address"], abi["trace_address"]), (abi["trace_address"], 0x340F9B9C), (0x34180400, 0x3418B000), (0x34200000, 0x34240000), (0x34240000, 0x34244000)]
    assert all(a[1] <= b[0] for a, b in zip(regions, regions[1:]))
    assert abi["trace_total_events"] == abi["trace_epoch_events"] + abi["trace_lifecycle_events"] == 162
    assert (abi["trace_pure_hw_epochs"], abi["trace_hybrid_epochs"], abi["trace_pure_sw_epochs"]) == (8, 1, 31)
    assert all(abi[k] is False for k in ("platform_initialized", "hardware_executed", "trace_independent_hardware_proof", "performance_accepted", "energy_accepted"))
    readme = (HERE / "README.md").read_text()
    assert "not an on-target ACK" in readme
    assert "hung runtime may leave a partial active log" in readme
    assert "not accepted logits" in readme
