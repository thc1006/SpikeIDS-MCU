"""Portable-board fixed-vector validation, independent of concrete transport.

Does not power/program a board or assume that a serial port is the right target.
"""
import hashlib
import io
from pathlib import Path
import numpy as np
from protocol import VECTORS,require

REPO=Path(__file__).resolve().parents[3]
ARCHIVE=REPO/'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq/validation_vectors.npz'


def load_rows():
    require(ARCHIVE==ARCHIVE.resolve(),'Noncanonical original archive')
    raw=ARCHIVE.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==VECTORS,'Wrong fixed validation vectors')
    with np.load(io.BytesIO(raw),allow_pickle=False) as z:
        x,ref,ids=(z[n].copy() for n in ('x','reference_logits','validation_row_ids'))
    require(x.shape==(1024,41) and x.dtype==np.dtype('<f4') and
            ref.shape==(1024,5) and ref.dtype==np.dtype('<f4'),'Wrong original tensors')
    require(ids.shape==(1024,) and ids.dtype==np.dtype('<i8') and
            np.all(ids>=0) and len(np.unique(ids))==1024,'Wrong original IDs')
    require(np.isfinite(x).all() and np.isfinite(ref).all(),'Nonfinite original tensor')
    require(ARCHIVE.read_bytes()==raw,'Original archive changed during read')
    return tuple((int(ids[i]),x[i].tobytes(),ref[i].tobytes()) for i in range(1024))


def run(session,rows,retain):
    """Preserve every response before continuing; never retry failed hardware IO.

    Returns a numerical result, not board firmware/physical-energy acceptance.
    No partial run is averaged or promoted. Extra/missing rows fail before IO.
    """
    require(type(rows) is tuple and len(rows)==1024,'Exactly 1024 original rows required')
    require(len({r[0] for r in rows})==1024,'Duplicate row ID')
    for row_id,input_words,reference in rows:
        require(type(row_id) is int and row_id>=0 and type(input_words) is bytes and
                len(input_words)==164 and type(reference) is bytes and len(reference)==20,'Row schema')
        require(np.isfinite(np.frombuffer(reference,dtype='<f4')).all(),'Nonfinite reference')
    session.hello()
    actual=[];refs=[]
    for ordinal,(row_id,input_words,reference) in enumerate(rows):
        output=session.infer(row_id,input_words)
        try:
            retain({'sequence':ordinal+1,'ordinal':ordinal,'row_id':row_id,
                    'input_hex':input_words.hex(),'reference_logits_hex':reference.hex(),
                    'actual_logits_hex':output.hex()})
        except BaseException:
            session.poisoned=True
            raise
        actual.append(np.frombuffer(output,dtype='<f4'))
        refs.append(np.frombuffer(reference,dtype='<f4'))
    actual=np.stack(actual);refs=np.stack(refs)
    close=np.isclose(refs,actual,atol=1e-6,rtol=1e-5)
    different=np.argmax(refs,1)!=np.argmax(actual,1)
    failed=np.argwhere(~close)
    return {'rows':1024,'outputs_per_row':5,'allclose_argument_order':['reference','actual'],
        'atol':1e-6,'rtol':1e-5,'threshold_arithmetic':'NumPy FP32',
        'failed_coordinates':failed.tolist(),'argmax_disagreements':int(different.sum()),
        'full_logit_parity_passed':bool(close.all() and not different.any()),
        'max_abs_error':float(np.max(np.abs(refs-actual))),
        'firmware_readback_verified':False,'latency_validated':False,
        'energy_measured':False,'research_measurement_accepted':False}
