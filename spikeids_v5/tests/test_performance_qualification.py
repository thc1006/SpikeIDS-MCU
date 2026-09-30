"""Pure counterexamples for the performance wrapper; no GPU/training invoked."""
from __future__ import annotations
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import qualify_v5_performance as q
from contracts import ContractError, seal, write_json


def base_plan(work, mode='profiles'):
    plan = {'work_dir': str(work), 'mode': mode, 'python': sys.executable,
            'cache_root': str(work/'cache'), 'raw_audit': str(work/'audit.json'),
            'data_acceptance': str(work/'acceptance.json'), 'selected_profile': 'fused:1',
            'metadata': {d: {'data_fingerprint': d} for d in q.DATASETS},
            'environments': {'1': {'fixture': 1}, '4': {'fixture': 4}},
            'data_evidence': {'fixture': True}, 'clock': q._clock_identity(),
            'content_sha256': 'synthetic-unit-test-plan'}
    plan['commands'] = q._command_matrix(plan)
    plan['attempt_order'] = list(plan['commands'])
    return plan


def test_fixed_matrix_has_sixty_profile_and_sixty_six_worker_fits(tmp_path):
    p = base_plan(tmp_path)
    assert len(q.PROFILES) * sum(map(len, q.MODELS.values())) * 2 == 60
    assert len(q.WORKERS) * sum(len(q.ARMS[d]) for d in q.DATASETS) * 2 == 66
    assert len(p['commands']) == 60
    assert len({a['output'] for a in q._profile_attempts(p)}) == 60
    for cmd in p['commands'].values():
        assert cmd[1].endswith('experiment_all.py')
        assert cmd[cmd.index('--stage')+1] == 'fit'
        assert cmd[cmd.index('--epochs')+1] == '10'
        assert cmd[cmd.index('--seeds')+1] == '0'
        assert 'run' not in cmd and 'evaluate' not in cmd
    for w in q.WORKERS:
        commands = q._worker_commands(p, w)
        assert set(commands) == {'freeze', 'fit', 'verify'}
        assert commands['fit'][2] == 'fit' and commands['verify'][2] == 'verify'
        assert '--bounded-memory' in commands['freeze']
        assert '--nonformal-fixture-evidence-bypass' not in commands['freeze']


@pytest.mark.parametrize('option', ['--epochs', '--seeds', '--models', '--profiles', '--workers'])
def test_cli_cannot_silently_change_the_registered_workload(option):
    with pytest.raises(SystemExit):
        q.parser().parse_args(['profiles', '--cache-root', 'c', '--raw-audit', 'a',
            '--data-acceptance', 'd', '--work-dir', 'w', option, '1'])


def test_bad_scope_fails_before_gpu_probe_or_work_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(q, 'cgroup_sample', lambda: {'memory_max': 'max'})
    monkeypatch.setattr(q, '_invoke', lambda *_: pytest.fail('GPU subprocess was reached'))
    args = q.parser().parse_args(['profiles', '--cache-root', 'c', '--raw-audit', 'a',
            '--data-acceptance', 'd', '--work-dir', str(tmp_path/'work')])
    with pytest.raises(ContractError, match='16 GiB'):
        q.execute(args)
    assert not (tmp_path/'work').exists()


def test_worker_output_cannot_invalidate_its_profile_evidence_by_nesting(tmp_path, monkeypatch):
    monkeypatch.setattr(q, 'preflight_scope', lambda: None)
    monkeypatch.setattr(q, 'build_plan', lambda *_: pytest.fail('Parent qualification was not protected'))
    parent = tmp_path/'profiles'; parent.mkdir()
    args = q.parser().parse_args(['workers', '--profile-qualification', str(parent),
                                 '--work-dir', str(parent/'workers')])
    with pytest.raises(ContractError, match='must not overlap'): q.execute(args)
    assert not (parent/'workers').exists()


def test_acceptance_failure_precedes_gpu_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(q, 'preflight_scope', lambda: None)
    def rejected(*_): raise ContractError('acceptance has not passed')
    monkeypatch.setattr(q, 'load_data_acceptance', rejected)
    monkeypatch.setattr(q, '_invoke', lambda *_: pytest.fail('GPU subprocess was reached'))
    args = q.parser().parse_args(['profiles', '--cache-root', 'c', '--raw-audit', 'a',
            '--data-acceptance', 'd', '--work-dir', str(tmp_path/'work')])
    with pytest.raises(ContractError, match='acceptance'):
        q.execute(args)
    failure = q._json(tmp_path/'work/qualification.json')
    assert failure['passed'] is False


def fit_fixture(plan):
    return {'protocol': {'dataset': 'cicids2017', 'model': 'cnn', 'epochs': 10,
            'seeds': [0], 'optimizer': 'fused', 'threads': 1, 'device': 'cuda',
            'batch_size': 512, 'eval_batch_size': 4096, 'eval_every': 10,
            'checkpoint_every': 10, 'hidden': 256, 'levels': 4, 'qcfs_formula': 'shifted_v1',
            'lr': .001, 'weight_decay': .00001, 'data_placement': 'gpu',
            'vram_reserve_gib': 2.0, 'compile': False,
            'loss_weighting': 'sqrt_inverse_fit_only_v1', 'checkpoint_policy': 'fixed_final_epoch_v1'},
            'status': 'fit_complete', 'per_seed': [], 'test_previously_exposed': False,
            'fit_runs': [{'elapsed_seconds': .1}],
            'data_fingerprint': 'cicids2017', 'environment': plan['environments']['1'],
            'fingerprint': 'f', 'training_digest': 'd', 'execution_identity': {'execution_id': 'e'}}


@pytest.mark.parametrize('attack', ['opened', 'complete', 'predictions', 'epochs', 'environment', 'batch', 'hidden'])
def test_fit_ledger_scope_and_protocol_are_checked(tmp_path, monkeypatch, attack):
    plan = base_plan(tmp_path); record = fit_fixture(plan)
    ledger = {'test_sessions_started': 0, 'test_sessions_completed': 0}
    if attack == 'opened': ledger['test_sessions_started'] = 1
    if attack == 'complete': record['status'] = 'complete'
    if attack == 'predictions': record['per_seed'] = [{'test_evaluated': True}]
    if attack == 'epochs': record['protocol']['epochs'] = 1
    if attack == 'environment': record['environment'] = {'other': 1}
    if attack == 'batch': record['protocol']['batch_size'] = 16
    if attack == 'hidden': record['protocol']['hidden'] = 16
    monkeypatch.setattr(q, 'load_fit', lambda *_: record)
    monkeypatch.setattr(q, '_json', lambda _: ledger)
    with pytest.raises(ContractError, match='accessed test|another protocol'):
        q._fit_summary(tmp_path/'model.json', plan, 'cicids2017', 'cnn', 'fused:1')


@pytest.mark.parametrize('elapsed', [0., -1., float('nan'), float('inf'), True, None])
def test_fit_checkpoint_elapsed_must_be_positive_finite_and_numeric(tmp_path, monkeypatch, elapsed):
    plan = base_plan(tmp_path); record = fit_fixture(plan)
    record['fit_runs'][0]['elapsed_seconds'] = elapsed
    monkeypatch.setattr(q, 'load_fit', lambda *_: record)
    monkeypatch.setattr(q, '_json', lambda _: {'test_sessions_started': 0, 'test_sessions_completed': 0})
    with pytest.raises(ContractError, match='positive finite'):
        q._fit_summary(tmp_path/'model.json', plan, 'cicids2017', 'cnn', 'fused:1')


def timing_fixture(tmp_path, plan):
    """Synthetic clocks/logs only: never a real benchmark or resource report."""
    origin = 1_000_000_000
    entered = origin+500_000_000
    started = entered+100_000_000
    profiles = {a['id']: a['profile'] for a in q._profile_attempts(plan)}
    for attempt, cmd in plan['commands'].items():
        seconds = ((q.PROFILES.index(profiles[attempt])+1.) if plan['mode'] == 'profiles'
                   else 10./int(attempt.split('_')[1]))
        ended = started+round(seconds*1e9)
        log = tmp_path/'logs'/f'{attempt}.log'
        log.parent.mkdir(parents=True, exist_ok=True); log.write_text('synthetic process log')
        write_json(tmp_path/'executions'/f'{attempt}.json', seal({
            'schema': 2, 'plan_sha256': plan['content_sha256'], 'attempt_id': attempt,
            'argv': cmd, 'cwd': str(q.ROOT), 'return_code': 0, 'error': None,
            'clock': plan['clock'], 'started_ns': started, 'ended_ns': ended,
            'wall_seconds': (ended-started)/1e9,
            'log': {'path': str(log), **q._snapshot(log)[0]}}))
        started = ended+100_000_000
    leaving = ended+200_000_000
    write_json(tmp_path/'execution_timeline.json', seal({
        'schema': 2, 'kind': 'qualification_execution_timeline',
        'plan_sha256': plan['content_sha256'], 'clock': plan['clock'],
        'completed': True, 'attempt_order': list(plan['commands']),
        'monitor_before_ns': origin-1_000_000, 'monitor_entered_ns': entered,
        'monitor_leaving_ns': leaving, 'monitor_after_ns': leaving+300_000_000}))
    raw = tmp_path/'resource_run_001.jsonl'
    final_seconds = (leaving-origin)/1e9+.1
    raw.write_text('\n'.join(json.dumps(s) for s in (
        {'boundary': 'baseline', 'elapsed_seconds': .1},
        {'boundary': 'final', 'elapsed_seconds': final_seconds}))+'\n')
    write_json(tmp_path/'resource_run_001.json', seal({
        'plan_sha256': plan['content_sha256'], 'duration_seconds': final_seconds+.05,
        'raw_samples': {'path': raw.name, 'sha256': q._snapshot(raw)[0]['sha256']}}))


def edit_sealed(path, mutate):
    value = q._json(path); value.pop('content_sha256')
    mutate(value)
    write_json(path, seal(value))


def profile_fixture(tmp_path, monkeypatch):
    plan = base_plan(tmp_path)
    timing_fixture(tmp_path, plan)
    reports = {}
    for d, models in q.MODELS.items():
        reports[d] = {'dataset': d, 'device': 'cuda', 'models': models, 'epochs': 10,
                      'test_evaluated': False, 'failed': {}, 'qualified': [
                          {'profile': p, 'wall_seconds': [i+1., i+1.], 'median_wall_seconds': i+1.}
                          for i, p in enumerate(q.PROFILES)]}
    def summary(path, _plan, d, model, profile):
        return {'fingerprint': d+model+profile, 'training_digest': d+model+profile,
                'execution_id': str(path), 'fit_elapsed_seconds': .1}
    monkeypatch.setattr(q, '_fit_summary', summary)
    return plan, reports, summary


def test_profile_ranking_is_runtime_only_and_repeats_are_checked(tmp_path, monkeypatch):
    plan, reports, summary = profile_fixture(tmp_path, monkeypatch)
    # Accuracy is irrelevant even if untrusted summaries contain enticing values.
    for report in reports.values(): report['accuracy'] = {'fused:4': 100, 'single:1': 0}
    qualified, failed = q._profile_results(plan, tmp_path)
    assert qualified[0]['profile'] == 'single:1' and failed == {}
    def altered(path, *args):
        result = summary(path, *args)
        if '_1_relu' in path.name: result['training_digest'] = 'different'
        return result
    monkeypatch.setattr(q, '_fit_summary', altered)
    with pytest.raises(ContractError, match='independent training'):
        q._profile_results(plan, tmp_path)


@pytest.mark.parametrize('message', ['torch.OutOfMemoryError: CUDA out of memory', 'arbitrary failure'])
def test_legacy_failed_strings_cannot_remove_any_candidate(tmp_path, monkeypatch, message):
    plan, reports, _ = profile_fixture(tmp_path, monkeypatch)
    reports['cicids2017']['qualified'].pop(0)
    reports['cicids2017']['failed']['single:1'] = [message]
    for dataset, report in reports.items():
        write_json(tmp_path/'profiles'/dataset/'benchmark.json', seal(report))
    qualified, failed = q._profile_results(plan, tmp_path)
    assert qualified[0]['profile'] == 'single:1' and failed == {} and len(qualified) == 6


def test_cuda_oom_attempt_invalidates_all_candidates_without_fallback(tmp_path, monkeypatch):
    plan, _, _ = profile_fixture(tmp_path, monkeypatch)
    attempt = plan['attempt_order'][0]
    log = tmp_path/'logs'/f'{attempt}.log'
    log.write_text('torch.OutOfMemoryError: CUDA out of memory')
    edit_sealed(tmp_path/'executions'/f'{attempt}.json', lambda e: e.update(
        return_code=1, log={'path': str(log), **q._snapshot(log)[0]}))
    monkeypatch.setattr(q, '_fit_summary', lambda *_: pytest.fail('Failure was not rejected before selection'))
    with pytest.raises(ContractError, match='entire qualification is invalid'):
        q._profile_results(plan, tmp_path)


def test_legacy_inner_zero_or_huge_times_are_not_a_ranking_source(tmp_path, monkeypatch):
    plan, reports, _ = profile_fixture(tmp_path, monkeypatch)
    for dataset, report in reports.items():
        for row in report['qualified']:
            seconds = 0. if row['profile'] == 'fused:4' else 1e12
            row.update(wall_seconds=[seconds, seconds], median_wall_seconds=seconds)
        write_json(tmp_path/'profiles'/dataset/'benchmark.json', seal(report))
    qualified, _ = q._profile_results(plan, tmp_path)
    assert qualified[0]['profile'] == 'single:1'
    assert all(row['measured_wall_seconds'] > 0 for row in qualified)


@pytest.mark.parametrize('mode', ['profiles', 'workers'])
@pytest.mark.parametrize('attack', ['zero', 'huge', 'wall_only', 'overlap', 'clock',
                                  'foreign_plan', 'failed', 'omitted', 'extra', 'log_changed'])
def test_execution_intervals_and_matrix_cannot_be_resealed_into_a_valid_ranking(tmp_path, mode, attack):
    plan = base_plan(tmp_path, mode); timing_fixture(tmp_path, plan)
    first = plan['attempt_order'][0]
    path = tmp_path/'executions'/f'{first}.json'
    if attack == 'omitted':
        path.unlink()
    elif attack == 'extra':
        write_json(tmp_path/'executions/extra.json', seal({'unexpected': True}))
    elif attack == 'log_changed':
        (tmp_path/'logs'/f'{first}.log').write_text('substituted log')
    else:
        def mutate(event):
            if attack == 'zero':
                event.update(ended_ns=event['started_ns'], wall_seconds=0.)
            elif attack == 'huge':
                event.update(ended_ns=event['started_ns']+10**21, wall_seconds=1e12)
            elif attack == 'wall_only': event['wall_seconds'] = .00001
            elif attack == 'overlap':
                event.update(started_ns=1, ended_ns=2, wall_seconds=1e-9)
            elif attack == 'clock': event['clock']['boot_id'] = 'another-boot'
            elif attack == 'foreign_plan': event['plan_sha256'] = 'another-plan'
            elif attack == 'failed': event['return_code'] = 137
        edit_sealed(path, mutate)
    with pytest.raises(ContractError): q._timed_executions(plan, tmp_path)


@pytest.mark.parametrize('mode', ['profiles', 'workers'])
def test_complete_attempt_times_must_fit_the_raw_telemetry_span(tmp_path, mode):
    plan = base_plan(tmp_path, mode); timing_fixture(tmp_path, plan)
    raw = tmp_path/'resource_run_001.jsonl'
    raw.write_text('{"boundary":"baseline","elapsed_seconds":0.1}\n'
                   '{"boundary":"final","elapsed_seconds":0.9}\n')
    edit_sealed(tmp_path/'resource_run_001.json', lambda r: r.update(
        duration_seconds=1., raw_samples={'path': raw.name, 'sha256': q._snapshot(raw)[0]['sha256']}))
    with pytest.raises(ContractError, match='contradict raw telemetry'):
        q._timed_executions(plan, tmp_path)


@pytest.mark.parametrize('mode', ['profiles', 'workers'])
def test_fit_checkpoint_elapsed_is_a_lower_bound_not_the_ranking_source(tmp_path, monkeypatch, mode):
    if mode == 'profiles':
        plan, _, summary = profile_fixture(tmp_path, monkeypatch)
        consumer = q._profile_results
    else:
        plan, summary = worker_fixture(tmp_path, monkeypatch)
        consumer = q._worker_results
    def altered(path, *args, **kwargs):
        result = summary(path, *args, **kwargs)
        result['fit_elapsed_seconds'] = 1e12
        return result
    monkeypatch.setattr(q, '_fit_summary', altered)
    with pytest.raises(ContractError, match='elapsed time'):
        consumer(plan, tmp_path)


def test_invoke_persists_own_intervals_and_log_on_process_start_failure(tmp_path, monkeypatch):
    def fail(*args, **kwargs): raise OSError('synthetic process could not start')
    monkeypatch.setattr(q.subprocess, 'run', fail)
    log = tmp_path/'attempt.log'
    event = q._invoke(['never-started'], log)
    assert event['return_code'] is None and 'OSError' in event['error']
    assert event['ended_ns'] > event['started_ns']
    assert event['wall_seconds'] == (event['ended_ns']-event['started_ns'])/1e9
    assert event['log'] == {'path': str(log), **q._snapshot(log)[0]}
    assert 'synthetic process could not start' in log.read_text()


def worker_fixture(tmp_path, monkeypatch):
    plan = base_plan(tmp_path, 'workers')
    timing_fixture(tmp_path, plan)
    jobs = [{'id': d+'_'+m, 'dataset': d, 'model': m} for d in q.DATASETS for m in q.ARMS[d]]
    digests = {j['id']: j['id'] for j in jobs}
    monkeypatch.setattr(q, 'read_plan', lambda path: {'protocol_role': 'smoke_only', 'seeds': [0],
        'execution': {'workers': int(path.name.split('_')[1])}, 'data_evidence': plan['data_evidence'],
        'content_sha256': path.name, 'jobs': jobs})
    original_json = q._json
    monkeypatch.setattr(q, '_json', lambda path: (
        {'passed': True, 'plan_sha256': path.parent.name, 'jobs': digests}
        if path.name == 'verification_fit.json' else original_json(path)))
    def summary(path, _plan, d, m, profile, **kwargs):
        return {'fingerprint': path.parents[1].name, 'training_digest': d+'_'+m,
                'execution_id': str(path), 'fit_elapsed_seconds': .1}
    monkeypatch.setattr(q, '_fit_summary', summary)
    return plan, summary


def test_workers_compare_training_digest_not_plan_dependent_fingerprint(tmp_path, monkeypatch):
    plan, _ = worker_fixture(tmp_path, monkeypatch)
    qualified, failed = q._worker_results(plan, tmp_path)
    assert qualified[0]['workers'] == 8 and failed == {}
    assert len(qualified[0]['training_digests']) == 11
    assert len(qualified[0]['execution_ids']) == 22


def test_worker_candidate_cannot_be_removed_or_partially_omitted(tmp_path, monkeypatch):
    plan, _ = worker_fixture(tmp_path, monkeypatch)
    (tmp_path/'executions/workers_8_verify.json').unlink()
    with pytest.raises(ContractError, match='matrix is incomplete'):
        q._worker_results(plan, tmp_path)


def test_worker_repeat_digest_mismatch_is_rejected(tmp_path, monkeypatch):
    plan, summary = worker_fixture(tmp_path, monkeypatch)
    def altered(path, *args, **kwargs):
        result = summary(path, *args, **kwargs)
        if 'replicas' in path.parts: result['training_digest'] = 'changed'
        return result
    monkeypatch.setattr(q, '_fit_summary', altered)
    with pytest.raises(ContractError, match='independent repeat'):
        q._worker_results(plan, tmp_path)


def test_cross_worker_digest_mismatch_is_rejected_even_if_each_repeat_matches(tmp_path, monkeypatch):
    plan, summary = worker_fixture(tmp_path, monkeypatch)
    original_json = q._json
    def changed_json(path):
        value = original_json(path)
        if path.name == 'verification_fit.json' and path.parent.name == 'workers_8':
            value = {**value, 'jobs': {k: v+'changed' for k, v in value['jobs'].items()}}
        return value
    def changed_summary(path, *args, **kwargs):
        value = summary(path, *args, **kwargs)
        if 'workers_8' in path.parts: value['training_digest'] += 'changed'
        return value
    monkeypatch.setattr(q, '_json', changed_json)
    monkeypatch.setattr(q, '_fit_summary', changed_summary)
    with pytest.raises(ContractError, match='across worker counts'):
        q._worker_results(plan, tmp_path)


def test_artifact_inventory_detects_changed_or_added_files(tmp_path):
    path = tmp_path/'result.bin'; path.write_bytes(b'first')
    original = q._artifacts(tmp_path)
    path.write_bytes(b'other')
    assert q._artifacts(tmp_path) != original
    path.write_bytes(b'first'); (tmp_path/'new.bin').write_bytes(b'extra')
    assert q._artifacts(tmp_path) != original


@pytest.mark.parametrize('attack', ['opened_ledger', 'missing_ledger', 'prediction', 'evaluation_report'])
def test_failed_candidate_cannot_hide_test_exposure(tmp_path, attack):
    run = tmp_path/'failed_candidate'
    (run/'runs').mkdir(parents=True)
    if attack == 'opened_ledger':
        write_json(run/'manifest.json', seal({'test_sessions_started': 1, 'test_sessions_completed': 0}))
    elif attack == 'missing_ledger':
        (run/'runs/relu_seed_0.pt').write_bytes(b'partial opaque checkpoint')
    elif attack == 'prediction':
        (run/'runs/relu_seed_0_predictions.npz').write_bytes(b'opaque prediction')
    else:
        write_json(run/'verification_evaluate.json', seal({'passed': False}))
    with pytest.raises(ContractError): q._assert_fit_only_artifacts(tmp_path)


@pytest.mark.parametrize('mode', ['profiles', 'workers'])
def test_failed_execution_retains_outputs_and_cannot_resume_same_namespace(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(q, 'preflight_scope', lambda: None)
    work = tmp_path/'qualification'; plan = base_plan(work, mode)
    plan.pop('content_sha256')
    plan = seal(plan)
    monkeypatch.setattr(q, 'build_plan', lambda *_: plan)
    monkeypatch.setattr(q, '_validate_plan', lambda *_: None)
    monkeypatch.setattr(q, '_inputs_unchanged', lambda *_, **__: None)
    monkeypatch.setattr(q, 'validate_resource_reports', lambda *_: None)
    @contextmanager
    def monitor(*_): yield lambda: None
    monkeypatch.setattr(q, 'resource_monitor', monitor)
    calls = []
    def failed(cmd, log):
        calls.append(cmd)
        log.parent.mkdir(parents=True, exist_ok=True); log.write_text('retained failure')
        return {'argv': cmd, 'return_code': 2, 'wall_seconds': 1.}
    monkeypatch.setattr(q, '_invoke', failed)
    arguments = (['profiles', '--cache-root', 'c', '--raw-audit', 'a', '--data-acceptance', 'd']
                 if mode == 'profiles' else ['workers', '--profile-qualification', str(tmp_path/'parent')])
    args = q.parser().parse_args([*arguments, '--work-dir', str(work)])
    with pytest.raises(ContractError, match='entire qualification invalid'):
        q.execute(args)
    assert len(calls) == 1
    assert (work/'logs'/f"{plan['attempt_order'][0]}.log").read_text() == 'retained failure'
    assert q._json(work/'qualification.json')['passed'] is False
    assert q._json(work/'execution_timeline.json')['completed'] is False
    assert len(list((work/'executions').glob('*.json'))) == 1
    with pytest.raises(ContractError, match='fresh canonical'):
        q.execute(args)


@pytest.fixture
def frozen_plan(tmp_path, monkeypatch):
    """Exercise plan construction with synthetic accepted-data/probe providers."""
    monkeypatch.setattr(q, 'preflight_scope', lambda: None)
    evidence = tmp_path/'accepted-fixture.json'; evidence.write_text('fixture input')
    binding = {'synthetic_unit_test_only': True}
    metadata = {d: {'data_fingerprint': d} for d in q.DATASETS}
    monkeypatch.setattr(q, '_input_paths', lambda *_: ({evidence}, binding, metadata))
    work = tmp_path/'work'; work.mkdir()
    def probe(command, log):
        assert '--probe' in command, 'No training subprocess is permitted in these tests'
        path = Path(command[command.index('--output')+1])
        write_json(path, {'gpu_runtime': {'power.limit': '165.0', 'power.default_limit': '165.0'}})
        log.parent.mkdir(parents=True, exist_ok=True); log.write_text('probe fixture')
        return {'argv': command, 'return_code': 0, 'wall_seconds': 1.}
    monkeypatch.setattr(q, '_invoke', probe)
    args = q.parser().parse_args(['profiles', '--cache-root', 'c', '--raw-audit', 'a',
        '--data-acceptance', 'd', '--work-dir', str(work)])
    plan = q.build_plan(args, work)
    q._validate_plan(plan, work)
    return plan, work, evidence


@pytest.mark.parametrize('attack', ['formal', 'epochs', 'memory', 'gpu', 'omit_input', 'command',
                                  'data', 'failed_policy', 'omit_candidate', 'reorder'])
def test_resealed_qualification_plan_cannot_change_scope_or_matrix(frozen_plan, attack):
    plan, work, _ = frozen_plan
    plan = copy.deepcopy(plan); plan.pop('content_sha256')
    if attack == 'formal': plan['protocol_role'] = 'planned_benchmark'
    elif attack == 'epochs': plan['epochs'] = 1
    elif attack == 'memory': plan['resource_limits']['maximum_cgroup_memory_bytes'] *= 2
    elif attack == 'gpu': plan['jobs'] = []
    elif attack == 'omit_input': plan['input_snapshots'].pop(next(iter(plan['input_snapshots'])))
    elif attack == 'command': plan['commands'][plan['attempt_order'][0]][1] = str(q.PACKAGE/'benchmark_profiles.py')
    elif attack == 'data': plan['data_evidence'] = {}
    elif attack == 'failed_policy': plan['execution_policy']['failure'] = 'skip_failed_candidates'
    elif attack == 'omit_candidate': plan['commands'].pop(plan['attempt_order'][0])
    elif attack == 'reorder': plan['attempt_order'].reverse()
    with pytest.raises(ContractError): q._validate_plan(seal(plan), work)


def test_input_byte_change_invalidates_frozen_plan(frozen_plan):
    plan, _, evidence = frozen_plan
    evidence.write_text('changed input')
    with pytest.raises(ContractError, match='input/source changed'):
        q._inputs_unchanged(plan, rehash=True)


@pytest.mark.parametrize('attack', ['none', 'input', 'input_restore', 'artifact', 'new_artifact',
                                  'report', 'report_rewrite'])
def test_verify_rechecks_inputs_artifacts_and_report_after_checkpoint_replay(frozen_plan, monkeypatch, attack):
    plan, work, evidence = frozen_plan
    write_json(work/'qualification_plan.json', plan)
    timing_fixture(work, plan)
    def summary(path, _plan, dataset, model, profile):
        return {'fingerprint': dataset+model+profile, 'training_digest': dataset+model+profile,
                'execution_id': str(path), 'fit_elapsed_seconds': .1}
    monkeypatch.setattr(q, '_fit_summary', summary)
    resource_calls = []
    monkeypatch.setattr(q, 'validate_resource_reports', lambda *_: resource_calls.append('replayed'))
    qualified, failed = q._profile_results(plan, work)
    report_path = work/'qualification.json'
    write_json(report_path, seal({'schema': 2, 'kind': 'spikeids_v5_performance_qualification',
        'mode': 'profiles', 'plan_sha256': plan['content_sha256'], 'passed': True,
        'paper_finalization_allowed': False, 'test_evaluated': False,
        'qualified': qualified, 'failed_candidates': failed, 'fastest_measured': qualified[0],
        'artifacts': q._artifacts(work)}))
    original = q._profile_results
    def tamper_after_replay(*args):
        result = original(*args)
        if attack in ('input', 'input_restore'):
            previous = evidence.read_bytes(); evidence.write_bytes(b'changed during long verification')
            if attack == 'input_restore': evidence.write_bytes(previous)
        elif attack == 'artifact':
            (work/'logs'/f"{plan['attempt_order'][0]}.log").write_text('changed after consumption')
        elif attack == 'new_artifact': (work/'new.bin').write_bytes(b'new file')
        elif attack == 'report': edit_sealed(report_path, lambda r: r.update(unverified_claim=True))
        elif attack == 'report_rewrite': report_path.write_bytes(report_path.read_bytes())
        return result
    monkeypatch.setattr(q, '_profile_results', tamper_after_replay)
    if attack == 'none':
        assert q.verify_qualification(work)['passed'] is True
    else:
        with pytest.raises(ContractError, match='input/source changed|artifacts changed during|report changed during'):
            q.verify_qualification(work)
    assert resource_calls == ['replayed']


@pytest.mark.parametrize('phase', ['build', 'validate'])
def test_workers_cannot_use_a_different_runtime_from_the_selected_profiles(frozen_plan, monkeypatch, phase):
    plan, parent, _ = frozen_plan
    write_json(parent/'qualification_plan.json', plan)
    timing_fixture(parent, plan)
    monkeypatch.setattr(q, '_fit_summary', lambda path, p, d, m, profile: {
        'fingerprint': d+m+profile, 'training_digest': d+m+profile,
        'execution_id': str(path), 'fit_elapsed_seconds': .1})
    monkeypatch.setattr(q, 'validate_resource_reports', lambda *_: None)
    qualified, failed = q._profile_results(plan, parent)
    write_json(parent/'qualification.json', seal({'schema': 2,
        'kind': 'spikeids_v5_performance_qualification', 'mode': 'profiles',
        'plan_sha256': plan['content_sha256'], 'passed': True,
        'paper_finalization_allowed': False, 'test_evaluated': False,
        'qualified': qualified, 'failed_candidates': failed, 'fastest_measured': qualified[0],
        'artifacts': q._artifacts(parent)}))
    assert q.verify_qualification(parent)['passed'] is True
    work = parent.parent/'workers'; work.mkdir()
    args = q.parser().parse_args(['workers', '--profile-qualification', str(parent), '--work-dir', str(work)])
    original_probe = q._invoke
    if phase == 'build':
        def changed_probe(command, log):
            result = original_probe(command, log)
            path = Path(command[command.index('--output')+1])
            env = q._stable_json(path); env['torch'] = 'new-stack-not-profiled'
            write_json(path, env)
            return result
        monkeypatch.setattr(q, '_invoke', changed_probe)
        with pytest.raises(ContractError, match='differs from selected-profile runtime'):
            q.build_plan(args, work)
        assert not (work/'executions').exists()
    else:
        worker_plan = q.build_plan(args, work)
        q._validate_plan(worker_plan, work)
        worker_plan.pop('content_sha256')
        threads = worker_plan['selected_profile'].split(':')[1]
        path = work/'environment'/f'threads_{threads}.json'
        worker_plan['environments'][threads]['torch'] = 'new-stack-not-profiled'
        write_json(path, worker_plan['environments'][threads])
        worker_plan['input_snapshots'][str(path)] = q._source_snapshot(path)
        with pytest.raises(ContractError, match='differs from selected-profile runtime'):
            q._validate_plan(seal(worker_plan), work)


def test_immutable_candidate_matrix_is_sealed_before_first_fit(tmp_path, monkeypatch):
    monkeypatch.setattr(q, 'preflight_scope', lambda: None)
    work = tmp_path/'qualification'; plan = base_plan(work)
    plan.pop('content_sha256')
    plan = seal(plan)
    monkeypatch.setattr(q, 'build_plan', lambda *_: plan)
    monkeypatch.setattr(q, '_validate_plan', lambda *_: None)
    monkeypatch.setattr(q, '_inputs_unchanged', lambda *_, **__: None)
    monkeypatch.setattr(q, 'validate_resource_reports', lambda *_: None)
    @contextmanager
    def monitor(*_): yield lambda: None
    monkeypatch.setattr(q, 'resource_monitor', monitor)
    def invoke(command, log):
        assert q._json(work/'qualification_plan.json') == plan
        return {'argv': command, 'return_code': 2, 'wall_seconds': 1.}
    monkeypatch.setattr(q, '_invoke', invoke)
    args = q.parser().parse_args(['profiles', '--cache-root', 'c', '--raw-audit', 'a',
        '--data-acceptance', 'd', '--work-dir', str(work)])
    with pytest.raises(ContractError, match='entire qualification invalid'): q.execute(args)
