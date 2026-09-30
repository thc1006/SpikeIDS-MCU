"""SM03 fixed compatibility bundle. Default offline; explicit bounded RAM only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import sys

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'host_sram_runtime'
BUILD=HERE.parent/'firmware_sram_qcompat/build_actual_01'
SOURCE_PINS={
    'run.py':'190ff04a743bb1508269ef4a52f1524b272c7ed4761b424a4e0e57cd91810f30',
    'controller.py':'15f546cbc8e74c729ec5c66458b631317db393885d02b42dcf3a17ecc5908759',
    'runtime_protocol.py':'b6c5c33565caad1a4e91f32137ef1debecc76d8197d782dcc12e78ac268955c7',
}
BUILD_PINS={
    'RESULT.json':'1b27bd8e56fcdf631a1ae3ea61d113e8ff7e86c1a027870a37cad4fa2016e2be',
    'n6_sram.elf':'daca1f2ce38f8082cb2b848862d1926aa1c3ff90961d6f9267eae4b22e8abc81',
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
    old=frozen('run.py','_sm03_original_launcher')
    modules,pins=old.dependencies()
    for name,digest in SOURCE_PINS.items():
        if sha(BASE/name)!=digest:raise ValueError('Source binding drift')
        pins[str(BASE/name)]=digest
    rp=frozen('runtime_protocol.py','_sm03_wire')
    # Private module's new identity only. Decoder still retains exact raw bytes,
    # same global-runtime receipt and all original wire checks. No math change.
    rp.TAG=0x534d3033
    previous=sys.modules.get('runtime_protocol')
    try:
        sys.modules['runtime_protocol']=rp
        controller=frozen('controller.py','_sm03_controller')
    finally:
        if previous is None:sys.modules.pop('runtime_protocol',None)
        else:sys.modules['runtime_protocol']=previous
    if controller.decode is not rp.decode:raise ValueError('Wrong private controller identity')
    old.BUILD=BUILD;old.BUILD_PINS=dict(BUILD_PINS)
    pins[str(HERE/'run.py')]=sha(HERE/'run.py')
    return old,modules,pins,controller,rp


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--execute-ram-validation',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args(argv)
    old,modules,pins,controller,rp=bindings()
    firmware=old.load_variant(modules);platform=modules['stage_bundle'].load_stage()
    if any(sha(Path(n))!=d for n,d in pins.items()):raise ValueError('Source bookend failed')
    if not args.execute_ram_validation:
        print(json.dumps(dict(offline_payloads_checked=True,validation_rows=len(firmware['rows']),
            deployment_tag=hex(rp.TAG),hardware_accessed=False)));return 0
    if args.output is None:p.error('--output required')
    sink=modules['orchestrate'].Store(args.output)
    sink.json('INTENT.json',dict(kind='SM03_fixed_QDQ_compatibility_full_validation',sources=pins,
        model_inputs=firmware['input_sha256'],stage_inputs=platform['input_sha256'],
        deployment_tag=rp.TAG,power_control=False,flash_write=False,energy_measurement=False,actual_process_exit=None))
    try:
        with modules['pyocd_backend'].attach_exact_probe() as core:
            wrapped=modules['fp_entry'].EntryCore(core,sink,lambda b:rp.decode(b,modules['protocol'].decode))
            result=controller.run_connected(wrapped,firmware,platform,sink,
                nonce=secrets.randbelow(0xfffffffe)+1,modules=modules)
        if any(sha(Path(n))!=d for n,d in pins.items()):raise ValueError('Sources changed during run')
        old.load_variant(modules)
        sink.json('RESULT.json',result);print(json.dumps(result));return 0
    except BaseException as exc:
        sink.json('FAILED.json',dict(error=type(exc).__name__+': '+str(exc),
            research_measurement_accepted=False,energy_measured=False));raise


if __name__=='__main__':raise SystemExit(main())
