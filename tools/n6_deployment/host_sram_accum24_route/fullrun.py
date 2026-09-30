"""SM06 fixed first-layer semantic-repair bundle. Default offline; explicit bounded RAM only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import sys

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'host_sram_runtime'
BUILD=HERE.parent/'firmware_sram_accum24_route/build_actual_01'
SOURCE_PINS={
    'run.py':'190ff04a743bb1508269ef4a52f1524b272c7ed4761b424a4e0e57cd91810f30',
    'controller.py':'15f546cbc8e74c729ec5c66458b631317db393885d02b42dcf3a17ecc5908759',
    'runtime_protocol.py':'b6c5c33565caad1a4e91f32137ef1debecc76d8197d782dcc12e78ac268955c7',
}
BUILD_PINS={
    'RESULT.json':'582163fddcd5e08836588fd4d89f7f6c45540ce0bc017c76fc9ae999d4dc73c6',
    'n6_sram.elf':'aa31c20c3f3d3078c5b5e356efaee9fae0a46dfbdf42e6262624033fdaafaec4',
}
GATE=HERE/'ACCUMULATOR_GATE.json'
GATE_SHA='2e148b3cb5a67f17ef58a73a1875d75d9b5c9d99b054c2b6c3f14354cc4255b6'
REVIEWER=HERE/'review_accumulators.py'
REVIEWER_SHA='71c5fe199c0fcdc0312707e691dc0ccf0384fecf9bd9c85eb1ec65134b058a27'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_raw_gate():
    if GATE!=GATE.resolve() or sha(GATE)!=GATE_SHA or sha(REVIEWER)!=REVIEWER_SHA:
        raise ValueError('Raw NPU evidence/reviewer gate changed')
    gate=json.loads(GATE.read_bytes())
    directory=HERE.parents[2]/'results/n6_accumulator_diagnostic_20260926_02'
    if gate['kind']!='SM06_saved_raw_NPU_gate_for_next_full_validation_only' or gate['diagnostic_directory']!=str(directory):
        raise ValueError('Wrong fixed raw diagnostic')
    if gate['allows_next_full_validation'] is not True or gate['research_measurement_accepted'] is not False:
        raise ValueError('Wrong diagnostic acceptance scope')
    if any(f!=f.resolve() or not f.is_file() for f in directory.iterdir()):raise ValueError('Nonordinary raw evidence')
    actual={f.name:sha(f) for f in directory.iterdir()}
    if actual!=gate['artifacts']:raise ValueError('Raw diagnostic artifact drift')
    spec=importlib.util.spec_from_file_location('_sm06_raw_gate_reviewer',REVIEWER)
    reviewer=importlib.util.module_from_spec(spec);spec.loader.exec_module(reviewer)
    if reviewer.review(directory)!=gate['review']:raise ValueError('Raw gate no longer reproducible')
    if sha(GATE)!=GATE_SHA or sha(REVIEWER)!=REVIEWER_SHA:raise ValueError('Raw gate changed during use')
    return gate


def frozen(name,private):
    p=BASE/name
    if p!=p.resolve() or sha(p)!=SOURCE_PINS[name]:raise ValueError('Frozen SM02 source changed: '+name)
    spec=importlib.util.spec_from_file_location(private,p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if sha(p)!=SOURCE_PINS[name]:raise ValueError('Frozen source changed during import')
    return module


def bindings():
    old=frozen('run.py','_sm06_original_launcher')
    modules,pins=old.dependencies()
    for name,digest in SOURCE_PINS.items():
        if sha(BASE/name)!=digest:raise ValueError('Source binding drift')
        pins[str(BASE/name)]=digest
    rp=frozen('runtime_protocol.py','_sm06_wire')
    # Private module's new identity only. Decoder still retains exact raw bytes,
    # same global-runtime receipt and all original wire checks. No math change.
    rp.TAG=0x534d3036
    previous=sys.modules.get('runtime_protocol')
    try:
        sys.modules['runtime_protocol']=rp
        controller=frozen('controller.py','_sm06_controller')
    finally:
        if previous is None:sys.modules.pop('runtime_protocol',None)
        else:sys.modules['runtime_protocol']=previous
    if controller.decode is not rp.decode:raise ValueError('Wrong private controller identity')
    old.BUILD=BUILD;old.BUILD_PINS=dict(BUILD_PINS)
    pins[str(HERE/'fullrun.py')]=sha(HERE/'fullrun.py')
    return old,modules,pins,controller,rp


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--execute-ram-validation',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args(argv)
    gate=verify_raw_gate()
    old,modules,pins,controller,rp=bindings()
    pins.update({str(GATE):GATE_SHA,str(REVIEWER):REVIEWER_SHA})
    firmware=old.load_variant(modules);platform=modules['stage_bundle'].load_stage()
    if any(sha(Path(n))!=d for n,d in pins.items()):raise ValueError('Source bookend failed')
    if not args.execute_ram_validation:
        print(json.dumps(dict(offline_payloads_checked=True,validation_rows=len(firmware['rows']),
            deployment_tag=hex(rp.TAG),hardware_accessed=False)));return 0
    if args.output is None:p.error('--output required')
    sink=modules['orchestrate'].Store(args.output)
    sink.json('INTENT.json',dict(kind='SM06_accumulator_preserving_full_validation',sources=pins,
        model_inputs=firmware['input_sha256'],stage_inputs=platform['input_sha256'],
        deployment_tag=rp.TAG,raw_accumulator_gate_sha256=GATE_SHA,
        power_control=False,flash_write=False,energy_measurement=False,actual_process_exit=None))
    try:
        with modules['pyocd_backend'].attach_exact_probe() as core:
            wrapped=modules['fp_entry'].EntryCore(core,sink,lambda b:rp.decode(b,modules['protocol'].decode))
            result=controller.run_connected(wrapped,firmware,platform,sink,
                nonce=secrets.randbelow(0xfffffffe)+1,modules=modules)
        if any(sha(Path(n))!=d for n,d in pins.items()):raise ValueError('Sources changed during run')
        old.load_variant(modules)
        if verify_raw_gate()!=gate:raise ValueError('Raw gate changed before final publication')
        sink.json('RESULT.json',result);print(json.dumps(result));return 0
    except BaseException as exc:
        sink.json('FAILED.json',dict(error=type(exc).__name__+': '+str(exc),
            research_measurement_accepted=False,energy_measured=False));raise


if __name__=='__main__':raise SystemExit(main())
