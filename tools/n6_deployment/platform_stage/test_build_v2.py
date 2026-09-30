"""Finite installed-tool pin tests; synthetic ordinary files, no compiler run."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import build_v2 as b

raw=b.VENDOR.read_bytes()
if hashlib.sha256(raw).hexdigest()!=b.VENDOR_SHA:raise RuntimeError('held writer changed')
spec=importlib.util.spec_from_file_location('_test_v2_held',b.VENDOR)
v=importlib.util.module_from_spec(spec);exec(compile(raw,str(b.VENDOR),'exec'),v.__dict__)

class ToolPinTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='stage-toolpin-')
        self.root=Path(self.tmp.name);self.path=self.root/'tool'
        with self.path.open('xb') as f:f.write(b'fixed toy tool bytes')
    def tearDown(self):self.tmp.cleanup()
    def test_hardlink_identity_preserved(self):
        os.link(self.path,self.root/'alias');pin=b.tool_snapshot(v,self.path)
        self.assertEqual(pin['links'],2);self.assertEqual(pin,b.tool_snapshot(v,self.path))
        self.assertEqual(pin['sha256'],hashlib.sha256(b'fixed toy tool bytes').hexdigest())
        with self.assertRaises(Exception):v.snapshot(self.path)
    def test_symlink_refused(self):
        p=self.root/'symbolic';p.symlink_to(self.path)
        with self.assertRaises(Exception):b.tool_snapshot(v,p)
    def test_directory_refused(self):
        with self.assertRaises(Exception):b.tool_snapshot(v,self.root)
    def test_link_count_change_is_not_same_pin(self):
        pin=b.tool_snapshot(v,self.path);os.link(self.path,self.root/'newalias')
        self.assertNotEqual(pin,b.tool_snapshot(v,self.path))
    def test_during_read_change_refused(self):
        original=os.read;changed=False
        def mutate(fd,n):
            nonlocal changed
            answer=original(fd,n)
            if not changed:
                changed=True
                with self.path.open('ab') as f:f.write(b'late')
            return answer
        with mock.patch.object(b.os,'read',mutate):
            with self.assertRaises(Exception):b.tool_snapshot(v,self.path)
    def test_same_bytes_path_replacement_refused(self):
        original=os.read;changed=False
        def replace(fd,n):
            nonlocal changed
            answer=original(fd,n)
            if not changed:
                changed=True;self.path.rename(self.root/'original')
                with self.path.open('xb') as f:f.write(b'fixed toy tool bytes')
            return answer
        with mock.patch.object(b.os,'read',replace):
            with self.assertRaises(Exception):b.tool_snapshot(v,self.path)

if __name__=='__main__':unittest.main(verbosity=2)
