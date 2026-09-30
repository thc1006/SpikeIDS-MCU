"""Complete scientific-artifact retention gate, using only the standard library.

This is byte/inventory retention, not a replacement for numerical verification.
Never deserialize checkpoint, NPZ, ONNX, or joblib payloads. The sealed manifest
belongs outside all three roots; regular *.lock files alone are excluded.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

ROLES = ('neural', 'tree', 'exports')
JOBS = tuple((d, m) for d in ('nslkdd', 'unsw', 'cicids2017', 'iot23')
             for m in (('relu', 'qcfs') if d == 'iot23' else ('relu', 'qcfs', 'cnn')))
COUNTS = {'neural_checkpoints': 440, 'neural_predictions': 440,
          'neural_executions': 22, 'tree_models': 84, 'tree_records': 84,
          'tree_ledgers': 84, 'export_attempts': 22}


class RetentionError(ValueError):
    pass


def _require(ok, message):
    if not ok:
        raise RetentionError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _seal(value):
    return {**value, 'content_sha256': _digest(value)}


def _check_seal(value):
    _require(isinstance(value, dict) and value.get('content_sha256') ==
             _digest({k: v for k, v in value.items() if k != 'content_sha256'}),
             'Retention input JSON seal is invalid')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'Duplicate retention JSON key')
        result[key] = value
    return result


def _snapshot(path, *, capture=False):
    """Hash and optionally parse the same FD bytes; reject mutate-and-restore."""
    path = Path(path).absolute()
    _require(path.resolve() == path, f'Retention path traverses symlink: {path}')
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
             f'Retention requires regular non-hardlinked files: {path}')
    fields = ('st_dev', 'st_ino', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    def identity(value):
        return tuple(getattr(value, field) for field in fields)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
    fd = os.open(path, flags)
    payload = [] if capture else None
    h = hashlib.sha256()
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        _require(identity(before) == identity(opened), 'Retention file changed while opening')
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
            if capture:
                payload.append(block)
        after = os.fstat(stream.fileno())
    _require(identity(opened) == identity(after) == identity(path.lstat()) and
             path.resolve() == path, f'Retention file changed while reading: {path}')
    return {'sha256': h.hexdigest(), 'bytes': after.st_size}, (b''.join(payload) if capture else None)


def _roots(roots):
    _require(isinstance(roots, dict) and set(roots) == set(ROLES),
             'Retention requires exactly neural/tree/exports roots')
    result = {role: Path(roots[role]).absolute() for role in ROLES}
    for root in result.values():
        _require(root.resolve() == root and root.is_dir() and not root.is_symlink(),
                 'Retention root is missing or noncanonical')
    values = list(result.values())
    _require(all(a != b and a not in b.parents and b not in a.parents
                 for i, a in enumerate(values) for b in values[i + 1:]),
             'Retention roots must be distinct and nonoverlapping')
    return result


def _inventory(root):
    files = {}
    def walk_error(error):
        raise error
    for directory, directories, names in os.walk(root, followlinks=False, onerror=walk_error):
        for name in directories:
            path = Path(directory) / name
            _require(stat.S_ISDIR(path.lstat().st_mode) and not path.is_symlink(),
                     f'Retention directory alias/special entry: {path}')
        for name in names:
            path = Path(directory) / name
            info = path.lstat()
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                     path.resolve() == path, f'Retention file alias/special entry: {path}')
            if not name.endswith('.lock'):
                files[path.relative_to(root).as_posix()] = path
    return dict(sorted(files.items()))


def _scan(roots):
    files = {}
    for role, root in roots.items():
        inventory = _inventory(root)
        files[role] = {name: _snapshot(path)[0] for name, path in inventory.items()}
        _require(set(_inventory(root)) == set(inventory),
                 'Retention file inventory changed during snapshot')
    return files


def _structural_contract(roots, files, identities):
    _require(isinstance(identities, dict) and set(identities) == set(ROLES) and
             all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v)
                 for v in identities.values()), 'Retention plan identities are invalid')

    def need(role, names):
        missing = set(names) - set(files[role])
        _require(not missing, f'Retention missing required {role} files: {sorted(missing)[:5]}')

    def read(role, name):
        need(role, [name])
        snapshot, payload = _snapshot(roots[role] / name, capture=True)
        _require(snapshot == files[role][name], f'Retention JSON changed during validation: {name}')
        value = json.loads(payload, object_pairs_hook=_pairs)
        _check_seal(value)
        return value

    neural = read('neural', 'plan.json')
    tree = read('tree', 'plan.json')
    export = read('exports', 'export_plan.json')
    _require({role: plan['content_sha256'] for role, plan in
              zip(ROLES, (neural, tree, export))} == identities, 'Retention plan identity differs')
    seeds = list(range(20))
    _require(neural.get('schema') == 5 and neural.get('protocol_role') == 'planned_benchmark'
             and neural.get('seeds') == seeds and neural.get('deployment_seed') == 0,
             'Retention requires the fixed 20-seed formal neural plan')
    jobs = neural.get('jobs', [])
    expected_jobs = {f'{d}_{m}' for d, m in JOBS}
    _require(len(jobs) == 11 and {j.get('id') for j in jobs} == expected_jobs and
             all(j.get('id') == f"{j.get('dataset')}_{j.get('model')}" and
                 j.get('hyperparameters', {}).get('seeds') == seeds for j in jobs),
             'Retention neural job/seed matrix is incomplete')
    _require(tree.get('kind') == 'tree_baseline_plan' and
             tree.get('random_forest_seeds') == seeds and tree.get('xgboost_seeds') == [0]
             and set(tree.get('datasets', {})) == {'nslkdd', 'unsw'} and
             tree.get('neural_plan', {}).get('content_sha256') == identities['neural'] and
             tree['neural_plan'].get('sha256') == files['neural']['plan.json']['sha256'],
             'Retention tree plan does not bind the complete formal neural/tree matrix')
    expected_attempts = [(d, m, mode) for d, m in JOBS for mode in ('fp32', 'qdq')]
    _require(export.get('kind') == 'spikeids_v5_export_plan' and
             export.get('source_plan_sha256') == identities['neural'] and
             export.get('source_plan', {}).get('sha256') == files['neural']['plan.json']['sha256']
             and [(a.get('dataset'), a.get('model'), a.get('mode'))
                  for a in export.get('attempts', [])] == expected_attempts,
             'Retention export plan does not bind the full 22-attempt matrix')

    need('neural', ['environment.json', 'verification_fit.json', 'verification_evaluate.json',
                   'independent_verification.json', 'stats_report_globecom.json',
                   'equivalence_v5.json', 'equivalence_v5.md', 'paper_numeric_check.json',
                   'export_registration.json', 'export_prior_exposure.json'])
    independent = read('neural', 'independent_verification.json')
    _require(independent.get('passed') is True and independent.get('plan_sha256') == identities['neural']
             and independent.get('checkpoints_checked') == independent.get('prediction_artifacts_checked') == 440
             and independent.get('executions_checked') == 22,
             'Retention lacks complete independent neural verification')
    resource_reports = [name for name in files['neural']
                        if re.fullmatch(r'resource_(run|fit|verify|evaluate)_\d{3,}\.json', name)]
    _require(resource_reports, 'Retention lacks resource reports')
    need('neural', [name + 'l' for name in resource_reports])
    required_cp, required_npz = set(), set()
    for dataset, model in JOBS:
        job = f'{dataset}_{model}'
        for execution in ('results', 'replicas'):
            stem = f'{execution}/{job}'
            need('neural', [stem + '.json', *(stem + '/' + name for name in
                 ('manifest.json', 'fit_manifest.json', 'fit_evidence.json'))])
            record = read('neural', stem + '.json')
            _require(record.get('status') == 'complete' and record.get('dataset') == dataset
                     and record.get('kind') == model and
                     record.get('formal', {}).get('plan_sha256') == identities['neural'],
                     'Retention neural execution is incomplete or from another plan')
            rows = record.get('per_seed', [])
            _require(len(rows) == 20 and {r.get('seed') for r in rows} == set(seeds),
                     'Retention neural prediction seed inventory is incomplete')
            by_seed = {row['seed']: row for row in rows}
            for seed in seeds:
                cp = f'{stem}/runs/{model}_seed_{seed}.pt'
                npz = f'{stem}/runs/{model}_seed_{seed}_predictions.npz'
                need('neural', [cp, npz]); required_cp.add(cp); required_npz.add(npz)
                checked = independent.get('checkpoints', {}).get(job, {}).get(execution, {}).get(str(seed), {})
                _require(checked.get('path') == cp and checked.get('artifact_sha256') == files['neural'][cp]['sha256']
                         and by_seed[seed].get('artifact') == {
                             'filename': Path(npz).name, 'sha256': files['neural'][npz]['sha256']},
                         'Retention neural checkpoint/prediction binding changed')
    _require({p for p in files['neural'] if p.endswith('.pt')} == required_cp and
             {p for p in files['neural'] if p.endswith('_predictions.npz')} == required_npz,
             'Retention neural model/prediction inventory contains unplanned files')

    need('tree', ['verification_fit.json', 'results.json', 'test_exposure.json',
                  'independent_verification.json', 'onnx/rf_nslkdd_seed_0.onnx',
                  'onnx/rf_unsw_seed_0.onnx'])
    tree_independent = read('tree', 'independent_verification.json')
    _require(tree_independent.get('passed') is True and
             tree_independent.get('tree_plan_sha256') == identities['tree'],
             'Retention tree independent verification is incomplete')
    required_models = set()
    for dataset in ('nslkdd', 'unsw'):
        for kind in ('random_forest', 'xgboost'):
            for seed in seeds if kind == 'random_forest' else [0]:
                for execution in ('primary', 'replica'):
                    stem = f'{execution}/{dataset}/{kind}/seed_{seed}'
                    artifact = stem + '.joblib'; required_models.add(artifact)
                    need('tree', [artifact, stem + '.json', stem + '.ledger.json'])
                    checked = tree_independent.get('models', {}).get(dataset, {}).get(kind, {}).get(str(seed), {}).get(execution, {})
                    _require(checked.get('artifact') == artifact and
                             checked.get('artifact_sha256') == files['tree'][artifact]['sha256'] and
                             checked.get('record_sha256') == files['tree'][stem + '.json']['sha256'] and
                             checked.get('execution_ledger_sha256') == files['tree'][stem + '.ledger.json']['sha256'],
                             'Retention tree model/record/ledger binding changed')
    _require({p for p in files['tree'] if p.endswith('.joblib')} == required_models,
             'Retention tree model inventory contains unplanned files')

    summary = read('exports', 'summary.json')
    _require(summary.get('source_plan_sha256') == identities['neural'] and
             summary.get('export_plan_sha256') == identities['exports'] and
             [(a.get('dataset'), a.get('model'), a.get('mode'))
              for a in summary.get('attempts', [])] == expected_attempts,
             'Retention export summary matrix is incomplete')
    for row in summary['attempts']:
        dataset, model, mode = (row[key] for key in ('dataset', 'model', 'mode'))
        stem = f'{dataset}/{model}/{mode}'
        evidence = stem + '/runner_validation.json'
        log = f'logs/{dataset}_{model}_{mode}.log'
        need('exports', [evidence, log])
        _require(row.get('output_dir') == stem and row.get('evidence') == evidence and row.get('log') == log
                 and row.get('evidence_sha256') == files['exports'][evidence]['sha256']
                 and row.get('log_sha256') == files['exports'][log]['sha256'],
                 'Retention export summary payload binding changed')
        checked = read('exports', evidence)
        actual = {p[len(stem) + 1:]: value['sha256'] for p, value in files['exports'].items()
                  if p.startswith(stem + '/') and p != evidence}
        _require(actual == checked.get('output_files_sha256') and
                 checked.get('export_plan_sha256') == identities['exports'],
                 'Retention export payload inventory differs')
        if row.get('passed') is True:
            names = {'export_report.json', 'export_policy.json', 'validation_vectors.npz',
                     'preprocessing.json', 'calibration_rows.json', 'model_fp32.onnx'}
            if mode == 'qdq':
                names.add('model_qdq_int8.onnx')
        else:
            failed = read('exports', stem + '/FAILED.json')
            stage = failed.get('stage')
            _require(stage in ('freeze', 'fp32_parity', 'qdq_parity'),
                     'Retention export failure is not a recorded scientific gate')
            names = {'FAILED.json', 'export_policy.json'}
            if stage != 'freeze':
                names.add('model_fp32.onnx')
            if stage == 'qdq_parity':
                names.add('model_qdq_int8.onnx')
        _require(set(actual) == names, 'Retention export output payload is incomplete')


def build_retention(neural_run: Path, tree_run: Path, export_root: Path,
                    planidentities: dict) -> dict:
    """Snapshot all regular scientific files, after checking formal cardinality."""
    roots = _roots(dict(zip(ROLES, (neural_run, tree_run, export_root))))
    files = _scan(roots)
    _structural_contract(roots, files, planidentities)
    return _seal({'schema': 1, 'kind': 'spikeids_v5_full_scientific_retention',
                  'plan_identities': dict(planidentities),
                  'source_roots': {role: str(path) for role, path in roots.items()},
                  'files': files, 'required_counts': dict(COUNTS)})


def validate_retention(manifest: dict, roots: dict) -> list[Path]:
    """Recheck complete inventory, bytes and plan-derived mandatory artifacts.

    ``roots`` can designate byte-identical relocated copies. Original paths
    stored inside plans and the manifest are provenance, not rewritten aliases.
    """
    _check_seal(manifest)
    _require(set(manifest) == {'schema', 'kind', 'plan_identities', 'source_roots',
                              'files', 'required_counts', 'content_sha256'} and
             manifest.get('schema') == 1 and manifest.get('kind') ==
             'spikeids_v5_full_scientific_retention' and manifest.get('required_counts') == COUNTS
             and set(manifest.get('source_roots', {})) == set(ROLES),
             'Retention manifest contract is invalid')
    roots = _roots(roots)
    files = _scan(roots)
    _require(files == manifest.get('files'), 'Retention exact inventory or file bytes changed')
    _structural_contract(roots, files, manifest['plan_identities'])
    return [roots[role] / name for role in ROLES for name in files[role]]
