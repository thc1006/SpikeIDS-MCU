"""Offline selection-gate adversarial checks; original evidence is never edited."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location('selection_test', HERE / 'verify_n6_selection.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_real_fixed_selection_is_read_only_numerical_only(gate):
    r = gate.verify()
    assert r['selected_firmware'] == 'SM06' and r['cross_run_output_word_matches'] == 5120
    assert r['fixed_1024_row_numerical_acceptance']
    assert not any(r[k] for k in ('hardware_accessed', 'energy_measured', 'latency_validated', 'research_measurement_accepted'))


@pytest.mark.parametrize('bad', ['firmware', 'seed', 'power', 'run', 'checksum', 'malformed', 'symlink'])
def test_manifest_cannot_silently_reselect(gate, tmp_path, bad):
    original = gate.MANIFEST
    p = tmp_path / 'selection.json'
    if bad == 'symlink':
        p.symlink_to(original)
    elif bad == 'malformed':
        p.write_bytes(b'{broken')
    else:
        m = json.loads(original.read_bytes())
        if bad == 'firmware': m['scope']['deployment_tag'] = 'SM05'
        if bad == 'seed': m['model']['seed'] = 1
        if bad == 'power': m['scope']['energy_measured'] = True
        if bad == 'run': m['runs'][1] = m['runs'][0]
        if bad == 'checksum': m['runs'][0]['inventory_sha256'] = '0'*64
        p.write_text(json.dumps(m))
    gate.MANIFEST = p
    with pytest.raises(ValueError): gate.manifest()


@pytest.mark.parametrize('bad', ['changed', 'missing', 'symlink', 'empty', 'traversal', 'absolute'])
def test_source_pins_fail_closed(gate, tmp_path, bad):
    p = tmp_path / 'model'; p.write_bytes(b'correct'); digest = gate.sha(p)
    pins = {'model': digest}
    if bad == 'changed': p.write_bytes(b'wrong')
    if bad == 'missing': p.unlink()
    if bad == 'symlink': (tmp_path/'alias').symlink_to(p); pins = {'alias': digest}
    if bad == 'empty': pins = {}
    if bad == 'traversal': pins = {'../model': digest}
    if bad == 'absolute': pins = {str(p): digest}
    with pytest.raises(ValueError): gate.check_pins(tmp_path, pins)


def test_no_execution_or_power_cli(gate):
    for flag in ('--execute', '--execute-ram-validation', '--power', '--model'):
        r = subprocess.run([sys.executable, str(HERE/'verify_n6_selection.py'), flag], capture_output=True)
        assert r.returncode == 2 and b'unrecognized arguments' in r.stderr
