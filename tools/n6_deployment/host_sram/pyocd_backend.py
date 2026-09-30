"""Explicit-attach backend. Importing this file never opens USB or a session.

The caller must establish power and review the actual deployment stage first.
An outer process deadline is required; library USB calls are not hard-real-time.
No reset/unlock/flash is invoked. Debug attach itself changes debug registers.
"""
from contextlib import contextmanager
import hashlib
from pathlib import Path

SERIAL = '004000183234510E37333934'
PACK = Path('/home/thc1006/.local/share/cmsis-pack-manager/Keil/STM32N6xx_DFP/1.2.0.pack')
PACK_SHA = 'e0ceea0fd94d62d05f186ab461f83381433c3382738bc114eab1398ca5dcbf65'
HERE = Path(__file__).resolve().parent


def require(value, message):
    if not value: raise RuntimeError(message)


def session_options():
    script = HERE/'empty_user_script.py'
    require(script.read_bytes() == b'# Intentionally empty, explicitly selected pyOCD user script. No hooks.\n',
            'Unexpected user script')
    return {'target_override':'stm32n657x0hxq', 'pack':str(PACK),
            'connect_mode':'attach', 'auto_unlock':False, 'no_config':True,
            'project_dir':str(HERE), 'user_script':str(script),
            'pack.debug_sequences.enable':False, 'resume_on_disconnect':False,
            'cache.enable_memory':False, 'cache.enable_register':False,
            'cache.read_code_from_elf':False, 'frequency':1000000,
            'dap_protocol':'swd', 'enable_swv':False}


class Core:
    def __init__(self, core): self.core = core

    def read(self, address, count):
        require(type(address) is int and type(count) is int and 0 < count <= 4096, 'Read bounds')
        return bytes(self.core.read_memory_block8(address,count))

    def write(self, address, raw):
        require(type(address) is int and type(raw) is bytes and 0 < len(raw) <= 4096, 'Write bounds')
        # Restrict memory writes to reviewed RAM, not MMIO/flash or OTP.
        from ram_loader import RAM_RANGES
        require(any(lo <= address < address+len(raw) <= hi for lo,hi in RAM_RANGES), 'Not allowed RAM')
        self.core.write_memory_block8(address,raw)
        self.core.flush()
        return len(raw)  # library completed; caller still requires real readback

    def entry_snapshot(self):
        from pyocd.core.target import Target
        require(self.core.is_halted(), 'Core must already be halted')
        secure = self.core.get_security_state()
        require(secure == Target.SecurityState.SECURE, 'Not observed in secure state')
        registers = {n:int(self.core.read_core_register_raw(n)) for n in ('control','xpsr','pc','msp','primask')}
        registers['ccr'] = self.core.read32(0xE000ED14)
        registers['cpuid'] = self.core.read32(0xE000ED00)
        registers['dscsr'] = self.core.read32(0xE000EE08)
        require(registers['control'] & 3 == 0 and registers['xpsr'] & 0x1FF == 0,
                'Not privileged MSP Thread; will not force context/security')
        require(registers['xpsr'] & (1<<24), 'Not Thumb execution state')
        require(registers['ccr'] & ((1<<16)|(1<<17)) == 0, 'CPU caches are enabled')
        require((registers['cpuid'] >> 4) & 0xFFF == 0xD22, 'Not Cortex-M55')
        require(registers['dscsr'] & (1<<16), 'Secure debug state changed')
        return registers

    def halt(self):
        # Explicit caller action, never a reset/unlock recovery fallback.
        self.core.halt()
        self.core.flush()
        require(self.core.is_halted(), 'Halt not confirmed')

    def resume_from_halt(self):
        require(self.core.is_halted(), 'Resume requires an observed halted core')
        self.core.resume()
        self.core.flush()

    def floating_environment(self):
        """Observe, do not silently change, FP32 arithmetic mode while halted.

        Call after adapter startup enabled CP10/CP11 and before platform ACK.
        A nondefault inherited environment needs a separately reviewed fix,
        not a different tolerance or an unrecorded rounding-mode write.
        """
        self.entry_snapshot()
        cpacr = self.core.read32(0xE000ED88)
        require(cpacr & 0x00F00000 == 0x00F00000, 'FPU access not enabled by adapter')
        fpccr = self.core.read32(0xE000EF34)
        fpdscr = self.core.read32(0xE000EF3C)
        fpscr = int(self.core.read_core_register_raw('fpscr'))
        require(fpccr & 1 == 0, 'Unresolved lazy FP context')
        require(fpscr & 0x07C80000 == 0 and fpdscr & 0x07C80000 == 0,
                'Nondefault FP rounding/flush/default-NaN/half mode')
        return {'cpacr':cpacr,'fpccr':fpccr,'fpdscr':fpdscr,'fpscr':fpscr,
                'arithmetic_policy':'round-nearest-even; FZ/DN/AHP/FZ16 off'}

    def start_loaded_image(self, entry, msp):
        """Caller must first load/read back the fixed ELF and retain registers.

        Starts ONLY in the two reviewed RAM image regions. It does not load
        bytes or acknowledge platform initialization, and cannot prove which
        payload was loaded. The orchestration layer owns that binding.
        """
        self.entry_snapshot()
        require(type(entry) is int and entry & 1 and
                (0x34064000 <= entry-1 < 0x340F0000 or 0x34180400 <= entry-1 < 0x34188000),
                'Entry outside reviewed RAM images')
        require(type(msp) is int and msp % 8 == 0 and msp in (0x340F8000,0x3418B000),
                'Unexpected stack top')
        require((entry < 0x34100000) == (msp == 0x340F8000), 'Image/stack mismatch')
        for name,value in (('primask',1),('msp',msp),('pc',entry)):
            self.core.write_core_register_raw(name,value)
        self.core.flush()
        require(self.core.read_core_register_raw('primask') == 1 and
                self.core.read_core_register_raw('msp') == msp and
                self.core.read_core_register_raw('pc') & ~1 == entry & ~1, 'Entry register readback mismatch')
        self.resume_from_halt()


@contextmanager
def attach_exact_probe():
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.session import Session
    require(PACK == PACK.resolve() and hashlib.sha256(PACK.read_bytes()).hexdigest() == PACK_SHA,
            'DFP changed')
    options = session_options()
    probes = [p for p in ConnectHelper.get_all_connected_probes(blocking=False)
              if p.unique_id == SERIAL]
    require(len(probes) == 1, 'Expected exactly the selected ST-LINK serial')
    session = Session(probes[0],auto_open=False,options=options)
    try:
        session.open()
        require(len(session.target.cores) == 1, 'Expected one Cortex-M55 core')
        yield Core(next(iter(session.target.cores.values())))
    finally:
        session.close()  # no auto-resume; no reset/flash/recovery fallback
