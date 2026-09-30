"""Replay and kernel-scope counterexamples for formal resource evidence."""
import os
from pathlib import Path

import pytest

import contracts as c
import resource_evidence as resources
import suite


def bounded():
    return {'path': '/test.scope', 'memory_max': 16*1024**3,
            'memory_current': 123, 'memory_peak': 456, 'swap_max': 0,
            'swap_current': 0, 'events': {'oom': 0, 'oom_kill': 0, 'oom_group_kill': 0}}


def plan():
    return {'content_sha256': 'a'*64, 'jobs': [{'hyperparameters': {'device': 'cpu'}}],
            'resource_limits': {'maximum_process_tree_rss_bytes': 14*1024**3,
                                'require_bounded_cgroup': True,
                                'maximum_cgroup_memory_bytes': 16*1024**3,
                                'require_zero_swap_io': True, 'require_zero_oom_kills': True}}


@pytest.fixture(autouse=True)
def isolated_process_tree(monkeypatch):
    monkeypatch.setattr(suite,'_process_tree',lambda _pid: [{
        'pid': os.getpid(), 'ppid': 1, 'start_ticks': 10, 'rss_bytes': 100,
        'cmdline': 'synthetic resource fixture', 'cgroup': '/test.scope'}])


@pytest.mark.parametrize(('field','value','issue'), [
    ('memory_max','max','cgroup_memory_limit_not_enforced'),
    ('memory_max',17*1024**3,'cgroup_memory_limit_not_enforced'),
    ('memory_peak',17*1024**3,'cgroup_memory_budget_exceeded'),
    ('swap_max','max','cgroup_swap_not_disabled'),
    ('swap_current',1,'cgroup_swap_not_disabled'),
    ('events',{'oom': 1, 'oom_kill': 0, 'oom_group_kill': 0},'cgroup_oom_event'),
])
def test_unbounded_or_violated_scope_rejected(field,value,issue):
    sample = bounded(); sample[field] = value
    assert issue in resources.cgroup_violations([sample],plan()['resource_limits'])


def test_scope_change_rejected():
    other = bounded(); other['path'] = '/other'
    assert resources.cgroup_violations([bounded(),other],plan()['resource_limits']) == ['cgroup_changed']


def record(tmp_path, monkeypatch):
    monkeypatch.setattr(suite,'cgroup_sample',bounded)
    monkeypatch.setattr(suite,'_host_sample', lambda: {
        'vmstat': {'pswpin': 0, 'pswpout': 0, 'oom_kill': 0},
        'mem_available_bytes': 10**9, 'swap_free_bytes': 10**9})
    with suite.resource_monitor(tmp_path,'run',plan(),1):
        pass
    return tmp_path/'resource_run_001.json', tmp_path/'resource_run_001.jsonl'


def test_short_complete_trace_replays(tmp_path, monkeypatch):
    report,raw = record(tmp_path,monkeypatch)
    assert resources.validate_resource_reports(tmp_path,plan()) == [report,raw]


def test_phase_boundary_failure_prevents_opening_test(tmp_path, monkeypatch):
    monkeypatch.setattr(suite,'cgroup_sample',bounded)
    damaged = False
    opened_test = False
    monkeypatch.setattr(suite,'_host_sample',lambda: {
        'vmstat': {'pswpin': 0, 'pswpout': int(damaged), 'oom_kill': 0},
        'mem_available_bytes': 10**9, 'swap_free_bytes': 10**9})
    with pytest.raises(c.ContractError,match='phase boundary'):
        with suite.resource_monitor(tmp_path,'run',plan(),60) as check:
            damaged = True
            check()
            opened_test = True
    assert opened_test is False
    report = c.load_json(tmp_path/'resource_run_001.json')
    assert report['completed'] is False and report['telemetry_passed'] is False


def test_observed_sampler_stall_blocks_next_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(suite,'cgroup_sample',bounded)
    monkeypatch.setattr(suite,'_host_sample',lambda: {
        'vmstat': {'pswpin': 0, 'pswpout': 0, 'oom_kill': 0},
        'mem_available_bytes': 10**9, 'swap_free_bytes': 10**9})
    elapsed = [0.0]
    monkeypatch.setattr(suite.time,'monotonic',lambda: elapsed[0])
    protocol = plan()
    protocol['resource_limits']['maximum_sample_gap_seconds'] = 15.0
    with pytest.raises(c.ContractError,match='phase boundary'):
        with suite.resource_monitor(tmp_path,'run',protocol,1) as check:
            elapsed[0] = 20.0
            check()
    report = c.load_json(tmp_path/'resource_run_001.json')
    assert 'sampling_gap_limit' in report['resource_limit_violations']


def test_host_swap_context_does_not_override_bounded_workload(tmp_path, monkeypatch):
    monkeypatch.setattr(suite,'cgroup_sample',bounded)
    calls = [0]
    def host():
        calls[0] += 1
        return {'vmstat': {'pswpin': calls[0], 'pswpout': calls[0]*100, 'oom_kill': 0},
                'mem_available_bytes': 10**9, 'swap_free_bytes': 10**9}
    monkeypatch.setattr(suite,'_host_sample',host)
    protocol = plan(); protocol['resource_limits']['require_zero_swap_io'] = False
    with suite.resource_monitor(tmp_path,'run',protocol,1) as check:
        check()
    report = c.load_json(tmp_path/'resource_run_001.json')
    assert report['vmstat_delta']['pswpout'] > 0 and report['telemetry_passed'] is True
    resources.validate_resource_reports(tmp_path,protocol)


@pytest.mark.parametrize('attack',['escape','swap','oom','unbounded','missing','host_oom'])
def test_host_context_mode_never_waives_workload_limits(tmp_path,monkeypatch,attack):
    sample = bounded()
    if attack == 'swap': sample['swap_current'] = 1
    elif attack == 'oom': sample['events']['oom_kill'] = 1
    elif attack == 'unbounded': sample['memory_max'] = 'max'
    elif attack == 'missing': sample = None
    if attack == 'escape':
        monkeypatch.setattr(suite,'_process_tree',lambda _pid: [{
            'pid': os.getpid(),'ppid': 1,'start_ticks':10,'rss_bytes':100,
            'cgroup':'/other.scope','cmdline':'escaped worker'}])
    monkeypatch.setattr(suite,'cgroup_sample',lambda:sample)
    tail = [0]
    monkeypatch.setattr(suite,'_host_sample',lambda: {
        'vmstat':{'pswpin':0,'pswpout':0,'oom_kill':tail[0]},
        'mem_available_bytes':10**9,'swap_free_bytes':10**9})
    protocol = plan(); protocol['resource_limits']['require_zero_swap_io'] = False
    with pytest.raises(c.ContractError,match='telemetry failed closed'):
        with suite.resource_monitor(tmp_path,'run',protocol,1) as check:
            if attack == 'host_oom': tail[0] = 1
            check()


@pytest.mark.parametrize('attack',['boundary','counter','rss','scope','missing_raw','missing_report','summary'])
def test_resealed_resource_counterexamples(tmp_path, monkeypatch, attack):
    report_path,raw = record(tmp_path,monkeypatch)
    report = c.load_json(report_path)
    report.pop('content_sha256')
    rows = [c.loads_json(line) for line in raw.read_bytes().splitlines()]
    if attack == 'missing_raw': raw.unlink()
    elif attack == 'missing_report': report_path.unlink()
    elif attack == 'summary':
        report['peak_process_tree_rss_bytes'] += 1
        c.write_json(report_path,c.seal(report))
    else:
        if attack == 'boundary': rows[-1]['boundary'] = 'periodic'
        elif attack == 'counter': rows[-1]['host']['vmstat']['pswpout'] = 1
        elif attack == 'rss': rows[-1]['processes'][0]['rss_bytes'] += 1
        elif attack == 'scope': rows[-1]['cgroup']['memory_max'] = 'max'
        c.write_text(raw,'\n'.join(c.json_bytes(row).decode() for row in rows)+'\n')
        report['raw_samples']['sha256'] = c.sha256(raw)
        c.write_json(report_path,c.seal(report))
    with pytest.raises((c.ContractError,FileNotFoundError)):
        resources.validate_resource_reports(tmp_path,plan())


def test_raw_trace_hash_and_parse_cannot_observe_different_versions(tmp_path, monkeypatch):
    report_path, raw = record(tmp_path, monkeypatch)
    report = c.load_json(report_path)
    valid = raw.read_bytes()
    rows = [c.loads_json(line) for line in valid.splitlines()]
    rows[-1]['host']['vmstat']['pswpout'] = 123
    invalid = b'\n'.join(c.json_bytes(row) for row in rows) + b'\n'
    c.write_text(raw, invalid.decode())
    report['raw_samples']['sha256'] = c.sha256(raw)
    report.pop('content_sha256')
    c.write_json(report_path, c.seal(report))
    read_bytes = Path.read_bytes

    def split_view(path):
        # The old verifier hashed the invalid file, then reopened it here.
        # Restore the invalid file afterwards so even a final hash would match.
        if path == raw:
            c.write_text(raw, valid.decode())
            contents = read_bytes(path)
            c.write_text(raw, invalid.decode())
            return contents
        return read_bytes(path)

    monkeypatch.setattr(Path, 'read_bytes', split_view)
    with pytest.raises(c.ContractError, match='counter summary differs'):
        resources.validate_resource_reports(tmp_path, plan())


@pytest.mark.parametrize('artifact', ['report', 'raw'])
def test_same_fd_resource_mutate_restore_is_rejected(tmp_path, monkeypatch, artifact):
    report, raw = record(tmp_path, monkeypatch)
    target = report if artifact == 'report' else raw
    fdopen = resources.os.fdopen

    class RacingStream:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def fileno(self):
            return self.stream.fileno()
        def read(self):
            payload = self.stream.read()
            if os.fstat(self.stream.fileno()).st_ino == target.stat().st_ino:
                with target.open('r+b') as changed:
                    changed.write(b'!')
                    changed.flush(); os.fsync(changed.fileno())
                    changed.seek(0); changed.write(payload[:1])
                    changed.flush(); os.fsync(changed.fileno())
            return payload

    monkeypatch.setattr(resources.os, 'fdopen',
                        lambda *args, **kwargs: RacingStream(fdopen(*args, **kwargs)))
    with pytest.raises(c.ContractError, match='changed while reading'):
        resources.validate_resource_reports(tmp_path, plan())


@pytest.mark.parametrize('alias', ['symlink', 'hardlink'])
def test_resource_aliases_are_rejected(tmp_path, monkeypatch, alias):
    _, raw = record(tmp_path, monkeypatch)
    saved = raw.with_suffix('.saved')
    raw.rename(saved)
    if alias == 'symlink':
        raw.symlink_to(saved)
    else:
        raw.hardlink_to(saved)
    with pytest.raises(c.ContractError):
        resources.validate_resource_reports(tmp_path, plan())
