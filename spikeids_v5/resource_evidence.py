"""Linux cgroup limits and replayable sampled resource evidence.

Sampling does not prove absence of sub-interval GPU peaks. The cgroup memory
limit is enforced by the kernel and includes descendants and charged cache.
Unkeyed digests provide integrity, not external attestation.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

from contracts import check_seal, loads_json, require


def _read_evidence_bytes(path: Path) -> bytes:
    """Read one private snapshot, rejecting aliases and concurrent replacement.

    Hashing a path and subsequently reopening it to parse JSON can observe two
    different versions.  Both parsing and hashing must instead consume these
    exact bytes, with inode and change-time checks around the single FD read.
    """
    path = Path(path).absolute()
    require(path.resolve() == path, 'Resource evidence path traverses a symlink')
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            'Resource evidence must be a regular independent file')
    fields = ('st_dev', 'st_ino', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    def snapshot(value):
        return tuple(getattr(value, field) for field in fields)
    flags = os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        require(snapshot(before) == snapshot(opened) and
                stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1,
                'Resource evidence changed while opening')
        payload = stream.read()
        after = os.fstat(stream.fileno())
    require(snapshot(opened) == snapshot(after) == snapshot(path.lstat()) and
            path.resolve() == path,
            'Resource evidence changed while reading')
    return payload


def cgroup_sample() -> dict:
    entries = Path('/proc/self/cgroup').read_text().splitlines()
    rows = [line[3:] for line in entries if line.startswith('0::')]
    require(len(rows) == 1 and rows[0].startswith('/') and
            '..' not in Path(rows[0]).parts, 'A unified cgroup v2 is required')
    root = Path('/sys/fs/cgroup') / rows[0].lstrip('/')
    def number(name):
        value = (root / name).read_text().strip()
        return value if value == 'max' else int(value)
    events = dict(line.split() for line in (root / 'memory.events').read_text().splitlines())
    return {'path': rows[0], 'memory_max': number('memory.max'),
            'memory_current': number('memory.current'),
            'memory_peak': number('memory.peak'),
            'swap_max': number('memory.swap.max'),
            'swap_current': number('memory.swap.current'),
            'events': {key: int(value) for key, value in events.items()}}


def cgroup_violations(samples: list[dict], limits: dict) -> list[str]:
    if not limits.get('require_bounded_cgroup', False):
        return []
    if not samples or any(not isinstance(row, dict) for row in samples):
        return ['cgroup_missing']
    violations = set()
    maximum = limits.get('maximum_cgroup_memory_bytes', 0)
    if len({row.get('path') for row in samples}) != 1:
        violations.add('cgroup_changed')
    for row in samples:
        cap = row.get('memory_max')
        if type(cap) is not int or not 0 < cap <= maximum:
            violations.add('cgroup_memory_limit_not_enforced')
        if row.get('swap_max') != 0 or row.get('swap_current') != 0:
            violations.add('cgroup_swap_not_disabled')
        for key in ('memory_current', 'memory_peak'):
            value = row.get(key)
            if type(value) is not int or not 0 <= value <= maximum:
                violations.add('cgroup_memory_budget_exceeded')
        events = row.get('events', {})
        # A fresh formal scope must not inherit a historical OOM. Fail closed
        # even when the baseline already contains an event.
        if any(type(events.get(key)) is not int or events[key] != 0
               for key in ('oom', 'oom_kill', 'oom_group_kill')):
            violations.add('cgroup_oom_event')
    return sorted(violations)


def process_scope_violations(processes: list[dict], cgroup: dict | None,
                             limits: dict) -> list[str]:
    if not limits.get('require_bounded_cgroup', False):
        return []
    if not cgroup or not isinstance(cgroup.get('path'), str) or not processes:
        return ['cgroup_process_membership_missing']
    root = cgroup['path'].rstrip('/')
    for process in processes:
        path = process.get('cgroup')
        if not isinstance(path, str) or not (path == root or path.startswith(root+'/')):
            return ['process_escaped_cgroup']
    return []


def validate_resource_reports(run_dir: Path, plan: dict) -> list[Path]:
    """Recompute boundaries, counters and peaks from all persisted raw traces."""
    run_dir = Path(run_dir)
    if plan.get('protocol_role') == 'planned_benchmark':
        _limits = plan.get('resource_limits', {})
        require(_limits.get('require_bounded_cgroup') is True and
                _limits.get('maximum_cgroup_memory_bytes') == 16*1024**3 and
                _limits.get('require_zero_oom_kills') is True,
                'Formal workload memory policy is missing or weakened')
    reports = sorted(run_dir.glob('resource_*.json'))
    require(reports, 'Formal resource evidence is missing')
    evidence = []
    actions = []
    for path in reports:
        require(re.fullmatch(r'resource_(run|fit|verify|evaluate)_\d{3,}\.json', path.name),
                'Unexpected resource report identity')
        require(path.resolve() == path.absolute() and path.stat().st_nlink == 1,
                'Resource report must be a canonical independent file')
        report = loads_json(_read_evidence_bytes(path), source=str(path)); check_seal(report)
        action = report.get('action')
        require(path.name.startswith(f'resource_{action}_') and
                report.get('kind') == 'spikeids_v5_resource_telemetry' and
                report.get('plan_sha256') == plan['content_sha256'] and
                report.get('completed') is True and report.get('telemetry_passed') is True and
                report.get('resource_limits') == plan['resource_limits'],
                'Resource report identity, completion, or limits differ')
        raw = run_dir / path.with_suffix('.jsonl').name
        raw_payload = _read_evidence_bytes(raw)
        require(raw.resolve() == raw.absolute() and raw.is_file() and
                raw.stat().st_nlink == 1 and report.get('raw_samples') ==
                {'path': raw.name, 'sha256': hashlib.sha256(raw_payload).hexdigest()},
                'Raw resource trace differs')
        samples = [loads_json(line, source=str(raw)) for line in raw_payload.splitlines()]
        require(len(samples) >= 2 and len(samples) == report.get('samples') and
                samples[0].get('boundary') == 'baseline' and
                samples[-1].get('boundary') == 'final' and
                all(row.get('boundary') == 'periodic' for row in samples[1:-1]) and
                all('sampling_error' not in row for row in samples),
                'Resource boundaries or sampler status invalid')
        times = [row.get('elapsed_seconds') for row in samples]
        require(all(type(value) in (int, float) and value >= 0 for value in times) and
                all(a <= b for a, b in zip(times, times[1:])) and
                times[-1] <= report.get('duration_seconds', -1),
                'Resource sample timing is invalid')
        gap_limit = plan['resource_limits'].get('maximum_sample_gap_seconds', 15.0)
        require(0 < report.get('interval_seconds', 0) <= gap_limit and
                times[0] <= gap_limit and
                report['duration_seconds'] - times[-1] <= gap_limit and
                all(b - a <= gap_limit for a, b in zip(times, times[1:])),
                'Resource trace has an excessive unobserved interval')
        deltas = {key: samples[-1]['host']['vmstat'][key] -
                  samples[0]['host']['vmstat'][key]
                  for key in ('pswpin', 'pswpout', 'oom_kill')}
        require(deltas == report.get('vmstat_delta') and all(v >= 0 for v in deltas.values()),
                'Resource counter summary differs')
        peak_rss = max(sum(p['rss_bytes'] for p in row['processes']) for row in samples)
        limits = plan['resource_limits']
        require(peak_rss == report.get('peak_process_tree_rss_bytes') and
                peak_rss <= limits['maximum_process_tree_rss_bytes'],
                'Resource RSS limit or summary differs')
        require(not limits.get('require_zero_swap_io') or
                deltas['pswpin'] == deltas['pswpout'] == 0, 'Host swap IO detected')
        require(not limits.get('require_zero_oom_kills') or deltas['oom_kill'] == 0,
                'Host OOM detected')
        cg = [row.get('cgroup') for row in samples]
        require(not cgroup_violations(cg, limits), 'Cgroup resource contract failed')
        require(all(not process_scope_violations(row['processes'], row.get('cgroup'), limits)
                    for row in samples), 'A sampled worker escaped the workload cgroup')
        expected_cuda = any(j['hyperparameters']['device'] == 'cuda' for j in plan['jobs'])
        gpu_rows = [row['gpu'] for row in samples if row.get('gpu') is not None]
        require(report.get('gpu_expected') == expected_cuda and
                len(gpu_rows) == report.get('gpu_samples') and
                (not expected_cuda or len(gpu_rows) == len(samples)),
                'GPU trace coverage is incomplete')
        if gpu_rows:
            require(max(g['memory_used_mib'] for g in gpu_rows) <=
                    limits['maximum_gpu_memory_used_mib'] and
                    max(g['temperature_c'] for g in gpu_rows) <=
                    limits['maximum_gpu_temperature_c'], 'GPU resource limit exceeded')
            owned = set()
            unknown_counts = {}
            foreign = set()
            for row in samples:
                owned.update((p['pid'], p['start_ticks']) for p in row['processes'])
                unknown = {(p['pid'], p.get('start_ticks'))
                           for p in row['gpu']['compute_processes']
                           if (p['pid'], p.get('start_ticks')) not in owned}
                unknown_counts = {identity: unknown_counts.get(identity, 0) + 1
                                  for identity in unknown}
                foreign.update(identity for identity, count in unknown_counts.items()
                               if count >= 2 or row['boundary'] in ('baseline', 'final'))
            require(not foreign, 'Raw trace contains foreign GPU compute processes')
        require(report.get('sampling_errors') == [] and
                report.get('resource_limit_violations') == [] and
                report.get('foreign_gpu_pids') == [] and
                report.get('foreign_gpu_process_identities') == [],
                'Resource monitor reported a failure')
        actions.append(action)
        evidence.extend((path, raw))
    require(actions == ['run'] or sorted(actions) == ['evaluate', 'fit', 'verify'],
            'Resource evidence must cover one full run or all three distinct stages')
    require(set(run_dir.glob('resource_*.jsonl')) == set(evidence[1::2]),
            'Unbound or incomplete resource traces exist')
    return evidence
