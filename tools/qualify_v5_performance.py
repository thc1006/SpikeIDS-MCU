#!/usr/bin/env python3
"""Bounded, fit-only performance qualification; never a scientific result.

Run each invocation in a fresh systemd user scope with MemoryMax=16G and
MemorySwapMax=0. Profiles measure six fixed optimizer/thread candidates twice
on CIC ReLU/QCFS/CNN and IoT ReLU/QCFS. Workers measure 1/4/8 on all 11 jobs,
using the selected, verified profile. All fits use seed 0 and ten epochs.
No API here evaluates test, changes science, retries, or adopts existing output.
Any subprocess failure, repeat mismatch, OOM or resource violation invalidates
the entire invocation; there is no candidate exclusion or runtime fallback.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / 'spikeids_v5'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PACKAGE))

from contracts import ARMS, DATASETS, check_seal, loads_json, require, seal, sources, write_json
from data_loaders import _cache_metadata, _source_snapshot, _stable_json
from evidence import load_fit, read_plan
from resource_evidence import cgroup_sample, cgroup_violations, validate_resource_reports
from suite import load_data_acceptance, resource_monitor
from tools.v5_retention import _inventory, _snapshot

PROFILES = ('single:1', 'single:4', 'foreach:1', 'foreach:4', 'fused:1', 'fused:4')
WORKERS = (1, 4, 8)
MODELS = {'cicids2017': ['relu', 'qcfs', 'cnn'], 'iot23': ['relu', 'qcfs']}
EPOCHS = 10
EXECUTION_POLICY = {'version': 2, 'failure': 'any_subprocess_or_repeat_failure_invalidates_entire_run',
                    'timing': 'sequential_monotonic_ns_intervals_bound_to_outer_raw_telemetry',
                    'selection': 'runtime_only_never_accuracy'}
LIMITS = {'maximum_process_tree_rss_bytes': 14*1024**3,
          'require_bounded_cgroup': True, 'maximum_cgroup_memory_bytes': 16*1024**3,
          'maximum_sample_gap_seconds': 15.0, 'maximum_gpu_memory_used_mib': 15360,
          'maximum_gpu_temperature_c': 80, 'require_zero_swap_io': False,
          'host_swap_scope': 'host context only; workload swap is disabled by cgroup',
          'require_zero_oom_kills': True}


def _json(path):
    value = _stable_json(Path(path)); check_seal(value)
    return value


def preflight_scope():
    """Must run before the environment probe or any GPU subprocess."""
    sample = cgroup_sample()
    require(not cgroup_violations([sample], LIMITS),
            'Performance qualification requires a fresh <=16 GiB/no-swap/OOM-free cgroup')
    return sample


def _clock_identity():
    return {'name': 'monotonic_ns', 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'implementation': time.get_clock_info('monotonic').implementation}


def _invoke(command, log):
    log.parent.mkdir(parents=True, exist_ok=True)
    return_code, error = None, None
    with log.open('x', encoding='utf-8') as stream:
        started = time.monotonic_ns()
        try:
            result = subprocess.run(command, cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, check=False)
            return_code = result.returncode
        except OSError as exc:
            error = f'{type(exc).__name__}: {exc}'
            stream.write(error+'\n')
        finally:
            ended = time.monotonic_ns()
    return {'argv': list(command), 'cwd': str(ROOT), 'return_code': return_code, 'error': error,
            'clock': _clock_identity(), 'started_ns': started, 'ended_ns': ended,
            'wall_seconds': (ended-started)/1e9,
            'log': {'path': str(log), **_snapshot(log)[0]}}


def _profile_attempts(plan):
    """The complete 60-fit order is fixed before attempt 1, including fresh repeats."""
    attempts = []
    for dataset, models in MODELS.items():
        for repeat in (0, 1):
            for profile in (PROFILES if repeat == 0 else tuple(reversed(PROFILES))):
                optimizer, threads = profile.split(':')
                for model in models:
                    stem = f'{optimizer}_{threads}_{repeat}_{model}'
                    output = Path(plan['work_dir'])/'profiles'/dataset/f'{stem}.json'
                    command = [plan['python'], str(PACKAGE/'experiment_all.py'),
                               '--dataset', dataset, '--cache', str(Path(plan['cache_root'])/dataset),
                               '--model', model, '--device', 'cuda', '--optimizer', optimizer,
                               '--threads', threads, '--epochs', str(EPOCHS), '--seeds', '0',
                               '--stage', 'fit', '--output', str(output)]
                    attempts.append({'id': f'{dataset}_{stem}', 'dataset': dataset,
                                     'model': model, 'profile': profile, 'repeat': repeat,
                                     'output': output, 'argv': command})
    return attempts


def _command_matrix(plan):
    if plan['mode'] == 'profiles':
        return {a['id']: a['argv'] for a in _profile_attempts(plan)}
    return {f'workers_{w}_{stage}': command for w in WORKERS
            for stage, command in _worker_commands(plan, w).items()}


def _worker_commands(plan, workers):
    run = Path(plan['work_dir'])/f'workers_{workers}'
    optimizer, threads = plan['selected_profile'].split(':')
    prefix = [plan['python'], str(PACKAGE/'suite.py')]
    freeze = [*prefix, 'freeze', '--cache-root', plan['cache_root'],
              '--raw-audit', plan['raw_audit'], '--data-acceptance', plan['data_acceptance'],
              '--run-dir', str(run), '--device', 'cuda', '--optimizer', optimizer,
              '--threads', threads, '--workers', str(workers), '--seeds', '0',
              '--smoke-epochs', str(EPOCHS), '--bounded-memory']
    return {'freeze': freeze, 'fit': [*prefix, 'fit', '--run-dir', str(run)],
            'verify': [*prefix, 'verify', '--run-dir', str(run)]}


def _input_paths(cache_root, raw_audit, acceptance_path):
    acceptance, binding = load_data_acceptance(raw_audit, acceptance_path, cache_root)
    paths = {Path(__file__).resolve(), ROOT/'tools/v5_retention.py',
             Path(sys.executable).resolve(), *PACKAGE.glob('*.py'),
             Path(raw_audit), Path(acceptance_path),
             Path(binding['independent_verifier']['path']),
             Path(binding['upstream_provenance']['path'])}
    metadata = {}
    for dataset in DATASETS:
        cache, meta = _cache_metadata(Path(cache_root)/dataset)
        accepted = acceptance['datasets'][dataset]
        matches = [r for r in accepted.get('rebuilds', []) if r.get('resolved_root') == str(cache)]
        require(len(matches) == 1 and matches[0].get('metadata_sha256') ==
                _source_snapshot(cache/'metadata.json')['sha256'] and
                matches[0].get('data_fingerprint') == meta['data_fingerprint'] and
                matches[0].get('files_sha256') == meta['files_sha256'] and
                accepted.get('data_fingerprint') == meta['data_fingerprint'],
                'Performance cache is not an independently accepted rebuild')
        metadata[dataset] = {'data_fingerprint': meta['data_fingerprint'],
                             'metadata_sha256': matches[0]['metadata_sha256']}
        paths.update(cache/name for name in ('metadata.json', *meta['files_sha256']))
    return paths, binding, metadata


def _inputs_unchanged(plan, *, rehash=False):
    for text, expected in plan['input_snapshots'].items():
        path = Path(text)
        if rehash:
            actual = _source_snapshot(path)
        else:
            require(path.resolve() == path and not path.is_symlink(), 'Qualification input alias appeared')
            s = path.stat()
            actual = {'device': s.st_dev, 'inode': s.st_ino, 'links': s.st_nlink,
                      'bytes': s.st_size, 'mtime_ns': s.st_mtime_ns, 'ctime_ns': s.st_ctime_ns,
                      'sha256': expected['sha256']}
        require(actual == expected, f'Qualification input/source changed: {path}')


def build_plan(args, work):
    """Freeze the complete candidate matrix, data, software and commands first."""
    preflight_scope()
    parent_binding = None
    if args.mode == 'workers':
        parent_root = Path(args.profile_qualification).absolute()
        parent = verify_qualification(parent_root)
        require(parent['mode'] == 'profiles', 'Workers require a verified profiles qualification')
        previous = _json(parent_root/'qualification_plan.json')
        cache_root, raw_audit, acceptance_path = map(Path, (
            previous['cache_root'], previous['raw_audit'], previous['data_acceptance']))
        selected_profile = parent['fastest_measured']['profile']
        parent_binding = {'root': str(parent_root),
                          'report_sha256': _source_snapshot(parent_root/'qualification.json')['sha256'],
                          'plan_sha256': previous['content_sha256']}
    else:
        cache_root, raw_audit, acceptance_path = (Path(args.cache_root).absolute(),
            Path(args.raw_audit).absolute(), Path(args.data_acceptance).absolute())
        selected_profile = None
    paths, data_evidence, metadata = _input_paths(cache_root, raw_audit, acceptance_path)
    if parent_binding:
        paths.update((parent_root/'qualification.json', parent_root/'qualification_plan.json'))
    snapshots = {str(path.absolute()): _source_snapshot(path) for path in sorted(paths)}
    environments, probes = {}, {}
    threads_set = (1, 4) if args.mode == 'profiles' else (int(selected_profile.split(':')[1]),)
    for threads in threads_set:
        env_path = work/'environment'/f'threads_{threads}.json'
        command = [sys.executable, str(PACKAGE/'experiment_all.py'), '--probe', '--device',
                   'cuda', '--threads', str(threads), '--output', str(env_path)]
        event = _invoke(command, work/'logs'/f'probe_{threads}.log')
        require(event['return_code'] == 0, 'Performance environment probe failed')
        env = _stable_json(env_path)
        require(float(env['gpu_runtime']['power.limit']) ==
                float(env['gpu_runtime']['power.default_limit']) == 165.0,
                'Performance qualification requires the safe/default 165 W power limit')
        if args.mode == 'workers':
            require(env == previous.get('environments', {}).get(str(threads)),
                    'Worker runtime differs from selected-profile runtime; fresh profiles qualification required')
        environments[str(threads)] = env
        probes[str(threads)] = event
        snapshots[str(env_path)] = _source_snapshot(env_path)
    plan = {'schema': 2, 'kind': 'spikeids_v5_performance_qualification_plan',
            'protocol_role': 'performance_qualification', 'paper_finalization_allowed': False,
            'mode': args.mode, 'work_dir': str(work), 'python': sys.executable,
            'cache_root': str(cache_root), 'raw_audit': str(raw_audit),
            'data_acceptance': str(acceptance_path), 'data_evidence': data_evidence,
            'metadata': metadata, 'sources': sources(), 'input_snapshots': snapshots,
            'environments': environments, 'probes': probes,
            'epochs': EPOCHS, 'seeds': [0], 'profiles': list(PROFILES),
            'profile_models': MODELS, 'workers': list(WORKERS),
            'selected_profile': selected_profile, 'profile_qualification': parent_binding,
            'resource_limits': LIMITS, 'jobs': [{'hyperparameters': {'device': 'cuda'}}],
            'execution_policy': EXECUTION_POLICY, 'clock': _clock_identity(),
            'invocation': [sys.executable, *sys.argv],
            'selection': ('sum of two-repeat median dataset sums of individual fit process wall times; accuracy unused'
                          if args.mode == 'profiles' else
                          'total wall time of primary fit plus verified independent repeat; accuracy unused'),
            'limitations': ['short seed-0 engineering workload, not formal 440 fits',
                            'sampled GPU peaks only; cgroup includes workload, not the entire host',
                            'no test evaluation; no universal optimum or full-run ETA claim']}
    plan['commands'] = _command_matrix(plan)
    plan['attempt_order'] = list(plan['commands'])
    _inputs_unchanged(plan, rehash=True)
    return seal(plan)


def _validate_plan(plan, work):
    check_seal(plan)
    require(plan.get('schema') == 2 and
            plan.get('kind') == 'spikeids_v5_performance_qualification_plan' and
            plan.get('protocol_role') == 'performance_qualification' and
            plan.get('paper_finalization_allowed') is False and plan.get('work_dir') == str(work)
            and plan.get('mode') in ('profiles', 'workers') and plan.get('epochs') == EPOCHS
            and plan.get('seeds') == [0] and plan.get('profiles') == list(PROFILES)
            and plan.get('profile_models') == MODELS and plan.get('workers') == list(WORKERS)
            and plan.get('resource_limits') == LIMITS and plan.get('sources') == sources()
            and plan.get('execution_policy') == EXECUTION_POLICY
            and plan.get('jobs') == [{'hyperparameters': {'device': 'cuda'}}]
            and Path(plan.get('python', '')).resolve() == Path(sys.executable).resolve(),
            'Qualification protocol changed or was promoted into formal results')
    clock = plan.get('clock', {})
    require(clock.get('name') == 'monotonic_ns' and
            isinstance(clock.get('implementation'), str) and bool(clock['implementation']) and
            isinstance(clock.get('boot_id'), str) and
            re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', clock['boot_id']),
            'Qualification monotonic clock identity is invalid')
    required_paths, binding, metadata = _input_paths(
        Path(plan['cache_root']), Path(plan['raw_audit']), Path(plan['data_acceptance']))
    require(plan.get('data_evidence') == binding and plan.get('metadata') == metadata,
            'Qualification data acceptance/cache binding changed')
    if plan['mode'] == 'profiles':
        require(plan.get('selected_profile') is None and plan.get('profile_qualification') is None,
                'Profile qualification cannot inherit another selection')
        threads_set = ('1', '4')
    else:
        require(plan.get('selected_profile') in PROFILES and isinstance(plan.get('profile_qualification'), dict),
                'Worker qualification lacks its selected-profile binding')
        parent = Path(plan['profile_qualification']['root'])
        parent_plan = _json(parent/'qualification_plan.json')
        require(parent != work and parent_plan.get('mode') == 'profiles',
                'Worker parent must be a separate profiles qualification')
        required_paths.update((parent/'qualification.json', parent/'qualification_plan.json'))
        threads_set = (plan['selected_profile'].split(':')[1],)
    require(set(plan.get('environments', {})) == set(threads_set) == set(plan.get('probes', {})),
            'Qualification environment probes are incomplete')
    for threads in threads_set:
        path = work/'environment'/f'threads_{threads}.json'
        required_paths.add(path)
        env = _stable_json(path)
        command = [plan['python'], str(PACKAGE/'experiment_all.py'), '--probe', '--device',
                   'cuda', '--threads', threads, '--output', str(path)]
        require(env == plan['environments'][threads] and
                plan['probes'][threads].get('argv') == command and
                plan['probes'][threads].get('return_code') == 0 and
                float(env['gpu_runtime']['power.limit']) == float(env['gpu_runtime']['power.default_limit']) == 165.0,
                'Qualification environment/probe/power contract changed')
        if plan['mode'] == 'workers':
            require(env == parent_plan.get('environments', {}).get(threads),
                    'Worker runtime differs from selected-profile runtime; fresh profiles qualification required')
    require(set(plan.get('input_snapshots', {})) == {str(p.absolute()) for p in required_paths},
            'Qualification omitted a required input/source snapshot')
    expected = _command_matrix(plan)
    require(plan.get('commands') == expected and plan.get('attempt_order') == list(expected),
            'Qualification subprocess matrix changed')


def _fit_summary(path, plan, dataset, model, profile, *, job=None, neural_plan=None):
    record = load_fit(path, job, neural_plan)
    manifest = _json(path.with_suffix('')/'manifest.json')
    optimizer, threads = profile.split(':')
    expected = {'dataset': dataset, 'model': model, 'epochs': EPOCHS, 'seeds': [0],
                'optimizer': optimizer, 'threads': int(threads), 'device': 'cuda',
                'batch_size': 1024 if dataset == 'iot23' else 512, 'eval_batch_size': 4096,
                'eval_every': 10, 'checkpoint_every': 10, 'hidden': 256, 'levels': 4,
                'qcfs_formula': 'shifted_v1', 'lr': .001, 'weight_decay': .00001,
                'data_placement': 'gpu', 'vram_reserve_gib': 2.0, 'compile': False,
                'loss_weighting': 'sqrt_inverse_fit_only_v1',
                'checkpoint_policy': 'fixed_final_epoch_v1'}
    require(all(record['protocol'].get(k) == v for k, v in expected.items()) and
            record.get('status') == 'fit_complete' and record.get('per_seed') == [] and
            record.get('test_previously_exposed') is False and
            type(manifest.get('test_sessions_started')) is int and
            type(manifest.get('test_sessions_completed')) is int and
            manifest.get('test_sessions_started') == manifest.get('test_sessions_completed') == 0 and
            record.get('data_fingerprint') == plan['metadata'][dataset]['data_fingerprint'] and
            record.get('environment') == plan['environments'][threads],
            'Qualification fit accessed test or used another protocol/environment/cache')
    require(not list(path.with_suffix('').rglob('*predictions*')), 'Qualification contains test predictions')
    elapsed = [row.get('elapsed_seconds') for row in record['fit_runs']]
    require(len(elapsed) == 1 and all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in elapsed),
            'Qualification checkpoint lacks a positive finite training elapsed time')
    return {'fingerprint': record['fingerprint'], 'training_digest': record['training_digest'],
            'execution_id': record['execution_identity']['execution_id'],
            'fit_elapsed_seconds': elapsed[0]}


def _execution(work, attempt, expected, plan):
    event = _json(work/'executions'/f'{attempt}.json')
    start, end = event.get('started_ns'), event.get('ended_ns')
    require(event.get('schema') == 2 and event.get('plan_sha256') == plan['content_sha256'] and
            event.get('attempt_id') == attempt and event.get('argv') == expected and
            event.get('cwd') == str(ROOT) and event.get('clock') == plan['clock'] and
            type(start) is int and type(end) is int and 0 < start < end and
            type(event.get('wall_seconds')) in (float, int) and
            math.isfinite(event['wall_seconds']) and event['wall_seconds'] == (end-start)/1e9,
            'Qualification execution timing/command evidence is invalid')
    log = work/'logs'/f'{attempt}.log'
    require(event.get('log') == {'path': str(log), **_snapshot(log)[0]},
            'Qualification execution log changed or belongs to another attempt')
    require(type(event.get('return_code')) is int and event['return_code'] == 0 and
            event.get('error') is None,
            'Qualification subprocess failed; the entire qualification is invalid (no fallback)')
    return event


def _timed_executions(plan, work):
    """Replay complete, sequential intervals against the outer monitor's raw span.

    The monitor uses its own monotonic origin. Four externally recorded boundary
    timestamps constrain that origin without changing the scientific modules.
    This is integrity evidence, not authenticated proof against whole-root forgery.
    """
    commands = _command_matrix(plan)
    require(plan.get('commands') == commands and plan.get('attempt_order') == list(commands),
            'Qualification candidate matrix was changed or omitted')
    actual = set(_inventory(work/'executions'))
    require(actual == {f'{name}.json' for name in commands},
            'Qualification execution matrix is incomplete, duplicated, or extended')
    timeline = _json(work/'execution_timeline.json')
    keys = ('monitor_before_ns', 'monitor_entered_ns', 'monitor_leaving_ns', 'monitor_after_ns')
    points = [timeline.get(key) for key in keys]
    require(timeline.get('schema') == 2 and timeline.get('kind') == 'qualification_execution_timeline' and
            timeline.get('plan_sha256') == plan['content_sha256'] and
            timeline.get('clock') == plan['clock'] and timeline.get('completed') is True and
            timeline.get('attempt_order') == list(commands) and
            all(type(v) is int and v > 0 for v in points) and
            all(a <= b for a, b in zip(points, points[1:])) and points[1] < points[2],
            'Qualification outer monotonic execution timeline is invalid')
    before, entered, leaving, after = points
    events = {name: _execution(work, name, cmd, plan) for name, cmd in commands.items()}
    previous = entered
    for event in events.values():
        require(previous <= event['started_ns'] < event['ended_ns'] <= leaving,
                'Qualification attempt intervals overlap, are reordered, or escape the monitor')
        previous = event['ended_ns']
    require(sorted(p.name for p in work.glob('resource_*.json')) == ['resource_run_001.json'] and
            sorted(p.name for p in work.glob('resource_*.jsonl')) == ['resource_run_001.jsonl'],
            'Qualification must have exactly one complete outer resource-monitor trace')
    report = _json(work/'resource_run_001.json')
    raw = work/'resource_run_001.jsonl'
    raw_snapshot, payload = _snapshot(raw, capture=True)
    require(report.get('plan_sha256') == plan['content_sha256'] and
            report.get('raw_samples') == {'path': raw.name, 'sha256': raw_snapshot['sha256']},
            'Qualification outer telemetry binding changed')
    samples = [loads_json(line, source=str(raw)) for line in payload.splitlines()]
    require(len(samples) >= 2 and samples[0].get('boundary') == 'baseline' and
            samples[-1].get('boundary') == 'final', 'Qualification raw telemetry boundaries missing')
    seconds = [samples[0].get('elapsed_seconds'), samples[-1].get('elapsed_seconds'),
               report.get('duration_seconds')]
    require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in seconds) and
            0 <= seconds[0] < seconds[1] <= seconds[2], 'Qualification telemetry timing is invalid')
    baseline, final, duration = [round(v*1e9) for v in seconds]
    # The internal origin must satisfy all monitor-entry, exit and raw-boundary
    # constraints simultaneously. 10 us only accommodates float/ns conversion.
    lower_origin = max(before, leaving-final, leaving-duration)
    upper_origin = min(entered-baseline, after-duration, entered)
    require(lower_origin <= upper_origin+10_000,
            'Qualification attempt/outer wall times contradict raw telemetry duration or boundaries')
    return events


def _profile_results(plan, work):
    events = _timed_executions(plan, work)
    successful = {p: {d: {'wall_seconds': [0., 0.], 'repetitions': [{}, {}]}
                      for d in MODELS} for p in PROFILES}
    identities = set()
    for attempt in _profile_attempts(plan):
        d, model, profile, repeat = (attempt[k] for k in ('dataset', 'model', 'profile', 'repeat'))
        record = _fit_summary(attempt['output'], plan, d, model, profile)
        event = events[attempt['id']]
        require(record['fit_elapsed_seconds'] <= event['wall_seconds']+1e-6,
                'Qualification fit elapsed time exceeds its measured subprocess interval')
        require(record['execution_id'] not in identities, 'Profile reused an execution namespace')
        identities.add(record['execution_id'])
        successful[profile][d]['wall_seconds'][repeat] += event['wall_seconds']
        successful[profile][d]['repetitions'][repeat][model] = record
    for datasets in successful.values():
        for dataset, evidence in datasets.items():
            first, second = evidence['repetitions']
            require(all(first[m]['fingerprint'] == second[m]['fingerprint'] and
                        first[m]['training_digest'] == second[m]['training_digest'] for m in MODELS[dataset]),
                    'Profile independent training evidence differs; entire qualification is invalid')
    qualified = [{'profile': profile, 'measured_wall_seconds': sum(
        statistics.median(v['wall_seconds']) for v in successful[profile].values()),
        'evidence': successful[profile]} for profile in PROFILES]
    qualified.sort(key=lambda r: (r['measured_wall_seconds'], PROFILES.index(r['profile'])))
    return qualified, {}


def _worker_results(plan, work):
    all_events = _timed_executions(plan, work)
    qualified = []
    for workers in WORKERS:
        events = {stage: all_events[f'workers_{workers}_{stage}'] for stage in ('freeze', 'fit', 'verify')}
        run = work/f'workers_{workers}'
        neural_plan = read_plan(run)
        require(neural_plan.get('protocol_role') == 'smoke_only' and
                neural_plan.get('seeds') == [0] and neural_plan.get('execution', {}).get('workers') == workers
                and neural_plan.get('data_evidence') == plan['data_evidence'], 'Worker smoke plan changed')
        verified = _json(run/'verification_fit.json')
        digests, identities = {}, set()
        elapsed = {'results': [], 'replicas': []}
        for job in neural_plan['jobs']:
            records = [_fit_summary(run/folder/f"{job['id']}.json", plan, job['dataset'],
                       job['model'], plan['selected_profile'], job=job, neural_plan=neural_plan)
                       for folder in ('results', 'replicas')]
            require(records[0]['fingerprint'] == records[1]['fingerprint'] and
                    records[0]['training_digest'] == records[1]['training_digest'], 'Worker independent repeat differs')
            for folder, record in zip(elapsed, records):
                require(record['execution_id'] not in identities, 'Worker reused an execution namespace')
                identities.add(record['execution_id'])
                elapsed[folder].append(record['fit_elapsed_seconds'])
            digests[job['id']] = records[0]['training_digest']
        require(verified.get('passed') is True and verified.get('plan_sha256') == neural_plan['content_sha256']
                and verified.get('jobs') == digests, 'Worker verification is incomplete or stale')
        for folder, stage in (('results', 'fit'), ('replicas', 'verify')):
            require(max(elapsed[folder]) <= events[stage]['wall_seconds']+1e-6 and
                    sum(elapsed[folder]) <= workers*events[stage]['wall_seconds']+1e-6,
                    'Worker checkpoint elapsed times exceed measured parallel subprocess capacity')
        qualified.append({'workers': workers, 'measured_wall_seconds': sum(events[s]['wall_seconds'] for s in ('fit', 'verify')),
                          'training_digests': digests, 'execution_ids': sorted(identities)})
    control = next((r for r in qualified if r['workers'] == 1), None)
    require(control is not None, 'Worker-1 control failed; no cross-worker qualification is possible')
    require(all(r['training_digests'] == control['training_digests'] for r in qualified),
            'Training digests differ across worker counts')
    qualified.sort(key=lambda r: (r['measured_wall_seconds'], r['workers']))
    require(len({identity for row in qualified for identity in row['execution_ids']}) == 66,
            'Worker candidates reused independent execution namespaces')
    return qualified, {}


def _artifacts(work):
    return {name: _snapshot(path)[0] for name, path in _inventory(work).items()
            if name != 'qualification.json'}


def _assert_fit_only_artifacts(work):
    """Failed/partial candidates also cannot conceal a test exposure ledger."""
    files = _inventory(work)
    require(not any('predictions' in Path(name).name or Path(name).name == 'verification_evaluate.json'
                    for name in files), 'Qualification contains forbidden test-evaluation artifacts')
    for name, path in files.items():
        if Path(name).name in ('manifest.json', 'fit_manifest.json'):
            ledger = _json(path)
            require(all(type(ledger.get(key)) is int and ledger[key] == 0
                        for key in ('test_sessions_started', 'test_sessions_completed')),
                    'A successful or failed qualification candidate opened test')
        if path.suffix == '.pt':
            require((path.parent.parent/'manifest.json').is_file(),
                    'Qualification checkpoint has no test-exposure ledger')


def verify_qualification(work):
    work = Path(work).absolute()
    plan = _json(work/'qualification_plan.json'); _validate_plan(plan, work)
    report_path = work/'qualification.json'
    report_snapshot = _source_snapshot(report_path)
    report = _stable_json(report_path, expected_sha256=report_snapshot['sha256']); check_seal(report)
    require(report.get('schema') == 2 and report.get('kind') == 'spikeids_v5_performance_qualification' and
            report.get('passed') is True and report.get('test_evaluated') is False and
            report.get('paper_finalization_allowed') is False and report.get('plan_sha256') == plan['content_sha256']
            and report.get('mode') == plan['mode'], 'Qualification is incomplete, failed, or stale')
    _inputs_unchanged(plan, rehash=True)
    require(report.get('artifacts') == _artifacts(work), 'Qualification artifact inventory changed')
    validate_resource_reports(work, plan)
    _assert_fit_only_artifacts(work)
    qualified, failed = (_profile_results if plan['mode'] == 'profiles' else _worker_results)(plan, work)
    require(qualified and report.get('qualified') == qualified and report.get('failed_candidates') == failed
            and report.get('fastest_measured') == qualified[0], 'Qualification ranking/digests changed')
    if plan['mode'] == 'workers':
        binding = plan['profile_qualification']; parent_root = Path(binding['root'])
        parent = verify_qualification(parent_root)
        require(_source_snapshot(parent_root/'qualification.json')['sha256'] == binding['report_sha256'] and
                _json(parent_root/'qualification_plan.json')['content_sha256'] == binding['plan_sha256'] and
                parent['fastest_measured']['profile'] == plan['selected_profile'], 'Worker profile selection changed')
    # Checkpoint replay and recursive parent verification can take substantial
    # time. Their inputs, evidence and report must still be the same at return.
    _inputs_unchanged(plan, rehash=True)
    require(report.get('artifacts') == _artifacts(work),
            'Qualification artifacts changed during verification')
    _inputs_unchanged(plan)  # stat/ctime guard also closes the final inventory walk
    require(_source_snapshot(report_path) == report_snapshot,
            'Qualification report changed during verification')
    return report


def execute(args):
    preflight_scope()
    work = Path(args.work_dir).absolute()
    require(work.resolve() == work and not work.exists(), 'Qualification requires a fresh canonical work directory')
    if args.mode == 'workers':
        parent = Path(args.profile_qualification).absolute()
        require(parent != work and parent not in work.parents and work not in parent.parents,
                'Worker output must not overlap its immutable profile qualification')
    work.mkdir(parents=True)
    plan = None
    try:
        plan = build_plan(args, work)
        _validate_plan(plan, work)
        write_json(work/'qualification_plan.json', plan)
        timeline = {'schema': 2, 'kind': 'qualification_execution_timeline',
                    'plan_sha256': plan['content_sha256'], 'clock': plan['clock'],
                    'attempt_order': plan['attempt_order'], 'completed': False,
                    'monitor_before_ns': time.monotonic_ns()}
        try:
            with resource_monitor(work, 'run', plan) as healthcheck:
                timeline['monitor_entered_ns'] = time.monotonic_ns()
                try:
                    for attempt in plan['attempt_order']:
                        command = plan['commands'][attempt]
                        _inputs_unchanged(plan); healthcheck()
                        event = _invoke(command, work/'logs'/f'{attempt}.log')
                        event.update(schema=2, plan_sha256=plan['content_sha256'], attempt_id=attempt)
                        write_json(work/'executions'/f'{attempt}.json', seal(event))
                        require(type(event['return_code']) is int and event['return_code'] == 0 and
                                event.get('error') is None,
                                'Qualification subprocess failed; entire qualification invalid (no fallback)')
                        healthcheck()
                finally:
                    timeline['monitor_leaving_ns'] = time.monotonic_ns()
            timeline['completed'] = True
        finally:
            timeline['monitor_after_ns'] = time.monotonic_ns()
            write_json(work/'execution_timeline.json', seal(timeline))
        _inputs_unchanged(plan, rehash=True)
        validate_resource_reports(work, plan)
        _assert_fit_only_artifacts(work)
        qualified, failed = (_profile_results if args.mode == 'profiles' else _worker_results)(plan, work)
        require(qualified, 'No performance candidate qualified')
        report = seal({'schema': 2, 'kind': 'spikeids_v5_performance_qualification',
                       'mode': args.mode, 'plan_sha256': plan['content_sha256'], 'passed': True,
                       'paper_finalization_allowed': False, 'test_evaluated': False,
                       'qualified': qualified, 'failed_candidates': failed,
                       'fastest_measured': qualified[0], 'artifacts': _artifacts(work)})
        write_json(work/'qualification.json', report)
        return verify_qualification(work)
    except BaseException as exc:
        # Retain every partial candidate, log and trace. Never retry/reset here.
        write_json(work/'qualification.json', seal({
            'schema': 2, 'kind': 'spikeids_v5_performance_qualification', 'mode': args.mode,
            'plan_sha256': plan['content_sha256'] if plan else None, 'passed': False,
            'paper_finalization_allowed': False, 'test_evaluated': None,
            'test_policy': 'forbidden; failed/incomplete evidence is not a verified absence claim',
            'error': f'{type(exc).__name__}: {exc}'}))
        raise


def parser():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = p.add_subparsers(dest='mode', required=True)
    profiles = sub.add_parser('profiles', allow_abbrev=False)
    for name in ('cache-root', 'raw-audit', 'data-acceptance', 'work-dir'):
        profiles.add_argument('--'+name, type=Path, required=True)
    workers = sub.add_parser('workers', allow_abbrev=False)
    workers.add_argument('--profile-qualification', type=Path, required=True)
    workers.add_argument('--work-dir', type=Path, required=True)
    verify = sub.add_parser('verify', allow_abbrev=False)
    verify.add_argument('--work-dir', type=Path, required=True)
    return p


def main():
    args = parser().parse_args()
    report = verify_qualification(args.work_dir) if args.mode == 'verify' else execute(args)
    print(report['fastest_measured'])


if __name__ == '__main__':
    main()
