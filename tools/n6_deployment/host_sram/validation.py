"""Exact ordered 1,024-row parity evaluation; not latency/energy acceptance."""
import math
import struct
import numpy as np

ATOL = 1e-6
RTOL = 1e-5


def require(ok, message):
    if not ok: raise ValueError(message)


def evaluate(rows, records):
    require(type(rows) is tuple and len(rows) == 1024 and len(records) == 1024,
            'The complete frozen 1024 rows and outputs are required')
    failed_values = []; failed_classes = []; max_abs = 0.0
    previous = None
    for index, ((row_id, inputs, reference), record) in enumerate(zip(rows,records)):
        require(type(row_id) is int and type(record['row_id']) is int and record['row_id'] == row_id,
                'Row missing, repeated or reordered')
        require(type(record['sequence']) is int and 0 < record['sequence'] <= 0xFFFFFFFF,
                'Invalid response sequence')
        if previous is not None: require(record['sequence'] == previous+1, 'Noncontiguous responses')
        previous = record['sequence']
        require(type(inputs) is bytes and len(inputs)==164 and record['input_hex'] == inputs.hex(),
                'Not the frozen full input')
        require(type(reference) is bytes and len(reference)==20, 'Five reference logits required')
        require(type(record['output_hex']) is str and len(record['output_hex'])==40,
                'Five output words required')
        raw = bytes.fromhex(record['output_hex'])
        actual, expected = struct.unpack('<5f',raw), struct.unpack('<5f',reference)
        require(all(math.isfinite(v) for v in actual+expected), 'Nonfinite logits')
        # Preserve the existing export_verified.compare_logits direction AND
        # FP32 NumPy arithmetic: np.allclose(reference, actual). Swapping its
        # operands or reimplementing the threshold in Python FP64 changes the
        # pre-existing numerical policy near a boundary.
        close = np.isclose(np.frombuffer(reference,dtype='<f4'),
                           np.frombuffer(raw,dtype='<f4'),atol=ATOL,rtol=RTOL)
        for column,(a,b) in enumerate(zip(actual,expected)):
            error = abs(a-b); max_abs=max(max_abs,error)
            if not close[column]:
                failed_values.append({'index':index,'row_id':row_id,'column':column,
                                      'actual':a,'reference':b,'abs_error':error})
        # Python max returns the first equal maximum, matching NumPy argmax.
        if max(range(5),key=lambda j:actual[j]) != max(range(5),key=lambda j:expected[j]):
            failed_classes.append({'index':index,'row_id':row_id})
    return {'rows':1024,'atol':ATOL,'rtol':RTOL,'max_abs_error':max_abs,
            'comparison':'numpy.isclose(reference_fp32, actual_fp32); actual is relative-tolerance anchor',
            'failed_logit_values':failed_values,'argmax_disagreements':failed_classes,
            'full_logit_parity_passed':not failed_values and not failed_classes,
            'research_measurement_accepted':False,'npu_execution_independently_verified':False,
            'latency_validated':False,'energy_measured':False}


def collect(mailbox, rows, retain_record):
    """Persist each complete result before submitting another row.

    The caller supplies the fixed bundle rows and a durable, append-only sink.
    A transport/sink error aborts: no next row, skipped row or inference retry.
    This routine performs no warmup or timing/energy aggregation.
    """
    require(type(rows) is tuple and len(rows)==1024, 'Full fixed validation subset required')
    results = []
    for row_id,inputs,_ in rows:
        record = mailbox.infer(row_id,inputs)
        retain_record(record)
        results.append(record)
    return evaluate(rows,results)
