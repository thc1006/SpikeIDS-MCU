"""Tiny real filesystem / fake compiler author controls; no vendor invocation."""
from contextlib import contextmanager, ExitStack
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sram_candidate',HERE/'generate.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)

def tiny_metadata():
    pools=[]
    for ident,(name,(base,size,rights,fname,weights)) in enumerate(g.POOLS.items(),1):
        pools.append({'id':ident,'name':name,'address':str(base),'size_bytes':size,
            'used_size_bytes':16 if weights else 256,'rights':rights,'cacheable':'CACHEABLE_OFF',
            'subpools':[],'user_allocated':False,'attributes':{'use_for_initrs':weights},
            'fname':f'atonbuf.{fname}.raw','buffers':[1] if weights else [2,3]})
    buffers=[{'id':1,'mpool_id':1,'is_param':True,'offset_start':0,'size_bytes':16,'alignment':4},
             {'id':2,'mpool_id':2,'is_param':False,'offset_start':0,'size_bytes':164,'alignment':4,
              'shape':[1,41],'format':'STAI_FORMAT_FLOAT','nbits':32},
             {'id':3,'mpool_id':2,'is_param':False,'offset_start':0,'size_bytes':20,'alignment':4,
              'shape':[1,5],'format':'STAI_FORMAT_FLOAT','nbits':32}]
    graph={'inputs':[2],'outputs':[3],
        'original_inputs':[{'shape':[1,41],'data_format':{'type':'FLOAT','size':32,'quantizer':'NONE'}}],
        'original_outputs':[{'shape':[1,5],'data_format':{'type':'FLOAT','size':32,'quantizer':'NONE'}}],
        'nodes':[{'id':i,'name':f'epoch_{i}','mapping':k} for i,k in enumerate(('NODE_SW','NODE_HW','NODE_SW_HW'),1)]}
    return {'json_schema_version':'2.0','ec_blobs_info':[],'memory_pools':pools,'buffers':buffers,
            'memory_footprint':{'weights':16,'activations':256},'graphs':[graph]}

def write_generated(directory,mutate=None):
    info=tiny_metadata()
    if mutate:mutate(info)
    name=g.v.NAME
    (directory/f'{name}_c_info.json').write_bytes(g.v.encoded(info))
    (directory/f'{name}.c').write_text('void *a=ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34200000UL + 0);\n'
                                     'void *b=ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL + 0);\n'
                                     'struct config x={.cacheable=0,.cache_allocate=0};\n')
    for file in (f'{name}.h',f'stai_{name}.c',f'stai_{name}.h'):(directory/file).write_text('/* tiny fixture */\n')
    (directory/f'{name}_atonbuf.SRAM_WEIGHTS.raw').write_bytes(bytes(16))
    (directory/f'{name}_generate_report.txt').write_text('Total number of epochs 3\n>> pure software (SW) epochs 1\n'
        '>> hybrid epochs (using both software and hardware) 1\n>> pure hardware (HW or EC) epochs 1\n')

def write_references(path,change=None):
    entries={'x.npy':('<f4',(1024,41)),'reference_logits.npy':('<f4',(1024,5)),
             'original_logits.npy':('<f4',(1024,5)),'validation_row_ids.npy':('<i8',(1024,))}
    if change:change(entries)
    with zipfile.ZipFile(path,'w') as z:
        for name,(dtype,shape) in entries.items():
            header=repr({'descr':dtype,'fortran_order':False,'shape':shape}).encode()+b'\n'
            z.writestr(name,b'\x93NUMPY\x01\x00'+struct.pack('<H',len(header))+header)

@contextmanager
def evidence(root,*,mutate=None,rc=0,after=None):
    """Patch only source provider/location and Popen; run/Output/validation stay real."""
    repo=Path(root)/'repo';payload=repo/'exports/a/b/qdq';payload.mkdir(parents=True)
    parent=repo/'results/bringup';parent.mkdir(parents=True)
    model=payload/'model_qdq_int8.onnx';model.write_bytes(b'tiny opaque model')
    refs=payload/'validation_vectors.npz';write_references(refs)
    held={str(p):g.v.snapshot(p) for p in (model,refs)}
    calls=[]
    class FakeProcess:
        def __init__(self,argv,**kw):
            calls.append(argv);self.returncode=rc;self.pid=123456789
            directory=Path(argv[argv.index('--output')+1]);write_generated(directory,mutate)
            kw['stdout'].write(b'Tiny synthetic compiler\n');kw['stderr'].write(b'')
            if after:after(directory)
        def wait(self,timeout=None):return self.returncode
        def poll(self):return self.returncode
    with ExitStack() as stack:
        for obj,key,value in [(g,'OUTPUT_PARENT',parent),(g.v,'REPO',repo),(g.v,'PAYLOAD',payload),
            (g.v,'INPUT_HASHES',{'model_qdq_int8.onnx':hashlib.sha256(model.read_bytes()).hexdigest()}),
            (g,'capture_inputs',lambda:(held,g.reference_headers(refs))),(g.subprocess,'Popen',FakeProcess)]:
            stack.enter_context(patch.object(obj,key,value))
        yield {'output':parent/'internal_sram_actual_01','pins':held,'calls':calls,'model':model,'refs':refs}

class GenerateTests(unittest.TestCase):
    def test_full_positive(self):
        with tempfile.TemporaryDirectory() as temp,evidence(temp) as e:
            result=g.run(e['output']);self.assertEqual(len(e['calls']),1)
            self.assertIsNone(result['actual_process_exit']);self.assertFalse(result['numerical_equivalence_verified'])
            self.assertEqual(result['observations']['mapping']['reported_epochs']['total'],3)
            self.assertTrue((e['output']/'RESULT.json').is_file())
    def test_nonzero_retains_failure_once(self):
        with tempfile.TemporaryDirectory() as temp,evidence(temp,rc=23) as e:
            with self.assertRaisesRegex(Exception,'Single compiler call failed'):g.run(e['output'])
            self.assertEqual(len(e['calls']),1)
            self.assertEqual(g.load_json(e['output']/'generate.json')['actual_return_code'],23)
            self.assertTrue((e['output']/'FAILED.json').is_file());self.assertFalse((e['output']/'RESULT.json').exists())
    def test_stale_output_does_not_invoke(self):
        with tempfile.TemporaryDirectory() as temp,evidence(temp) as e:
            e['output'].mkdir()
            with self.assertRaises(Exception):g.run(e['output'])
            self.assertEqual(e['calls'],[])
    def test_arbitrary_cli_refused(self):
        with self.assertRaises(SystemExit) as err:g.main(['--output-dir','/tmp/not-created','--model','evil'])
        self.assertEqual(err.exception.code,2)
    def test_command_exact_profile(self):
        argv=g.command(Path('/synthetic'))
        self.assertEqual(argv.count('generate'),1);self.assertIn('internal_sram@/synthetic/neural_art.json',argv)
        self.assertNotIn('--Ocache-opt',' '.join(argv));self.assertNotIn('--enable-virtual-mem-pools',' '.join(argv))
    def invalid(self,mutate):
        with tempfile.TemporaryDirectory() as temp,evidence(temp,mutate=mutate) as e:
            with self.assertRaises(Exception):g.run(e['output'])
            self.assertTrue((e['output']/'FAILED.json').is_file())
    def test_unknown_pool(self):self.invalid(lambda x:x['memory_pools'].append(copy.deepcopy(x['memory_pools'][0])))
    def test_buffer_spill(self):self.invalid(lambda x:x['buffers'][0].update(mpool_id=2))
    def test_buffer_overrun(self):self.invalid(lambda x:x['buffers'][0].update(size_bytes=17))
    def test_pool_capacity(self):self.invalid(lambda x:x['memory_pools'][0].update(size_bytes=0x80000))
    def test_cacheable(self):self.invalid(lambda x:x['memory_pools'][0].update(cacheable='CACHEABLE_ON'))
    def test_buffer_membership(self):self.invalid(lambda x:x['memory_pools'][0].update(buffers=[]))
    def test_typed_pool_id(self):self.invalid(lambda x:x['memory_pools'][0].update(id=True))
    def test_interface_width(self):self.invalid(lambda x:x['graphs'][0]['original_inputs'][0].update(shape=[1,42]))
    def test_epoch_mismatch(self):self.invalid(lambda x:x['graphs'][0]['nodes'].pop())
    def test_allocated_io_wrong_buffer(self):self.invalid(lambda x:x['graphs'][0].update(inputs=[1]))
    def test_allocated_io_wrong_shape(self):self.invalid(lambda x:x['buffers'][1].update(shape=[1,42]))
    def test_pointer_unused_capacity(self):
        def change(d):
            p=d/f'{g.v.NAME}.c';p.write_text(p.read_text().replace('0x34200000UL + 0','0x34200000UL + 20'))
        with tempfile.TemporaryDirectory() as temp,evidence(temp,after=change) as e:
            with self.assertRaises(Exception):g.run(e['output'])
    def test_cache_fields_disabled(self):
        def change(d):
            p=d/f'{g.v.NAME}.c';p.write_text(p.read_text().replace('.cache_allocate=0','.cache_allocate=1'))
        with tempfile.TemporaryDirectory() as temp,evidence(temp,after=change) as e:
            with self.assertRaises(Exception):g.run(e['output'])
    def test_extra_raw(self):
        with tempfile.TemporaryDirectory() as temp,evidence(temp,after=lambda d:(d/'extra.raw').write_bytes(b'x')) as e:
            with self.assertRaises(Exception):g.run(e['output'])
    def test_external_address(self):
        def change(d):(d/f'{g.v.NAME}.c').write_text('void *a=ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x71000000UL);')
        with tempfile.TemporaryDirectory() as temp,evidence(temp,after=change) as e:
            with self.assertRaises(Exception):g.run(e['output'])
    def test_reference_header_wrong_count(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'r.npz';write_references(p,lambda x:x.update({'x.npy':('<f4',(1023,41))}))
            with self.assertRaises(Exception):g.reference_headers(p)
    def test_profile_and_mpool_fixed_hashes(self):
        for name,digest in g.PROFILE_HASHES.items():self.assertEqual(hashlib.sha256((HERE/name).read_bytes()).hexdigest(),digest)
        mp=g.load_json(HERE/'internal_sram.mpool')['memory']
        self.assertEqual(mp['cacheinfo'],[]);self.assertEqual(len(mp['mempools']),2)

if __name__=='__main__':unittest.main()
