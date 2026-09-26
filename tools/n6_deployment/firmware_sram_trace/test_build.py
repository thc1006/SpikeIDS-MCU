"""Finite synthetic ELF/source controls; no compiler, device or model execution."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sram_trace_build_author',HERE/'build.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

def elf():
    raw=bytearray(0x300)
    ident=b'\x7fELF\x01\x01\x01'+bytes(9)
    struct.pack_into('<16sHHIIIIIHHHHHH',raw,0,ident,2,40,1,0x34064041,52,0,0,52,32,5,40,0,0)
    for i,ph in enumerate([(1,0x200,0x34064000,0x34064000,0x80,0x80,5,4),
        (1,0x280,0x34064080,0x34064080,0x20,0x100,6,4),
        (1,0x2a0,0x340F0000,0x340F0000,0,0x8000,6,4),
        (1,0x2a0,0x340F8000,0x340F8000,0,512,6,4),
        (1,0x2a0,0x340F8200,0x340F8200,0,6556,6,4)]):
        struct.pack_into('<IIIIIIII',raw,52+i*32,*ph)
    struct.pack_into('<II',raw,0x200,0x340F8000,0x34064041)
    return raw

class BuildTests(unittest.TestCase):
    def test_positive_exact_five_segments(self):
        result=b.elf_layout(elf())
        self.assertEqual(len(result['segments']),5)
        self.assertEqual(result['segments'][-1]['address']+6556,0x340f9b9c)
        self.assertEqual(result['reserved_pools'],[[0x34200000,0x34240000],[0x34240000,0x34244000]])
    def test_trace_wrong_address_or_alias(self):
        for address in (0x340f8000,0x340f8204,0x340f0000,0x34200000,0x34240000):
            with self.subTest(address=address):
                raw=elf();struct.pack_into('<II',raw,52+4*32+8,address,address)
                with self.assertRaises(RuntimeError):b.elf_layout(raw)
    def test_trace_wrong_size_or_initialized_or_executable(self):
        for offset,value in ((16,1),(20,6555),(20,6557),(24,7),(24,4)):
            with self.subTest(offset=offset,value=value):
                raw=elf();struct.pack_into('<I',raw,52+4*32+offset,value)
                with self.assertRaises(RuntimeError):b.elf_layout(raw)
    def test_wrong_segment_count(self):
        raw=elf();struct.pack_into('<H',raw,44,4)
        with self.assertRaisesRegex(RuntimeError,'five|RX/data'):b.elf_layout(raw)
    def test_full_weight_and_activation_reservations(self):
        for address in (0x3423fff0,0x34243000):
            with self.subTest(address=address):
                raw=elf();struct.pack_into('<II',raw,52+32+8,address,address)
                with self.assertRaisesRegex(RuntimeError,'reserved SRAM'):b.elf_layout(raw)
    def test_wrong_vectors_machine_or_writable_code(self):
        for offset,fmt,value in ((18,'<H',62),(24,'<I',0x34064040),(0x200,'<I',0x3418b000),(52+24,'<I',7)):
            with self.subTest(offset=offset):
                raw=elf();struct.pack_into(fmt,raw,offset,value)
                with self.assertRaises(RuntimeError):b.elf_layout(raw)
    def test_mailbox_extent_exact(self):
        for offset,value in ((20,511),(20,544),(16,4)):
            with self.subTest(offset=offset,value=value):
                raw=elf();struct.pack_into('<I',raw,52+3*32+offset,value)
                with self.assertRaises(RuntimeError):b.elf_layout(raw)
    def test_stale_output_before_frozen_candidate_or_subprocess(self):
        with tempfile.TemporaryDirectory() as temp:
            parent=Path(temp);out=parent/'stale';out.mkdir()
            with (patch.object(b,'HERE',parent),patch.object(b,'frozen_pins',side_effect=AssertionError('frozen')),
                  patch.object(b,'candidate_pins',side_effect=AssertionError('candidate')),
                  patch.object(b.subprocess,'Popen',side_effect=AssertionError('compiler'))):
                with self.assertRaisesRegex(RuntimeError,'Existing output'):b.run(out)
    def test_no_cli_model_or_address_override(self):
        for flag in ('--model','--address','--runtime','--output'):
            with self.subTest(flag=flag),self.assertRaises(SystemExit) as error:
                b.main(['--output-dir','/tmp/no-build',flag,'x'])
            self.assertEqual(error.exception.code,2)
    def test_frozen_source_hashes_and_identical_bootstrap_copies(self):
        held=b.frozen_pins()
        self.assertEqual(len(held),12)
        self.assertEqual(b.FROZEN[b.TRACE/'npu_trace.c'],'c1125ead0369ef7666e06568f3f0c2ac9efb955eaa57369402aa7c038db6bcbf')
        for name in ('startup.c','syscalls.c'):
            self.assertEqual((HERE/name).read_bytes(),(b.ORIGINAL/name).read_bytes())
    def test_wrong_frozen_identity_rejected(self):
        with patch.object(b,'FROZEN',{HERE/'main.c':'0'*64}):
            with self.assertRaisesRegex(RuntimeError,'Frozen source'):b.frozen_pins()
    def test_same_byte_replacement_is_not_original_pin(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'tiny';p.write_bytes(b'fixed');held={};b.hold(held,p)
            q=Path(temp)/'replacement';q.write_bytes(b'fixed');q.replace(p)
            with self.assertRaisesRegex(RuntimeError,'no fresh adoption'):b.hold(held,p)
    def test_abi_prefix_preserved_and_tail_exact(self):
        old=json.loads((b.ORIGINAL/'ABI.json').read_bytes());a=json.loads((HERE/'ABI.json').read_bytes())
        for key,value in old.items():
            if key not in ('kind','magic','deployment_tag'):self.assertEqual(a[key],value,key)
        self.assertEqual((a['magic'],a['deployment_tag']),(0x54364e36,0x54523031))
        self.assertNotEqual(a['magic'],old['magic'])
        self.assertEqual(a['trace_tail_offsets'],dict(zip(('trace_address','trace_bytes','trace_run_id','trace_status','trace_bind_status','trace_complete','trace_error'),range(484,512,4))))
        self.assertEqual((a['trace_address'],a['trace_bytes']),(0x340f8200,6556))
        oldstruct=(b.ORIGINAL/'mailbox.h').read_text().split('typedef struct {',1)[1].split('uint8_t tail_padding',1)[0]
        newstruct=(HERE/'mailbox.h').read_text().split('typedef struct {',1)[1].split('uint8_t tail_padding',1)[0]
        self.assertEqual(oldstruct,newstruct)
    def test_counts_lifecycle_and_nonacceptance(self):
        a=json.loads((HERE/'ABI.json').read_bytes())
        self.assertEqual((a['trace_epoch_count'],a['trace_epoch_events'],a['trace_lifecycle_events'],a['trace_total_events']),(40,160,2,162))
        self.assertEqual((a['trace_pure_hw_epochs'],a['trace_hybrid_epochs'],a['trace_pure_sw_epochs']),(8,1,31))
        for key in ('trace_independent_hardware_proof','performance_accepted','energy_accepted','hardware_executed','platform_initialized'):
            self.assertIs(a[key],False)
    def test_bind_after_init_and_before_ready(self):
        s=(HERE/'main.c').read_text()
        self.assertLess(s.index('while (g_mailbox.platform_ack'),s.index('stai_nsl_qcfs_seed0_init('))
        self.assertLess(s.index('stai_nsl_qcfs_seed0_init('),s.index('npu_trace_bind('))
        self.assertLess(s.index('npu_trace_bind('),s.index('g_mailbox.state=S6_READY'))
        self.assertIn('if (g_mailbox.trace_bind_status!=STAI_SUCCESS) park_error(S6_E_TRACE)',s)
    def test_begin_run_finish_actual_rc_before_runtime_error_gate(self):
        s=(HERE/'main.c').read_text()
        order=['npu_trace_begin(&trace_context,seq)','if (g_mailbox.trace_status!=0) park_error(S6_E_TRACE)',
               'stai_return_code rc=stai_nsl_qcfs_seed0_run(network,STAI_MODE_SYNC)',
               'npu_trace_finish(&trace_context,rc)','g_mailbox.api_status[4]=(int32_t)rc',
               'g_mailbox.api_status[5]=(int32_t)error_rc','memcpy(output_copy,out[0],20)',
               'g_mailbox.output_count=5','if (rc!=STAI_SUCCESS || error_rc!=STAI_SUCCESS) park_error(0)',
               'if (g_mailbox.trace_status!=0 || !g_mailbox.trace_complete || g_mailbox.trace_error) park_error(S6_E_TRACE)',
               'g_mailbox.state=S6_DONE; __DMB(); g_mailbox.response_sequence=seq;']
        positions=[s.index(x) for x in order];self.assertEqual(positions,sorted(positions))
        self.assertEqual(s.count('npu_trace_finish('),1)
    def test_no_finite_or_request_gate_weakened(self):
        s=(HERE/'main.c').read_text()
        self.assertEqual(s.count('if (!request_unchanged(seq,row))'),2)
        self.assertIn('for (unsigned i=0; i<41; ++i)',s)
        self.assertIn('for (unsigned i=0; i<5; ++i) g_mailbox.output_words[i]=output_copy[i]',s)
        self.assertIn('if (!finite_word(input_copy[i])) park_error(S6_E_INPUT)',s)
        self.assertIn('if (!finite_word(output_copy[i])) park_error(S6_E_OUTPUT)',s)
        self.assertIn('out[0] != S6_RUNTIME_IO_ADDRESS',s)
        self.assertNotIn('g_mailbox.platform_ack =',s)
    def test_no_error_path_clears_trace_or_publishes_done(self):
        s=(HERE/'main.c').read_text();park=s.split('static void park_error',1)[1].split('static void checked',1)[0]
        self.assertIn('trace_snapshot();',park);self.assertIn('g_mailbox.state = S6_ERROR',park)
        self.assertNotIn('memset',park);self.assertNotIn('S6_DONE',park);self.assertNotIn('response_sequence',park)
    def test_linker_has_distinct_noload_and_exact_assertions(self):
        s=(HERE/'linker.ld').read_text()
        for token in ('TRACE (rw) : ORIGIN = 0x340F8200, LENGTH = 0x199C',
                      '.npu_trace (NOLOAD)', 'KEEP(*(.npu_trace))', 'trace PT_LOAD FLAGS(6)',
                      'SIZEOF(.npu_trace) == 6556','SIZEOF(.mailbox) == 512',
                      'ORIGIN(MAILBOX) + LENGTH(MAILBOX) == ORIGIN(TRACE)',
                      'ORIGIN(TRACE) + LENGTH(TRACE) <= __weights_start'):
            self.assertIn(token,s)
    def test_frozen_helpers_unchanged_and_fixed_compile_closure(self):
        def functions(path):
            tree=ast.parse(path.read_text());return {x.name:ast.dump(x) for x in tree.body if isinstance(x,ast.FunctionDef)}
        old=functions(b.ORIGINAL/'build.py');new=functions(HERE/'build.py')
        for name in ('pin','bookend','hold','encoded','candidate_namespace','candidate_pins'):
            self.assertEqual(new[name],old[name],name)
        s=(HERE/'build.py').read_text()
        self.assertIn('[TRACE/"npu_trace.c",TRACE/"npu_trace_bind.c"]+runtime+devices+hal',s)
        self.assertIn('"Direct input changed before frozen-source check"',s)
        self.assertIn('"npu_trace_callback","npu_trace_finish"',s)
        self.assertIn('-DLL_ATON_RT_MODE=LL_ATON_RT_POLLING',b.DEFS)
        self.assertIn('-DLL_ATON_SW_FALLBACK=1',b.DEFS)
        self.assertNotIn('-DNPU_TRACE_HOST_CONTROL',b.DEFS)
    def test_trace_host_retention_contract_explicit(self):
        s=(HERE/'README.md').read_text()
        for token in ('before the next request is a mandatory host obligation',
                      'response_sequence retains','not a live seqlock',
                      'not independent hardware proof','not accepted logits'):
            self.assertIn(token,s)

if __name__=='__main__':unittest.main(verbosity=2)
