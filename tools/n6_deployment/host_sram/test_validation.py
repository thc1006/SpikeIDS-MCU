import copy
import struct
import unittest
import numpy as np
from validation import evaluate, collect


def fixture():
    ref=struct.pack('<5f',1,2,3,4,5)
    rows=tuple((i,bytes(164),ref) for i in range(1024))
    records=[{'row_id':i,'sequence':i+1,'input_hex':bytes(164).hex(),'output_hex':ref.hex()} for i in range(1024)]
    return rows,records


class ValidationTests(unittest.TestCase):
    def test_complete_control(self):
        rows,records=fixture(); r=evaluate(rows,records)
        self.assertTrue(r['full_logit_parity_passed']); self.assertFalse(r['energy_measured'])

    def test_incorrect_nonwinning_logit_is_not_argmax_pass(self):
        rows,records=fixture(); records[1023]['output_hex']=struct.pack('<5f',1.01,2,3,4,5).hex()
        r=evaluate(rows,records)
        self.assertFalse(r['full_logit_parity_passed']); self.assertFalse(r['argmax_disagreements'])
        self.assertEqual(r['failed_logit_values'][0]['index'],1023)

    def test_missing_reordered_mismatched_or_nonfinite_refused(self):
        rows,original=fixture()
        cases=[original[:-1], original[::-1]]
        for key,value in [('sequence',True),('row_id',False),('sequence',10),
                          ('input_hex','00'*164+'00'),('output_hex',struct.pack('<5f',float('nan'),2,3,4,5).hex())]:
            records=copy.deepcopy(original);records[2][key]=value;cases.append(records)
        for records in cases:
            with self.subTest():
                with self.assertRaises(ValueError): evaluate(rows,records)

    def test_persistence_failure_stops_before_next_row(self):
        rows,records=fixture()
        class Mail:
            count=0
            def infer(self,*args): self.count+=1;return records[self.count-1]
        mail=Mail()
        def retain(_): raise OSError('full disk')
        with self.assertRaises(OSError): collect(mail,rows,retain)
        self.assertEqual(mail.count,1)

    def test_exact_existing_numpy_direction_and_fp32_boundary(self):
        rows,records=fixture()
        expected=np.array([1,2,3,4,5],dtype=np.float32)
        for delta in np.linspace(0.999e-5,1.101e-5,31):
            actual=expected.copy();actual[0]+=np.float32(delta)
            records[0]['output_hex']=actual.tobytes().hex()
            self.assertEqual(evaluate(rows,records)['full_logit_parity_passed'],
                             bool(np.allclose(expected,actual,atol=1e-6,rtol=1e-5)))


if __name__ == '__main__': unittest.main()
