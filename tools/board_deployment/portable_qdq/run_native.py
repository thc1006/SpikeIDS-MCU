"""One fixed native semantic probe; no board/ORT/Torch/model-selection path."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import generate as g

HERE=Path(__file__).resolve().parent
CC=Path('/usr/bin/x86_64-linux-gnu-gcc-15')
FLAGS=('-std=c11','-O2','-Wall','-Wextra','-Werror','-fno-fast-math',
       '-ffp-contract=off','-fexcess-precision=standard')
ROWS=1024

def encoded(value): return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def child_environment(output):
    # No inherited compiler search overrides, preload hooks, credentials or
    # unrelated service configuration. Compiler temporary files use owned root.
    return {'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C','TZ':'UTC',
            'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
            'TMPDIR':str(output)}

def load_vectors(raw):
    with np.load(io.BytesIO(raw),allow_pickle=False) as archive:
        g.require(set(archive.files)=={'x','reference_logits','original_logits','validation_row_ids'}, 'archive keys')
        values={k:archive[k].copy() for k in archive.files}
    for key,shape in (('x',(ROWS,41)),('reference_logits',(ROWS,5)),('original_logits',(ROWS,5))):
        v=values[key]
        g.require(v.shape==shape and v.dtype==np.float32 and np.isfinite(v).all(), 'FP32 archive shape/finite')
    ids=values['validation_row_ids']
    g.require(ids.shape==(ROWS,) and ids.dtype.kind in 'iuSU' and len(np.unique(ids))==ROWS, 'row IDs')
    return values

def decode_records(raw):
    g.require(len(raw)==ROWS*28, 'native output length')
    words=np.frombuffer(raw,dtype='<u4').reshape(ROWS,7)
    g.require(np.array_equal(words[:,0],np.arange(ROWS,dtype=np.uint32)), 'native row ordering')
    statuses=words[:,1].copy()
    g.require(np.array_equal(statuses,np.zeros(ROWS,dtype=np.uint32)), 'native row failure')
    logits=words[:,2:].copy().view('<f4').astype(np.float32,copy=False)
    g.require(np.isfinite(logits).all(), 'native output finite')
    return logits,statuses

def compare(reference,actual):
    g.require(reference.shape==actual.shape==(ROWS,5) and reference.dtype==actual.dtype==np.float32
              and np.isfinite(reference).all() and np.isfinite(actual).all(), 'comparison inputs')
    # Exactly the held export_verified.compare_logits orientation and five fields.
    legacy={'allclose':bool(np.allclose(reference,actual,atol=1e-6,rtol=1e-5)),
            'max_abs_error':float(np.max(np.abs(reference.astype(float)-actual))),
            'prediction_disagreement_fraction':float(np.mean(reference.argmax(1)!=actual.argmax(1))),
            'vectors_checked':len(reference),
            'scope':'only these validation vectors, not every possible input'}
    mask=~np.isclose(reference,actual,atol=1e-6,rtol=1e-5)
    bits=reference.view(np.uint32)!=actual.view(np.uint32)
    return {'legacy':legacy,'allclose_argument_order':['reference','actual'],
            'threshold_arithmetic':'NumPy FP32','relative_tolerance_anchor':'actual',
            'failed_values':int(mask.sum()),'failed_rows':int(mask.any(axis=1).sum()),
            'differing_fp32_words':int(bits.sum()),
            'argmax_disagreements':int(np.count_nonzero(reference.argmax(1)!=actual.argmax(1))),
            'candidate_numerical_pass':legacy['allclose'] and legacy['prediction_disagreement_fraction']==0.0}

def run(output):
    g.require(sys.flags.optimize==0, 'optimized Python forbidden')
    g.require(Path(g.__file__).resolve()==HERE/'generate.py', 'generator origin')
    output,fd,parent_identity=g.create_output(output)
    identity=None; names=set(); pins={}; own={}
    def write(name,data):
        g.write_new(output,identity,name,data); names.add(name)
        own[str(output/name)]=g.snapshot(output/name)[1]
    def hold(p):
        raw,pin=g.snapshot(p)
        if str(p) in pins: g.require(pins[str(p)]==pin, 'original pin changed')
        else: pins[str(p)]=pin
        return raw
    def command(label,argv,stdin=None,timeout=60):
        g.owned(output,identity)
        try:
            done=subprocess.run([str(x) for x in argv],input=stdin,capture_output=True,
                                timeout=timeout,check=False,cwd=output,
                                env=child_environment(output))
        except subprocess.TimeoutExpired as exc:
            write(label+'.stdout',exc.stdout or b''); write(label+'.stderr',exc.stderr or b'')
            write(label+'.json',encoded({'argv':[str(x) for x in argv],
                  'returncode':None,'timeout':True,'timeout_seconds':timeout,
                  'environment':child_environment(output)}))
            raise
        write(label+'.stdout',done.stdout); write(label+'.stderr',done.stderr)
        write(label+'.json',encoded({'argv':[str(x) for x in argv],'returncode':done.returncode,
              'environment':child_environment(output),
              'stdout_sha256':hashlib.sha256(done.stdout).hexdigest(),
              'stderr_sha256':hashlib.sha256(done.stderr).hexdigest(),
              'stdin_sha256':None if stdin is None else hashlib.sha256(stdin).hexdigest()}))
        g.require(done.returncode==0, f'{label} process exit {done.returncode}')
        return done
    def namespace():
        expected=names|{'model_sources','candidate'}
        g.require(set(os.listdir(output))==expected, 'native output namespace')
        g.require(set(os.listdir(output/'model_sources'))=={'model.c','MANIFEST.json'}, 'generated namespace')
    try:
        for p in (HERE/'run_native.py',HERE/'generate.py',HERE/'portable_qdq.c',HERE/'portable_qdq.h',
                  HERE/'native_main.c',CC,Path(np.__file__).resolve()): hold(p)
        graph=hold(g.BUNDLE/'model_qdq_int8.onnx')
        vectors=hold(g.BUNDLE/'validation_vectors.npz')
        g.require(hashlib.sha256(graph).hexdigest()==g.MODEL_SHA and
                  hashlib.sha256(vectors).hexdigest()==g.VECTORS_SHA, 'fixed payload identities')
        values=load_vectors(vectors)
        identity=g.publish_directory(output,fd,parent_identity)
        write('STARTED.json',encoded({'kind':'portable_qdq_native_probe_intent','original_pins':pins,
              'flags':FLAGS,'rows':ROWS,'hardware_accessed':False,'numpy_version':np.__version__,
              'allclose_argument_order':['reference','actual'],'automatic_retry':False}))
        generated=g.generate(output/'model_sources')
        for p,pin in generated['original_pins'].items():
            if p in pins: g.require(pins[p]==pin, 'generation original pin')
            else: pins[p]=pin
        for n in ('model.c','MANIFEST.json'): own[str(output/'model_sources'/n)]=g.snapshot(output/'model_sources'/n)[1]
        command('compiler_version',[CC,'--version'],timeout=10)
        command('compile',[CC,*FLAGS,'-I',HERE,HERE/'portable_qdq.c',HERE/'native_main.c',
                output/'model_sources/model.c','-lm','-o',output/'candidate'],timeout=120)
        own[str(output/'candidate')]=g.snapshot(output/'candidate')[1]
        input_bytes=np.ascontiguousarray(values['x'],dtype='<f4').tobytes()
        native=command('native',[output/'candidate'],stdin=input_bytes,timeout=300)
        actual,statuses=decode_records(native.stdout)
        metrics=compare(values['reference_logits'],actual)
        archive=io.BytesIO()
        np.savez(archive,actual_logits=actual,reference_logits=values['reference_logits'],
                 validation_row_ids=values['validation_row_ids'],row_ordinals=np.arange(ROWS,dtype=np.uint32),
                 statuses=statuses)
        write('logits.npz',archive.getvalue())
        g.require(all(g.snapshot(p)[1]==pin for p,pin in pins.items()), 'source/input hash bookend')
        g.require(all(g.snapshot(p)[1]==pin for p,pin in own.items()), 'output hash bookend')
        record={'schema_version':1,'kind':'portable_qdq_native_semantic_probe','original_pins':pins,
                'output_pins':dict(own),'graph_sha256':g.MODEL_SHA,'validation_sha256':g.VECTORS_SHA,
                'compiler_flags':FLAGS,'numpy_version':np.__version__,'rows':ROWS,'outputs_per_row':5,
                'native_returncode':native.returncode,'metrics':metrics,
                'arithmetic':'per-channel FP32 DQ, sequential non-FMA FP32 Gemm, complete QDQ/QCFS',
                'row_order':'original validation archive order; no sorting or selection',
                'actual_process_exit':None,'candidate_only':True,'hardware_accessed':False,
                'board_parity_accepted':False,'fastest_backend_claimed':False,'all_integer_execution_claimed':False,
                'full_compiler_or_runtime_dependency_closure_claimed':False,'automatic_retry':False}
        write('RESULT.json',encoded(record))
        # After the final expensive/hash callbacks: direct original stats and names.
        g.require(all(g.snapshot(p)[1]==pin for p,pin in pins.items()), 'last input hashes')
        g.owned(output.parent,parent_identity); g.owned(output,identity)
        namespace(); g.final_stats(pins|own)
        return record
    except Exception as exc:
        if identity is not None:
            try: g.write_new(output,identity,'FAILED.json',encoded({'kind':'native_probe_failure','error':str(exc)}))
            except (OSError,ValueError): pass
        raise
    finally: os.close(fd)

if __name__=='__main__':
    parser=argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.output_dir),sort_keys=True,allow_nan=False))
