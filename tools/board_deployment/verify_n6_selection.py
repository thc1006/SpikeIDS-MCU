"""Read-only fixed SM06 selection gate. No flashing, USB or power operations."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'tools/board_deployment/N6_SM06_SELECTION.json'
MANIFEST_SHA = 'c70b0200ea022938da5fdd1ab8a46e2b6adb3394eae512de8f6c1e40fbc17403'
HOST = 'tools/n6_deployment/host_sram_accum24_route/'
BUILD = 'tools/n6_deployment/firmware_sram_accum24_route/build_actual_01/'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    require(path == path.resolve() and path.is_file(), 'Nonordinary file: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(root, name):
    p = Path(name)
    require(not p.is_absolute() and '..' not in p.parts and p.parts, 'Unsafe relative path')
    return root / p


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def check_pins(root, pins):
    require(type(pins) is dict and bool(pins), 'Missing pins')
    for name, digest in pins.items():
        require(sha(relative(root, name)) == digest, 'Selected artifact changed: ' + name)


def manifest():
    require(sha(MANIFEST) == MANIFEST_SHA, 'Selection manifest changed; explicit new review required')
    m = json.loads(MANIFEST.read_bytes())
    require(m['schema'] == 1 and m['kind'] == 'SM06_fixed_model_two_run_numerical_acceptance_only', 'Wrong selection kind')
    require(m['scope']['research_measurement_accepted'] is False, 'Numerical gate cannot accept energy/research')
    check_pins(ROOT, m['pins'])
    return m


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def verify():
    m = manifest()
    reviewer = module('_selected_sm06_saved', ROOT / (HOST + 'review_saved.py'))
    launcher = module('_selected_sm06_fullrun', ROOT / (HOST + 'fullrun.py'))
    raw = launcher.verify_raw_gate()
    # Offline bundle parsing revalidates the actual ELF, original model/vectors,
    # all 314 build inputs and platform profile. No attach/execute call is made.
    old, modules, source_pins, _, wire = launcher.bindings()
    bundle = old.load_variant(modules)
    modules['stage_bundle'].load_stage()
    require(wire.TAG == 0x534d3036 and len(bundle['rows']) == 1024, 'Wrong loaded bundle')
    build = json.loads((ROOT / (BUILD + 'RESULT.json')).read_bytes())
    build_pins = {BUILD + name: pin['sha256'] for name, pin in build['artifacts_before_result'].items()}
    require(len(build_pins) == 240 and len(build['input_pins']) == 314, 'Changed build inventory')
    check_pins(ROOT, build_pins)
    comparisons, nonces, reports = [], [], []
    require(len(m['runs']) == 2 and len({r['directory'] for r in m['runs']}) == 2, 'Require two distinct retained runs')
    for run in m['runs']:
        p = relative(ROOT, run['directory'])
        r = reviewer.review(p)
        inventory = r.pop('artifact_sha256')
        require(len(inventory) == run['artifact_count'] == 1060 and content_hash(inventory) == run['inventory_sha256'], 'Saved run inventory changed')
        require(r['rows'] == 1024 and r['bitwise_equal_values'] == 5120 and r['full_logit_parity_passed'] is True, 'Numerical validation failed')
        require(run['external_tool_receipt']['exit_code'] == 0, 'Missing external success receipt')
        # Receipt strings document actual tool responses; they are not a
        # cryptographic attestation. Never rewrite producer exit:null as 0.
        nonce, echo = struct.unpack_from('<II', (p / 'platform_mailbox.bin').read_bytes(), 24)
        require(0 < nonce == echo == run['platform_nonce'], 'Wrong fresh platform challenge')
        nonces.append(nonce)
        rows = []
        for i in range(1024):
            row = json.loads((p / f'row_{i:04d}.json').read_bytes())
            rows.append((row['row_id'], row['input_hex'], struct.unpack('<5I', bytes.fromhex(row['output_hex']))))
        comparisons.append(rows)
        reports.append(dict(directory=run['directory'], rows=1024, bitwise_equal_values=5120))
    require(nonces[0] != nonces[1] and comparisons[0] == comparisons[1], 'Reload repeats do not agree')
    # Bookend every selected input and every saved-run inventory after review.
    for run in m['runs']:
        require(content_hash(reviewer.inventory(relative(ROOT, run['directory']))) == run['inventory_sha256'], 'Evidence changed during review')
    check_pins(ROOT, build_pins)
    for name, digest in source_pins.items():
        require(sha(Path(name)) == digest, 'Source changed during offline bundle use')
    old.load_variant(modules)
    require(launcher.verify_raw_gate() == raw and manifest() == m, 'Bookend gate drift')
    return dict(selection_manifest_sha256=MANIFEST_SHA, selected_model='nslkdd/qcfs/primary/seed0/epoch80',
                selected_firmware='SM06', runs=reports, cross_run_output_word_matches=5120,
                fixed_1024_row_numerical_acceptance=True, energy_measured=False,
                latency_validated=False, research_measurement_accepted=False, hardware_accessed=False)


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__, allow_abbrev=False).parse_args()
    print(json.dumps(verify(), sort_keys=True, indent=2))
