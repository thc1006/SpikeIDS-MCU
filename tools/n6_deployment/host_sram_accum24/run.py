"""SM05 fixed accumulator candidate. Default offline; explicit INIT-ONLY RAM diagnostic."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import sys

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'host_sram_runtime'
BUILD=HERE.parent/'firmware_sram_accum24/build_actual_01'
SOURCE_PINS={
    'run.py':'190ff04a743bb1508269ef4a52f1524b272c7ed4761b424a4e0e57cd91810f30',
    'controller.py':'15f546cbc8e74c729ec5c66458b631317db393885d02b42dcf3a17ecc5908759',
    'runtime_protocol.py':'b6c5c33565caad1a4e91f32137ef1debecc76d8197d782dcc12e78ac268955c7',
}
BUILD_PINS={
    'RESULT.json':'0d3b0707373cd907ba68f88bac5625648bedea8021ef85575dc10d74c6edb9ae',
    'n6_sram.elf':'f40c71597030f02fc2090316c950759de3c6fc028243304e173d05ffbc4b6043',
}


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def frozen(name,private):
    p=BASE/name
    if p!=p.resolve() or sha(p)!=SOURCE_PINS[name]:raise ValueError('Frozen SM02 source changed: '+name)
    spec=importlib.util.spec_from_file_location(private,p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if sha(p)!=SOURCE_PINS[name]:raise ValueError('Frozen source changed during import')
    return module


def bindings():
    old=frozen('run.py','_sm05_original_launcher')
    modules,pins=old.dependencies()
    for name,digest in SOURCE_PINS.items():
        if sha(BASE/name)!=digest:raise ValueError('Source binding drift')
        pins[str(BASE/name)]=digest
    rp=frozen('runtime_protocol.py','_sm05_wire')
    # Private module's new identity only. Decoder still retains exact raw bytes,
    # same global-runtime receipt and all original wire checks. No math change.
    rp.TAG=0x534d3035
    previous=sys.modules.get('runtime_protocol')
    try:
        sys.modules['runtime_protocol']=rp
        controller=frozen('controller.py','_sm05_controller')
    finally:
        if previous is None:sys.modules.pop('runtime_protocol',None)
        else:sys.modules['runtime_protocol']=previous
    if controller.decode is not rp.decode:raise ValueError('Wrong private controller identity')
    old.BUILD=BUILD;old.BUILD_PINS=dict(BUILD_PINS)
    pins[str(HERE/'run.py')]=sha(HERE/'run.py')
    return old,modules,pins,controller,rp


class InitializationReady(Exception):
    """Intentional stop before ANY inference, not a parity pass."""


def initialize_only(core,firmware,platform,sink,*,nonce,modules,controller):
    from types import SimpleNamespace
    def stop_before_collect(mailbox,rows,retain):
        core.halt()
        raw,words=mailbox.snapshot()
        if words[3]!=3 or words[5:7]!=(0,0) or len(rows)!=1024:
            raise ValueError('Not pristine READY with original complete vector bundle')
        sink.raw('diagnostic_ready.bin',raw)
        raise InitializationReady()
    # Private adapter only: the immutable full evaluator stays unchanged and
    # is not called/claimed. Existing init/FP/MMIO gates and finally cleanup run.
    local=dict(modules)
    local['validation']=SimpleNamespace(**vars(modules['validation']))
    local['validation'].collect=stop_before_collect
    try:
        controller.run_connected(core,firmware,platform,sink,nonce=nonce,modules=local)
    except InitializationReady:
        return dict(initialization_ready=True,completed_rows=0,inference_executed=False,
            full_logit_parity_passed=False,energy_measured=False,research_measurement_accepted=False)
    raise RuntimeError('Init-only mode unexpectedly returned a full inference result')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--execute-init-diagnostic',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args(argv)
    old,m,pins,controller,rp=bindings();f=old.load_variant(m);platform=m['stage_bundle'].load_stage()
    if any(sha(Path(n))!=d for n,d in pins.items()):raise ValueError('Source bookend failed')
    if not args.execute_init_diagnostic:
        print(json.dumps(dict(offline_payloads_checked=True,validation_rows=len(f['rows']),
            deployment_tag=hex(rp.TAG),hardware_accessed=False,init_only=True)));return 0
    if args.output is None:p.error('--output required')
    sink=m['orchestrate'].Store(args.output)
    sink.json('INTENT.json',dict(kind='SM05_INIT_ONLY_not_inference_or_acceptance',sources=pins,
        model_inputs=f['input_sha256'],stage_inputs=platform['input_sha256'],deployment_tag=rp.TAG,
        power_control=False,flash_write=False,energy_measurement=False,actual_process_exit=None))
    try:
        with m['pyocd_backend'].attach_exact_probe() as core:
            wrapped=m['fp_entry'].EntryCore(core,sink,lambda b:rp.decode(b,m['protocol'].decode))
            result=initialize_only(wrapped,f,platform,sink,nonce=secrets.randbelow(0xfffffffe)+1,modules=m,controller=controller)
        if any(sha(Path(n))!=d for n,d in pins.items()):raise ValueError('Sources changed')
        old.load_variant(m)
        sink.json('INIT_READY.json',result);print(json.dumps(result));return 0
    except BaseException as exc:
        sink.json('FAILED.json',dict(error=type(exc).__name__+': '+str(exc),research_measurement_accepted=False,energy_measured=False));raise


if __name__=='__main__':raise SystemExit(main())
