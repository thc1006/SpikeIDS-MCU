"""Four no-USB lifecycle controls. Fake packages replace all pyOCD imports."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().with_name('read_probe_vref.py')
EXPECTED='d8ade05ee62c638d256124058bda316883c8e2a570eb725c054509075e19dd2d'
spec=importlib.util.spec_from_file_location('vref_under_test',SOURCE)
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)

class FakeDevice:
    serial_number=v.SERIAL
    def __init__(self,mode,source):
        self.mode=mode;self.source=source;self.is_open=False;self.calls=[];self.closes=0
    def open(self):self.is_open=True
    def transfer(self,command,*,readSize,timeout):
        self.calls.append((command,readSize,timeout))
        if self.mode=='transfer' and len(self.calls)==2:raise OSError('fake transfer failure')
        if self.mode=='missing' and len(self.calls)==3:self.source.unlink()
        return bytearray(struct.pack('<2I',1000,750))
    def close(self):
        self.closes+=1;self.is_open=False
        if self.mode=='close':raise OSError('fake close failure')

class VrefControls(unittest.TestCase):
    def invoke(self,mode):
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(),EXPECTED)
        with tempfile.TemporaryDirectory(prefix='vref_fake_only_') as td:
            packages={name:types.ModuleType(name) for name in
                      ('pyocd','pyocd.probe','pyocd.probe.stlink')}
            for mod in packages.values():mod.__path__=[]
            for leaf in ('usb','constants','stlink'):
                name='pyocd.probe.stlink.'+leaf;mod=types.ModuleType(name)
                file=Path(td)/(leaf+'.py');file.write_bytes(b'# fake no-device fixture\n')
                mod.__file__=str(file);packages[name]=mod
                setattr(packages['pyocd.probe.stlink'],leaf,mod)
            device=FakeDevice(mode,Path(td)/'usb.py')
            packages['pyocd.probe.stlink.usb'].STLinkUSBInterface=types.SimpleNamespace(
                get_all_connected_devices=lambda:[device])
            packages['pyocd.probe.stlink.constants'].Commands=types.SimpleNamespace(GET_TARGET_VOLTAGE=0xf7)
            stdout=io.StringIO();error=None
            with patch.dict(sys.modules,packages),patch.object(sys,'argv',[str(SOURCE)]),redirect_stdout(stdout):
                try:v.main()
                except BaseException as exc:error=exc
            result=json.loads(stdout.getvalue())
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(),EXPECTED)
        self.assertTrue(result['open_completed']);self.assertTrue(result['close_attempted'])
        self.assertEqual(device.closes,1)
        self.assertTrue(all(call==([0xf7],8,1000) for call in device.calls))
        for field in ('target_debug_entered','target_reset_requested','ppk_accessed',
                      'target_power_switched','calibrated_voltage_claimed','model_executed',
                      'short_reply_raw_retained_by_library'):
            self.assertIs(result[field],False)
        for sample in result['samples']:
            self.assertEqual(sample['raw_hex'],struct.pack('<2I',1000,750).hex())
            self.assertEqual(sample['reported_volts'],1.8)
            self.assertLessEqual(sample['monotonic_before_ns'],sample['monotonic_after_ns'])
        return result,error,device
    def test_success_three_exact_replies(self):
        r,e,d=self.invoke('success')
        self.assertIsNone(e);self.assertEqual(len(d.calls),3);self.assertEqual(len(r['samples']),3)
        self.assertTrue(r['source_bookend_passed']);self.assertTrue(r['close_completed'])
    def test_missing_source_still_prints_three_samples_and_fails(self):
        r,e,d=self.invoke('missing')
        self.assertIsInstance(e,RuntimeError);self.assertEqual(len(r['samples']),3)
        self.assertFalse(r['source_bookend_passed']);self.assertIn('FileNotFoundError',r['source_bookend_error'])
        self.assertTrue(r['close_completed'])
    def test_transfer_failure_retains_prior_sample_and_closes(self):
        r,e,d=self.invoke('transfer')
        self.assertIsInstance(e,OSError);self.assertEqual(len(d.calls),2);self.assertEqual(len(r['samples']),1)
        self.assertIn('fake transfer failure',r['error'])
        self.assertTrue(r['source_bookend_passed']);self.assertTrue(r['close_completed'])
    def test_close_failure_retains_all_samples_and_fails(self):
        r,e,d=self.invoke('close')
        self.assertIsInstance(e,OSError);self.assertEqual(len(r['samples']),3)
        self.assertIn('fake close failure',r['close_error'])
        self.assertFalse(r['close_completed']);self.assertTrue(r['source_bookend_passed'])

if __name__=='__main__':unittest.main()
