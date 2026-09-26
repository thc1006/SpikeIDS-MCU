"""Root independent saved-only replay of the one completed native experiment.

Does not import the generator/runner, ORT or Torch, execute the native binary,
recompile, or access hardware. stdout is the complete bounded review result.
"""
import hashlib
import io
import json
from pathlib import Path
import numpy as np

REPO=Path(__file__).resolve().parents[3]
OUT=REPO/'results/portable_qdq_native_20260925_01'
VECTORS=REPO/'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq/validation_vectors.npz'
REPORT_SHA='cb3536b760e40ad2fe6ce942e677ab2472837e2a73ffb86edd15700c3a171a93'
RECEIPT_SHA='5222d43668261d9cbd2a2c29fa19d9cd86c300354a71a5020717dc882b732de2'


def require(condition, message):
    if not condition: raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def check_pin(path,pin):
    p=Path(path);require(p==p.resolve(),'Noncanonical path')
    before=p.stat();raw=p.read_bytes();after=p.stat()
    require(sha(raw)==pin['sha256'],'Hash changed: '+str(p))
    for k,v in pin.items():
        if k!='sha256':require(getattr(before,k)==v==getattr(after,k),'Stat changed: '+str(p)+' '+k)
    return raw


def main():
    raw=(OUT/'RESULT.json').read_bytes();require(sha(raw)==REPORT_SHA,'Report digest')
    report=json.loads(raw)
    receipt_raw=(Path(__file__).parent/'NATIVE_ACTUAL_01_EXECUTION.json').read_bytes()
    require(sha(receipt_raw)==RECEIPT_SHA,'External receipt digest')
    receipt=json.loads(receipt_raw)
    require(type(receipt['actual_process']['observed_return_code']) is int and
            receipt['actual_process']['observed_return_code']==0,'External native exit')
    check_pin(OUT/'RESULT.json',receipt['report_original_pin'])
    retained={}
    for group in ('original_pins','output_pins'):
        for p,pin in report[group].items():retained[p]=check_pin(p,pin)
    require(len(report['original_pins'])==9 and len(report['output_pins'])==14,'Pin count')
    require(report['hardware_accessed'] is False and report['board_parity_accepted'] is False,'Scope changed')
    for name in ('compile.json','native.json'):
        doc=json.loads(retained[str(OUT/name)])
        require(type(doc['returncode']) is int and doc['returncode']==0,'Native child failure')
    with np.load(io.BytesIO(retained[str(VECTORS)]),allow_pickle=False) as z:
        ids=z['validation_row_ids'].copy();reference=z['reference_logits'].copy();x=z['x'].copy()
    records=np.frombuffer(retained[str(OUT/'native.stdout')],dtype='<u4')
    require(records.size==1024*7,'Native record count');records=records.reshape(1024,7)
    require(np.array_equal(records[:,0],np.arange(1024,dtype='<u4')),'Native order')
    require(not records[:,1].any(),'Native status')
    actual=records[:,2:].copy().view('<f4')
    require(reference.dtype==np.dtype('<f4') and reference.shape==(1024,5),'Reference shape')
    require(np.isfinite(actual).all(),'Nonfinite native output')
    with np.load(io.BytesIO(retained[str(OUT/'logits.npz')]),allow_pickle=False) as z:
        require(set(z.files)=={'actual_logits','reference_logits','validation_row_ids',
                              'row_ordinals','statuses'},'Native NPZ schema')
        require(np.array_equal(z['validation_row_ids'],ids),'Original row IDs')
        require(z['actual_logits'].tobytes()==actual.tobytes(),'Raw/NPZ logits')
        require(z['reference_logits'].tobytes()==reference.tobytes(),'Original reference logits')
        require(np.array_equal(z['row_ordinals'],records[:,0]) and
                np.array_equal(z['statuses'],records[:,1]),'Raw/NPZ ordinals and statuses')
    native=json.loads(retained[str(OUT/'native.json')])
    require(native['stdin_sha256']==sha(x.tobytes()),'Original full input tensor not native stdin')
    different=int(np.count_nonzero(actual.view('<u4')!=reference.view('<u4')))
    failed=int(np.count_nonzero(~np.isclose(reference,actual,atol=1e-6,rtol=1e-5)))
    disagree=int(np.count_nonzero(reference.argmax(1)!=actual.argmax(1)))
    require((different,failed,disagree)==(0,0,0),'Saved numerical comparison differs')
    require(report['metrics']['differing_fp32_words']==different and
            report['metrics']['argmax_disagreements']==disagree,'Reported metrics differ')
    for group in ('original_pins','output_pins'):
        for p,pin in report[group].items():check_pin(p,pin)
    require((OUT/'RESULT.json').read_bytes()==raw,'Report changed during review')
    return {'kind':'independent_saved_native_review','input_pins':9,'output_pins':14,
        'rows':1024,'output_words':5120,'differing_words':different,'failed_values':failed,
        'argmax_disagreements':disagree,'input_tensor_sha256':sha(x.tobytes()),
        'hardware_accessed':False,'native_rerun':False,'board_parity_accepted':False}


if __name__=='__main__':print(json.dumps(main(),sort_keys=True))
