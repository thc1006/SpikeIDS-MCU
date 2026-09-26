"""Frozen S6 controller with explicit, retained pre-ACK RMode initialization.

Default offline only. Existing controller, ELF, weights and tolerance unchanged.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import secrets
import sys

HERE = Path(__file__).resolve().parent
LEGACY = HERE.parent / 'host_sram'
LEGACY_PINS = {
    'bundle.py': 'd83e032d018c564936d30016c2f26e2933f71ce45b9595f536da73f44ca6a423',
    'empty_user_script.py': 'e37f0c329b40ee23e5f014079276ac040d517be8981fe6101a809a0b005f6480',
    'orchestrate.py': '2d2328bc8d46c762910d628a8d1c65d0c7b8e296c332ec4eccc6b07f538e1f93',
    'protocol.py': '78b25d2622774d77b7241c943f884bd1cadb1517657246d398e2702785afe50e',
    'pyocd_backend.py': 'ccea760c695766a23c9b9d8180f7d53b4ab33d0de266ba6817613b02fe004a5d',
    'ram_loader.py': '847e1cb3f0c876f2cd0a5dcdf7433c859e2f353538c2b7f2806802752a9ff950',
    'stage_bundle.py': 'b1eefbe71b122efe4393ddd42e1d54a75acaba9b20cbaf2fbed04b9a80e1a6f9',
    'stage_protocol.py': '9c0b472eefc04a19048baa0964359779ac77304501b95e9ebd8c61407c0412c5',
    'validation.py': '684068f35b9c55d4fec967fcb5e8fc7d34d3af5b729f361e722452cd39947f75',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    result = {}
    for name, expected in LEGACY_PINS.items():
        path = LEGACY / name
        if path != path.resolve() or digest(path) != expected:
            raise ValueError('Frozen host source changed: ' + str(path))
        result[str(path)] = expected
    for name in ('run.py', 'fp_entry.py'):
        path = HERE / name
        if path != path.resolve():
            raise ValueError('Noncanonical new source')
        result[str(path)] = digest(path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--execute-ram-validation-with-rne-entry', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    pins = sources()  # before any legacy module import or USB enumeration
    sys.path.insert(0, str(LEGACY))
    for name in ('bundle', 'protocol', 'ram_loader', 'validation', 'stage_protocol',
                 'stage_bundle', 'orchestrate', 'pyocd_backend'):
        module = importlib.import_module(name)
        if Path(module.__file__).resolve() != LEGACY / (name + '.py'):
            raise ValueError('Unexpected module provider: ' + name)
    from bundle import load_bundle
    from stage_bundle import load_stage
    from orchestrate import Store, run_connected
    from protocol import decode
    from pyocd_backend import attach_exact_probe
    import fp_entry
    if Path(fp_entry.__file__).resolve() != HERE / 'fp_entry.py':
        raise ValueError('Unexpected FP entry module provider')
    EntryCore = fp_entry.EntryCore
    firmware, platform = load_bundle(), load_stage()
    if sources() != pins:
        raise ValueError('Source changed in offline preflight')
    if not args.execute_ram_validation_with_rne_entry:
        print(json.dumps(dict(offline_payloads_checked=True, validation_rows=len(firmware['rows']),
                              hardware_accessed=False, fp_entry_policy='explicit pre-ACK RMode only')))
        return 0
    if args.output is None:
        parser.error('--output required for execution')
    sink = Store(args.output)
    sink.json('INTENT.json', dict(kind='sram_fixed_vector_validation_explicit_rne_entry',
        sources=pins, model_inputs=firmware['input_sha256'], stage_inputs=platform['input_sha256'],
        power_control=False, flash_write=False, fp_write_policy='FPSCR[23:22] only before ACK',
        energy_measurement=False, actual_process_exit=None))
    try:
        with attach_exact_probe() as core:
            result = run_connected(EntryCore(core, sink, decode), firmware, platform,
                                   sink, nonce=secrets.randbelow(0xFFFFFFFE) + 1)
        if sources() != pins:
            raise RuntimeError('Source changed during hardware execution')
        result['fp_entry_policy'] = 'explicit retained pre-ACK FPSCR RMode initialization'
        sink.json('RESULT.json', result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except BaseException as exc:
        sink.json('FAILED.json', dict(error=type(exc).__name__ + ': ' + str(exc),
                  research_measurement_accepted=False, energy_measured=False))
        raise


if __name__ == '__main__':
    raise SystemExit(main())
