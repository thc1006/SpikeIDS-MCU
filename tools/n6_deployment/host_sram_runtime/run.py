"""Explicit new runtime-initialized SRAM validation. Default is offline only."""
import argparse
import hashlib
import importlib.util
import importlib
import json
from pathlib import Path
import secrets
import sys

HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'host_sram'
FP=HERE.parent/'host_sram_fp'
BUILD=HERE.parent/'firmware_sram_runtime/build_actual_01'
# Actual cross-build 3e7242 / f659d6, exit 0; fixed reviewed build, not latest.
BUILD_PINS={
    'RESULT.json':'2f7571ef7f878da5d710c949dd590593b1308321c0a83934f62c4930dc50e5fd',
    'n6_sram.elf':'bf2671fbf5c63ceec5e2b154be6b718dd24e74673bf7dc61a0bf0e0423539556',
}


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def dependencies():
    expected={'run.py':'20a6e45afc01731eb02983f2a3ff8a7af01b524b54f46dd349279d0424c13371',
              'fp_entry.py':'60178340e307a55b3c9a4c88440828694092f4ccd27a7ac1c53fc3c725db1403'}
    for name,digest in expected.items():
        if (FP/name)!=(FP/name).resolve() or sha(FP/name)!=digest:
            raise ValueError('Frozen FP source changed')
    spec=importlib.util.spec_from_file_location('_frozen_fp_launcher',FP/'run.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    pins=old.sources()
    sys.path.insert(0,str(FP));sys.path.insert(0,str(OLD))
    modules={}
    for name in ('bundle','ram_loader','protocol','validation','stage_protocol','stage_bundle','orchestrate','pyocd_backend','fp_entry'):
        module=importlib.import_module(name)
        root=FP if name=='fp_entry' else OLD
        if Path(module.__file__).resolve()!=root/(name+'.py'): raise ValueError('Unexpected module: '+name)
        modules[name]=module
    for name in ('run.py','runtime_protocol.py','controller.py'):
        path=HERE/name
        if path!=path.resolve(): raise ValueError('Noncanonical new source')
        pins[str(path)]=sha(path)
    return modules,pins


def load_variant(modules):
    if set(BUILD_PINS)!={'RESULT.json','n6_sram.elf'}:
        raise ValueError('New build has not been pinned after review')
    for name,digest in BUILD_PINS.items():
        path=BUILD/name
        if path!=path.resolve() or sha(path)!=digest: raise ValueError('New artifact changed')
    report=json.loads((BUILD/'RESULT.json').read_text())
    if report['arm_compile_link_succeeded'] is not True or len(report['calls'])!=63:
        raise ValueError('Unexpected new build')
    if any(type(c['actual_return_code']) is not int or c['actual_return_code']!=0 for c in report['calls']):
        raise ValueError('Build failure')
    for path,pin in report['input_pins'].items():
        if sha(Path(path))!=pin['sha256']: raise ValueError('Build input changed: '+path)
    old=modules['bundle'].load_bundle()
    entry,msp,segments=modules['bundle'].elf_segments((BUILD/'n6_sram.elf').read_bytes())
    old.update(entry=entry,msp=msp,segments=tuple(segments)+old['segments'][-2:])
    old['input_sha256'].update({str(BUILD/n):d for n,d in BUILD_PINS.items()})
    return old


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--execute-ram-validation',action='store_true')
    p.add_argument('--output',type=Path)
    args=p.parse_args(argv)
    modules,pins=dependencies()
    firmware=load_variant(modules);platform=modules['stage_bundle'].load_stage()
    if any(sha(Path(n))!=d for n,d in pins.items()): raise ValueError('Source changed before use')
    if not args.execute_ram_validation:
        print(json.dumps(dict(offline_payloads_checked=True,validation_rows=len(firmware['rows']),hardware_accessed=False)))
        return 0
    if args.output is None:p.error('--output required for execution')
    # New module providers are checked too; default invocation never imports a USB backend library.
    import controller,runtime_protocol
    for module in (controller,runtime_protocol):
        if Path(module.__file__).resolve()!=HERE/(module.__name__+'.py'): raise ValueError('Wrong controller provider')
    sink=modules['orchestrate'].Store(args.output)
    sink.json('INTENT.json',dict(kind='SM02_runtime_initialized_full_validation',sources=pins,
        model_inputs=firmware['input_sha256'],stage_inputs=platform['input_sha256'],
        power_control=False,flash_write=False,energy_measurement=False,actual_process_exit=None))
    try:
        with modules['pyocd_backend'].attach_exact_probe() as core:
            wrapped=modules['fp_entry'].EntryCore(core,sink,
                lambda raw:runtime_protocol.decode(raw,modules['protocol'].decode))
            result=controller.run_connected(wrapped,firmware,platform,sink,
                nonce=secrets.randbelow(0xfffffffe)+1,modules=modules)
        if any(sha(Path(n))!=d for n,d in pins.items()): raise ValueError('Source changed during execution')
        load_variant(modules)  # artifact/input bookend before successful publication
        sink.json('RESULT.json',result);print(json.dumps(result,sort_keys=True));return 0
    except BaseException as exc:
        sink.json('FAILED.json',dict(error=type(exc).__name__+': '+str(exc),
            research_measurement_accepted=False,energy_measured=False))
        raise


if __name__=='__main__':raise SystemExit(main())
