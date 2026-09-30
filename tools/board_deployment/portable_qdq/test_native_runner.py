"""Bounded synthetic complete native pipeline and cheap protocol controls."""
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import run_native as r
from test_portable_qdq import toy,reference

def records():
    out=np.zeros((1024,7),dtype='<u4'); out[:,0]=np.arange(1024,dtype=np.uint32)
    return out

class ProtocolTests(unittest.TestCase):
    def test_child_environment_is_allowlist_not_inherited(self):
        with patch.dict(r.os.environ,{'LD_PRELOAD':'forbidden','CPATH':'forbidden',
                                    'GCC_EXEC_PREFIX':'forbidden','SECRET_TOKEN':'forbidden'}):
            env=r.child_environment(Path('/tmp/owned-test'))
        self.assertEqual(set(env),{'PATH','LANG','LC_ALL','TZ','OMP_NUM_THREADS',
                                  'OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','TMPDIR'})
        self.assertEqual(env['PATH'],'/usr/bin:/bin')
        self.assertEqual(env['TMPDIR'],'/tmp/owned-test')
    def test_full_decode_all_five_last_row(self):
        raw=records(); raw[-1,6]=0x3f800000
        values,rc=r.decode_records(raw.tobytes())
        self.assertEqual(values.shape,(1024,5)); self.assertEqual(values[-1,-1],1)
        self.assertFalse(rc.any())
    def test_short_stream(self):
        with self.assertRaisesRegex(ValueError,'length'): r.decode_records(records().tobytes()[:-1])
    def test_last_row_order(self):
        raw=records(); raw[-1,0]=1022
        with self.assertRaisesRegex(ValueError,'ordering'): r.decode_records(raw.tobytes())
    def test_status_reject(self):
        raw=records(); raw[3,1]=2
        with self.assertRaisesRegex(ValueError,'failure'): r.decode_records(raw.tobytes())
    def test_nonfinite_word(self):
        raw=records(); raw[1023,6]=0x7fc00000
        with self.assertRaisesRegex(ValueError,'finite'): r.decode_records(raw.tobytes())
    def test_comparison_true_and_negative(self):
        ref=np.zeros((1024,5),np.float32); actual=ref.copy()
        self.assertTrue(r.compare(ref,actual)['candidate_numerical_pass'])
        actual[-1,-1]=1
        m=r.compare(ref,actual)
        self.assertFalse(m['candidate_numerical_pass']); self.assertEqual(m['failed_values'],1)
        self.assertEqual(m['argmax_disagreements'],1); self.assertEqual(m['legacy']['max_abs_error'],1)
    def test_signed_zero_counts_without_false_allclose(self):
        ref=np.zeros((1024,5),np.float32); actual=ref.copy(); actual[-1,-1]=-0.0
        m=r.compare(ref,actual)
        self.assertTrue(m['candidate_numerical_pass']); self.assertEqual(m['differing_fp32_words'],1)
        self.assertEqual(m['failed_values'],0)
    def test_comparison_orientation_and_dtype(self):
        ref=np.zeros((1024,5),np.float32); actual=np.ones_like(ref)
        real=np.allclose
        with patch.object(r.np,'allclose',wraps=real) as call:
            r.compare(ref,actual)
        self.assertIs(call.call_args.args[0],ref); self.assertIs(call.call_args.args[1],actual)
        self.assertEqual(call.call_args.kwargs,{'atol':1e-6,'rtol':1e-5})
        with self.assertRaises(ValueError): r.compare(ref.astype(np.float64),actual.astype(np.float64))

class CompleteSyntheticTests(unittest.TestCase):
    def fixture(self,directory):
        bundle=directory/'bundle'; bundle.mkdir()
        model=toy(r.g.DIMS); raw=model.SerializeToString(); (bundle/'model_qdq_int8.onnx').write_bytes(raw)
        parsed=r.g.parse_graph(raw)
        x=np.zeros((1024,41),np.float32)
        expected=reference(x[0],parsed)
        logits=np.repeat(expected[None,:],1024,axis=0).astype(np.float32)
        arrays=io.BytesIO(); np.savez(arrays,x=x,reference_logits=logits,original_logits=logits,
                         validation_row_ids=np.arange(10000,11024,dtype=np.int64))
        vr=arrays.getvalue(); (bundle/'validation_vectors.npz').write_bytes(vr)
        return bundle,hashlib.sha256(raw).hexdigest(),hashlib.sha256(vr).hexdigest()
    def test_full_synthetic_generation_compile_1024(self):
        with tempfile.TemporaryDirectory(prefix='portable-full-toy-') as t:
            root=Path(t); bundle,msha,vsha=self.fixture(root)
            with patch.object(r.g,'BUNDLE',bundle),patch.object(r.g,'MODEL_SHA',msha),patch.object(r.g,'VECTORS_SHA',vsha):
                result=r.run(root/'out')
            self.assertTrue(result['metrics']['candidate_numerical_pass'])
            self.assertEqual(result['rows'],1024); self.assertEqual(result['native_returncode'],0)
            self.assertEqual(result['graph_sha256'],msha)
            saved=json.loads((root/'out/RESULT.json').read_text())
            self.assertIsNone(saved['actual_process_exit']); self.assertFalse(saved['board_parity_accepted'])
            self.assertEqual((root/'out/native.stdout').stat().st_size,28672)
            with np.load(root/'out/logits.npz',allow_pickle=False) as data:
                self.assertEqual(data['actual_logits'].shape,(1024,5))
                self.assertEqual(data['validation_row_ids'][-1],11023)
            self.assertFalse((root/'out/FAILED.json').exists())
    def test_generation_stale_output_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError,'fresh'): r.g.generate(t)
    def test_wrong_fixed_identity_before_output(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); bundle,msha,vsha=self.fixture(root)
            with patch.object(r.g,'BUNDLE',bundle),patch.object(r.g,'MODEL_SHA','0'*64),patch.object(r.g,'VECTORS_SHA',vsha):
                with self.assertRaisesRegex(ValueError,'identities'): r.run(root/'out')
            self.assertFalse((root/'out').exists())
    def test_parent_rebind_not_written(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); parent=root/'parent'; parent.mkdir(); foreign=root/'foreign'; foreign.mkdir()
            output,fd,identity=r.g.create_output(parent/'out')
            parent.rename(root/'original'); parent.symlink_to(foreign,target_is_directory=True)
            try:
                with self.assertRaisesRegex(ValueError,'directory'): r.g.publish_directory(output,fd,identity)
            finally: r.g.os.close(fd)
            self.assertEqual(list(foreign.iterdir()),[])
    def test_late_generated_file_change_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); bundle,msha,vsha=self.fixture(root); real=r.g.snapshot
            def snapshot(p):
                result=real(p)
                if Path(p)==bundle/'validation_vectors.npz' and (root/'out/MANIFEST.json').exists():
                    (root/'out/model.c').write_bytes(b'changed')
                return result
            with patch.object(r.g,'BUNDLE',bundle),patch.object(r.g,'MODEL_SHA',msha),patch.object(r.g,'VECTORS_SHA',vsha),patch.object(r.g,'snapshot',snapshot):
                with self.assertRaisesRegex(ValueError,'late file'): r.g.generate(root/'out')
            self.assertTrue((root/'out/FAILED.json').exists())

if __name__=='__main__': unittest.main()
