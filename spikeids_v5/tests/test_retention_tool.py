"""Opaque-byte retention fixtures; these are NOT scientifically valid models."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import v5_retention as retention


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    result = retention._seal(value)
    path.write_text(json.dumps(result, sort_keys=True) + '\n')
    return result


def _bytes(path, value=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if value is not None else path.as_posix().encode())
    return _sha(path)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_neural(root, plan):
    """Return independent fields for caller to merge with other gate evidence."""
    independent = {'passed': True, 'plan_sha256': plan['content_sha256'],
                   'checkpoints_checked': 440, 'prediction_artifacts_checked': 440,
                   'executions_checked': 22, 'checkpoints': {}}
    for dataset, model in retention.JOBS:
        job = f'{dataset}_{model}'
        independent['checkpoints'][job] = {}
        for execution in ('results', 'replicas'):
            stem = root / execution / job
            rows = []
            checked = independent['checkpoints'][job][execution] = {}
            for seed in range(20):
                cp = stem / 'runs' / f'{model}_seed_{seed}.pt'
                npz = stem / 'runs' / f'{model}_seed_{seed}_predictions.npz'
                cp_sha = _bytes(cp); npz_sha = _bytes(npz)
                checked[str(seed)] = {'path': cp.relative_to(root).as_posix(), 'artifact_sha256': cp_sha}
                rows.append({'seed': seed, 'artifact': {'filename': npz.name, 'sha256': npz_sha}})
            _write(stem.with_suffix('.json'), {'status': 'complete', 'dataset': dataset,
                   'kind': model, 'formal': {'plan_sha256': plan['content_sha256']}, 'per_seed': rows})
            for name in ('manifest.json', 'fit_manifest.json', 'fit_evidence.json'):
                _write(stem / name, {'opaque_retention_fixture': True})
    return independent


def fill_tree(root, plan):
    independent = {'passed': True, 'tree_plan_sha256': plan['content_sha256'], 'models': {}}
    for dataset in ('nslkdd', 'unsw'):
        independent['models'][dataset] = {}
        for kind in ('random_forest', 'xgboost'):
            target = independent['models'][dataset][kind] = {}
            for seed in range(20) if kind == 'random_forest' else [0]:
                target[str(seed)] = {}
                for execution in ('primary', 'replica'):
                    stem = root / execution / dataset / kind / f'seed_{seed}'
                    model = stem.with_suffix('.joblib'); _bytes(model)
                    _write(stem.with_suffix('.json'), {'opaque_retention_fixture': True})
                    _write(stem.with_suffix('.ledger.json'), {'opaque_retention_fixture': True})
                    target[str(seed)][execution] = {
                        'artifact': model.relative_to(root).as_posix(), 'artifact_sha256': _sha(model),
                        'record_sha256': _sha(stem.with_suffix('.json')),
                        'execution_ledger_sha256': _sha(stem.with_suffix('.ledger.json'))}
        _bytes(root / 'onnx' / f'rf_{dataset}_seed_0.onnx')
    return independent


def fill_exports(root, plan):
    summary = {'source_plan_sha256': plan['source_plan_sha256'],
               'export_plan_sha256': plan['content_sha256'], 'attempts': []}
    for dataset, model in retention.JOBS:
        for mode in ('fp32', 'qdq'):
            stem = root / dataset / model / mode
            names = {'export_report.json', 'export_policy.json', 'validation_vectors.npz',
                     'preprocessing.json', 'calibration_rows.json', 'model_fp32.onnx'}
            if mode == 'qdq': names.add('model_qdq_int8.onnx')
            payload = {name: _bytes(stem / name) for name in sorted(names)}
            evidence = stem / 'runner_validation.json'
            _write(evidence, {'export_plan_sha256': plan['content_sha256'], 'output_files_sha256': payload})
            log = root / 'logs' / f'{dataset}_{model}_{mode}.log'; _bytes(log)
            summary['attempts'].append({
                'dataset': dataset, 'model': model, 'mode': mode, 'passed': True,
                'output_dir': stem.relative_to(root).as_posix(),
                'evidence': evidence.relative_to(root).as_posix(), 'evidence_sha256': _sha(evidence),
                'log': log.relative_to(root).as_posix(), 'log_sha256': _sha(log)})
    return summary


def populate_fixture(base):
    roots = {role: base / role for role in retention.ROLES}
    for root in roots.values(): root.mkdir(parents=True)
    neural = _write(roots['neural'] / 'plan.json', {
        'schema': 5, 'protocol_role': 'planned_benchmark', 'seeds': list(range(20)),
        'deployment_seed': 0, 'jobs': [
            {'id': f'{d}_{m}', 'dataset': d, 'model': m, 'hyperparameters': {'seeds': list(range(20))}}
            for d, m in retention.JOBS]})
    binding = {'content_sha256': neural['content_sha256'], 'sha256': _sha(roots['neural'] / 'plan.json')}
    tree = _write(roots['tree'] / 'plan.json', {
        'kind': 'tree_baseline_plan', 'random_forest_seeds': list(range(20)),
        'xgboost_seeds': [0], 'datasets': {'nslkdd': {}, 'unsw': {}}, 'neural_plan': binding})
    export = _write(roots['exports'] / 'export_plan.json', {
        'kind': 'spikeids_v5_export_plan', 'source_plan': binding,
        'source_plan_sha256': neural['content_sha256'],
        'attempts': [{'dataset': d, 'model': m, 'mode': mode}
                     for d, m in retention.JOBS for mode in ('fp32', 'qdq')]})
    identities = dict(zip(retention.ROLES, (p['content_sha256'] for p in (neural, tree, export))))
    for name in ('environment.json', 'verification_fit.json', 'verification_evaluate.json',
                 'stats_report_globecom.json', 'equivalence_v5.json', 'equivalence_v5.md',
                 'paper_numeric_check.json', 'export_registration.json', 'export_prior_exposure.json',
                 'resource_run_001.json', 'resource_run_001.jsonl'):
        _bytes(roots['neural'] / name)
    _write(roots['neural'] / 'independent_verification.json', fill_neural(roots['neural'], neural))
    for name in ('verification_fit.json', 'results.json', 'test_exposure.json'):
        _bytes(roots['tree'] / name)
    _write(roots['tree'] / 'independent_verification.json', fill_tree(roots['tree'], tree))
    _write(roots['exports'] / 'summary.json', fill_exports(roots['exports'], export))
    return roots, identities


@pytest.fixture
def retained(tmp_path):
    roots, identities = populate_fixture(tmp_path / 'original')
    manifest = retention.build_retention(*(roots[r] for r in retention.ROLES), identities)
    return roots, manifest


def test_complete_opaque_payload_retention_and_regular_lock_exclusion(retained):
    roots, manifest = retained
    _bytes(roots['neural'] / 'pipeline.lock', b'1')
    paths = retention.validate_retention(manifest, roots)
    assert len([p for p in paths if p.suffix == '.pt']) == 440
    assert len([p for p in paths if p.name.endswith('_predictions.npz')]) == 440
    assert len([p for p in paths if p.suffix == '.joblib']) == 84
    assert all(p.suffix != '.lock' for p in paths)


@pytest.mark.parametrize(('role', 'relative'), [
    ('neural', 'replicas/nslkdd_relu/runs/relu_seed_19.pt'),
    ('neural', 'results/iot23_qcfs/runs/qcfs_seed_19_predictions.npz'),
    ('tree', 'replica/unsw/random_forest/seed_19.joblib'),
    ('tree', 'primary/nslkdd/xgboost/seed_0.ledger.json'),
    ('exports', 'iot23/qcfs/qdq/model_qdq_int8.onnx'),
])
@pytest.mark.parametrize('coordinated', [False, True])
def test_deleted_artifact_or_resealed_partial_inventory_rejected(retained, role, relative, coordinated):
    roots, manifest = retained
    (roots[role] / relative).unlink()
    if coordinated:
        manifest = copy.deepcopy(manifest)
        del manifest['files'][role][relative]
        manifest.pop('content_sha256'); manifest = retention._seal(manifest)
    with pytest.raises(retention.RetentionError): retention.validate_retention(manifest, roots)


def test_empty_or_incomplete_plan_cannot_be_declared_complete(tmp_path):
    roots = {role: tmp_path / role for role in retention.ROLES}
    for root in roots.values(): root.mkdir()
    with pytest.raises(retention.RetentionError, match='missing required'):
        retention.build_retention(*(roots[r] for r in retention.ROLES), {role: 'a'*64 for role in roots})


def test_partial_formal_plan_is_rejected(tmp_path):
    roots, identities = populate_fixture(tmp_path)
    plan = json.loads((roots['neural'] / 'plan.json').read_bytes())
    plan.pop('content_sha256'); plan['jobs'] = plan['jobs'][:1]
    plan = _write(roots['neural'] / 'plan.json', plan)
    identities['neural'] = plan['content_sha256']
    with pytest.raises(retention.RetentionError, match='job/seed matrix'):
        retention.build_retention(*(roots[r] for r in retention.ROLES), identities)


@pytest.mark.parametrize('alias', ['symlink', 'hardlink', 'lock_symlink', 'directory_symlink'])
def test_aliases_rejected_even_for_excluded_locks(retained, tmp_path, alias):
    roots, manifest = retained
    target = roots['neural'] / 'replicas/nslkdd_relu/runs/relu_seed_19.pt'
    if alias == 'directory_symlink':
        (roots['tree'] / 'alias').symlink_to(roots['neural'], target_is_directory=True)
    elif alias == 'lock_symlink':
        (roots['tree'] / 'pipeline.lock').symlink_to(target)
    elif alias == 'hardlink':
        (tmp_path / 'alias.pt').hardlink_to(target)
    else:
        saved = tmp_path / 'saved.pt'; target.rename(saved); target.symlink_to(saved)
    with pytest.raises(retention.RetentionError, match='alias|hardlink'):
        retention.validate_retention(manifest, roots)


def test_relocated_copy_validates_but_changed_copy_does_not(retained, tmp_path):
    roots, manifest = retained
    copied = {role: tmp_path / 'copy' / role for role in roots}
    for role, path in roots.items(): shutil.copytree(path, copied[role])
    retention.validate_retention(manifest, copied)
    (copied['tree'] / 'replica/unsw/xgboost/seed_0.joblib').write_bytes(b'changed during copy')
    with pytest.raises(retention.RetentionError, match='bytes changed'):
        retention.validate_retention(manifest, copied)


def test_same_fd_mutate_restore_rejected(retained, monkeypatch):
    roots, manifest = retained
    target = roots['neural'] / 'replicas/nslkdd_relu/runs/relu_seed_19.pt'
    target_inode = target.stat().st_ino
    fdopen = retention.os.fdopen
    class RacingStream:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): self.stream.__enter__(); return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def fileno(self): return self.stream.fileno()
        def read(self, size):
            payload = self.stream.read(size)
            if payload and os.fstat(self.fileno()).st_ino == target_inode:
                with target.open('r+b') as changed:
                    changed.write(b'!'); changed.flush(); os.fsync(changed.fileno())
                    changed.seek(0); changed.write(payload[:1]); changed.flush(); os.fsync(changed.fileno())
            return payload
    monkeypatch.setattr(retention.os, 'fdopen', lambda *a, **kw: RacingStream(fdopen(*a, **kw)))
    with pytest.raises(retention.RetentionError, match='changed while reading'):
        retention.validate_retention(manifest, roots)
