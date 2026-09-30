"""Single-session SRAM initialization, payload readback and full-row validation.

Hardware operation is explicit. This does NOT switch PPK power, flash, reset
the MCU, erase, unlock, or accept energy/latency/NPU profiling results. Its fixed
stage DOES configure clocks/SRAM/NPU attribution and reset NPU/CACHEAXI.
The power source and physical wiring remain external prerequisites. Run under
an outer process deadline; a host timeout cannot prove the NPU has stopped.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import time

from bundle import load_bundle, REPO
from protocol import Mailbox, MAGIC, ADDRESS, ACK, decode
from ram_loader import load_and_verify
import stage_protocol as stage
from validation import collect


class Store:
    def __init__(self,path):
        path=Path(path)
        if not path.is_absolute() or path!=path.resolve() or not path.is_relative_to(REPO/'results'):
            raise ValueError('Fresh absolute results/ directory required')
        path.mkdir(mode=0o700,parents=False,exist_ok=False)
        self.path=path

    def raw(self,name,payload):
        if Path(name).name!=name: raise ValueError('Flat output filename required')
        with (self.path/name).open('xb') as stream:
            stream.write(payload);stream.flush();os.fsync(stream.fileno())

    def json(self,name,value):
        self.raw(name,(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())


def wait_header(core,address,magic,size,expected,*,seconds=10,clock=time.monotonic,sleep=time.sleep):
    start=clock()
    for _ in range(10000):
        if clock()-start>=seconds: raise TimeoutError('Firmware header deadline')
        raw=core.read(address,16)
        if type(raw) is not bytes or len(raw)!=16: raise ValueError('Short firmware header')
        if clock()-start>=seconds: raise TimeoutError('Header read crossed deadline')
        m,v,n,state=struct.unpack('<4I',raw)
        if m==magic:
            if (v,n)!=(1,size): raise ValueError('Wrong firmware header ABI')
            if state==expected: return raw
            if (magic==stage.MAGIC and state in (3,4)) or (magic==MAGIC and state in (6,7)):
                raise ValueError('Firmware rejected initialization or faulted')
        elif m!=0: raise ValueError('Unexpected image present')
        sleep(0.002)
    raise TimeoutError('Header poll budget')


def run_connected(core,firmware,platform,sink,*,nonce):
    """Dependency-injected engine; production inputs come from fixed bundles.

    All persistent output paths are absolute before pyOCD changes cwd. The
    finally path attempts an explicit halt, not automatic reset or inference
    retry. It cannot stop independent bus masters or disconnect DUT power.
    """
    events=[];mail_events=[];completed=[]
    try:
        core.halt()
        initial=core.entry_snapshot();sink.json('initial_registers.json',initial)
        sink.json('platform_load.json',load_and_verify(core,platform['segments'],
            lambda a,b:sink.raw(f'backup_stage_{a:08x}.bin',b),events))
        core.start_loaded_image(platform['entry'],platform['msp'])
        wait_header(core,stage.ADDRESS,stage.MAGIC,stage.SIZE,2)
        initialized=stage.challenge(core.read,core.write,nonce)
        sink.raw('platform_mailbox.bin',initialized['raw'])
        core.halt()
        sink.json('platform_live_before_payload.json',stage.live_register_check(core.read,initialized))
        sink.json('model_load.json',load_and_verify(core,firmware['segments'],
            lambda a,b:sink.raw(f'backup_model_{a:08x}.bin',b),events))
        # Loading the model must not change platform MMIO or imply acceptance.
        sink.json('platform_live_after_payload.json',stage.live_register_check(core.read,initialized))
        core.start_loaded_image(firmware['entry'],firmware['msp'])
        wait_header(core,ADDRESS,MAGIC,512,1)
        core.halt()
        mailbox=Mailbox(core.read,core.write,events=mail_events)
        raw,words=mailbox.snapshot()
        if words[3]!=1 or words[4:7]!=(0,0,0): raise ValueError('Adapter not in fresh WAIT_PLATFORM')
        sink.raw('adapter_wait_platform.bin',raw)
        sink.json('floating_environment.json',core.floating_environment())
        sink.json('platform_live_before_ack.json',stage.live_register_check(core.read,initialized))
        # Token is only an acknowledgement of this session's observed checks,
        # not a caller's assertion that the hardware is physically attested.
        n=core.write(ADDRESS+16,struct.pack('<I',ACK))
        if type(n) is not int or n!=4 or core.read(ADDRESS+16,4)!=struct.pack('<I',ACK):
            raise ValueError('Platform acknowledgement write/readback failed')
        core.resume_from_halt()
        wait_header(core,ADDRESS,MAGIC,512,3)
        def retain(record):
            sink.json(f'row_{len(completed):04d}.json',record)
            completed.append(record['row_id'])
        parity=collect(mailbox,firmware['rows'],retain)
        sink.json('PARITY.json',parity)
        if not parity['full_logit_parity_passed']: raise ValueError('Full-logit parity failed; original tolerance retained')
        core.halt()
        sink.json('floating_environment_after_validation.json',core.floating_environment())
        sink.json('platform_live_after_validation.json',stage.live_register_check(core.read,initialized))
        return {'full_logit_parity_passed':True,'completed_rows':len(completed),
                'actual_process_exit':None,'nominal_cpu_npu_hz':initialized['nominal_cpu_npu_hz'],
                'frequency_measured':False,'npu_execution_independently_verified':False,
                'latency_validated':False,'energy_measured':False,'research_measurement_accepted':False}
    finally:
        # Retain failures too. No successful report is written if cleanup fails.
        cleanup_error=None
        try:core.halt()
        except BaseException as exc:cleanup_error=type(exc).__name__+': '+str(exc)
        sink.json('load_events.json',events)
        sink.json('mailbox_events.json',mail_events)
        sink.json('completion_state.json',{'completed_row_ids':completed,'halt_error':cleanup_error,
                  'power_was_not_switched':True,'npu_quiescence_verified':False})
        if cleanup_error is not None: raise RuntimeError('Cleanup halt failed: '+cleanup_error)


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--execute-ram-validation',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    # No USB enumeration/import until both fixed payloads pass offline checks.
    from stage_bundle import load_stage
    firmware,platform=load_bundle(),load_stage()
    if not args.execute_ram_validation:
        print(json.dumps({'offline_payloads_checked':True,'validation_rows':len(firmware['rows']),
                          'hardware_accessed':False}));return 0
    if args.output is None: parser.error('--output is required for hardware execution')
    sink=Store(args.output)
    sources={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest()
             for p in Path(__file__).resolve().parent.glob('*.py')}
    sink.json('INTENT.json',{'kind':'sram_fixed_vector_validation','sources':sources,
                           'model_inputs':firmware['input_sha256'],'stage_inputs':platform['input_sha256'],
                           'power_control':False,'energy_measurement':False,'actual_process_exit':None})
    try:
        from pyocd_backend import attach_exact_probe
        with attach_exact_probe() as core:
            result=run_connected(core,firmware,platform,sink,nonce=secrets.randbelow(0xFFFFFFFE)+1)
        for path,sha in sources.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise RuntimeError('Collector source changed')
        sink.json('RESULT.json',result)
        print(json.dumps(result,sort_keys=True));return 0
    except BaseException as exc:
        sink.json('FAILED.json',{'error':type(exc).__name__+': '+str(exc),
                               'research_measurement_accepted':False,'energy_measured':False})
        raise


if __name__=='__main__':raise SystemExit(main())
