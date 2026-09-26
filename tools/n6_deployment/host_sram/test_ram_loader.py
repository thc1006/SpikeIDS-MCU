import unittest
from ram_loader import load_and_verify, validate_regions
from pyocd_backend import session_options, Core


class Fake:
    def __init__(self):
        self.memory = {}; self.writes = []; self.snapshots = 0
        self.short = False; self.corrupt = False; self.changed = False
    def entry_snapshot(self):
        self.snapshots += 1
        return {'pc': 1 if self.changed and self.snapshots > 1 else 0}
    def read(self,a,n):
        raw = bytes(self.memory.get(a+i, 0xA5) for i in range(n))
        if self.short: return raw[:-1]
        if self.corrupt and self.writes: return bytes(n)
        return raw
    def write(self,a,raw):
        self.writes.append((a,raw))
        self.memory.update({a+i:b for i,b in enumerate(raw)})
        return len(raw)


class LoaderTests(unittest.TestCase):
    def test_all_backup_precedes_write_and_full_readback(self):
        f = Fake(); backups = []
        regions = ((0x34064000,b'X'*4100),(0x34200000,b'Y'*30))
        def backup(a,raw):
            self.assertFalse(f.writes)
            backups.append((a,raw))
        result = load_and_verify(f,regions,backup,[])
        self.assertEqual([len(r) for a,r in backups],[4100,30])
        self.assertEqual(len(f.writes),3)
        self.assertFalse(result['target_started'])

    def test_bad_ranges_refused_before_transport(self):
        for regions in ((),((True,b'a'),),((0x71000000,b'a'),),((0x34243FFF,b'xx'),),
                        ((0x34064000,b'xx'),(0x34064001,b'y'))):
            f = Fake()
            with self.assertRaises(ValueError): load_and_verify(f,regions,lambda *a:None,[])
            self.assertEqual(f.snapshots,0)

    def test_failed_backup_no_write(self):
        f = Fake()
        def backup(*_): raise OSError('disk unavailable')
        with self.assertRaises(OSError): load_and_verify(f,((0x34064000,b'abc'),),backup,[])
        self.assertFalse(f.writes)

    def test_short_backup_or_changed_entry_no_write(self):
        for attr in ('short','changed'):
            f = Fake(); setattr(f,attr,True)
            with self.assertRaises(ValueError):
                load_and_verify(f,((0x34064000,b'abc'),),lambda *a:None,[])
            self.assertFalse(f.writes)

    def test_readback_failure_no_retry(self):
        f = Fake(); f.corrupt=True
        with self.assertRaises(ValueError):
            load_and_verify(f,((0x34064000,b'abc'),),lambda *a:None,[])
        self.assertEqual(len(f.writes),1)

    def test_backend_options_no_ambient_hooks_or_erasure(self):
        o = session_options()
        for k in ('auto_unlock','resume_on_disconnect','pack.debug_sequences.enable',
                  'cache.enable_memory','cache.enable_register','cache.read_code_from_elf'):
            self.assertIs(o[k],False)
        self.assertIs(o['no_config'],True)
        self.assertEqual(o['connect_mode'],'attach')
        self.assertTrue(o['user_script'].endswith('/empty_user_script.py'))

    def test_backend_no_mmio_flash_writes(self):
        c = Core(None)
        for address in (0x580E0000,0x08000000,0x71000000,0x34244000):
            with self.assertRaises(RuntimeError): c.write(address,b'1234')

    def test_float_policy_read_only(self):
        class Target:
            regs={0xE000ED88:0xF00000,0xE000EF34:0,0xE000EF3C:0}
            fpscr=0
            def read32(self,a): return self.regs[a]
            def read_core_register_raw(self,n):
                self_name=n
                if self_name!='fpscr': raise AssertionError(self_name)
                return self.fpscr
        target=Target();core=Core(target);core.entry_snapshot=lambda: {}
        self.assertEqual(core.floating_environment()['fpscr'],0)
        for value in (1<<22,1<<24,1<<25,1<<26,1<<19):
            target.fpscr=value
            with self.assertRaises(RuntimeError):core.floating_environment()
        target.fpscr=0;target.regs={**target.regs,0xE000EF34:1}
        with self.assertRaises(RuntimeError):core.floating_environment()


if __name__ == '__main__': unittest.main()
