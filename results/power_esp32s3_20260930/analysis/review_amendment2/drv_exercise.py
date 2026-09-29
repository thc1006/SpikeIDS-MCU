"""Review of Amendment 2 driver changes: exercise the pure functions of
run_sessions_esp.py on recorded (read-only) recorder data. Never opens any
`control` FIFO: Recorder.command is overridden. Run with python -B."""
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path('/home/thc1006/dev/SpikeIDS-MCU')
sys.path.insert(0, str(REPO / 'tools/esp32s3_deployment/host_measure'))
import run_sessions_esp as rse  # noqa: E402
rs = rse.rs
BASE = REPO / 'results/power_esp32s3_20260930'
out = {}


class Rec(rs.Recorder):
    def command(self, text):            # never touch the FIFO
        raise AssertionError('command() must not be called in this review')


def off_on_events(rec):
    ev = rec.events()
    return ([e['sample_index'] for e in ev if e['kind'] == 'command' and e.get('name') == 'output_off'],
            [e['sample_index'] for e in ev if e['kind'] == 'command' and e.get('name') == 'output_on'], ev)


# 1. fresh-recorder 0xFF preflight check, evaluated on the pre-ON bins of every recorder
fresh = {}
for d in sorted(BASE.glob('ppk_*')):
    if not d.is_dir():
        continue
    rec = Rec(d)
    offs, ons, ev = off_on_events(rec)
    rows = rec.summary_rows(0)
    first_on = ons[0] if ons else None
    pre = [r for r in rows if first_on is None or int(r['sample_start']) < first_on]
    bad = [r for r in pre if int(r['bits_or']) != 255 or int(r['bits_and']) != 255]
    fresh[d.name] = dict(bins_total=len(rows), bins_pre_on=len(pre), bad_pre_on=len(bad),
                         first_bad=(bad[0]['sample_start'], bad[0]['bits_or'], bad[0]['bits_and']) if bad else None,
                         first_on_sample=first_on,
                         preflight_would_pass=len(pre) >= 300 and not bad)
out['fresh_check_pre_on'] = fresh

# 2. OFF-gap latch check, exactly as the driver computes it (prev_off + 1 s .. next ON / end)
gaps = {}
for name in ('ppk_esp2', 'ppk_esp8', 'ppk_selftest_logic_01'):
    rec = Rec(BASE / name)
    offs, ons, ev = off_on_events(rec)
    rows = rec.summary_rows(0)
    end = int(rows[-1]['sample_start']) + 1000
    res = []
    for off in offs:
        nxt = [o for o in ons if o > off]
        b = nxt[0] if nxt else end
        st, n = rse.logic_states(rec, off + int(rse.OFF_GAP_SKIP_S * 100_000), b)
        # when does the byte stop changing after OFF (first-principles)?
        after = [(int(r['sample_start']), int(r['bits_or']), int(r['bits_and'])) for r in rows
                 if off <= int(r['sample_start']) < b]
        last_change = None
        for i in range(1, len(after)):
            if after[i][1:] != after[i - 1][1:]:
                last_change = (after[i][0] - off) / 1e5
        # all distinct states in the whole gap including the first second
        allst = sorted({x[1:] for x in after})
        # transitions after the skip window (would a board boot be visible?)
        res.append(dict(off_sample=off, window_to=b, window_to_is_next_on=bool(nxt), states=st, bins=n,
                        gate_pass=(len(st) == 1 and n >= 100), last_change_s_after_off=last_change,
                        states_incl_first_second=allst))
    gaps[name] = res
out['off_gap'] = gaps

# 3. status_age_s parsing
now = datetime.now(timezone.utc)
out['status_age_s'] = {
    'aware_+00:00_now': rse.status_age_s({'utc': now.isoformat()}),
    'Z_suffix': rse.status_age_s({'utc': now.strftime('%Y-%m-%dT%H:%M:%S.%fZ')}),
    'naive': rse.status_age_s({'utc': now.replace(tzinfo=None).isoformat()}),
    'missing': rse.status_age_s({}),
    'recorded_ppk_esp2': rse.status_age_s(json.loads((BASE / 'ppk_esp2/status.json').read_text())),
    'python': sys.version.split()[0],
}

# 4. wait_done_esp vs rs.wait_done on identical replayed data (fake clock), ppk_esp2 session 1
class Clock:
    t = 1000.0


real_sleep, real_mono = time.sleep, time.monotonic


def fake_sleep(s):
    Clock.t += s


def fake_mono():
    return Clock.t


class Replay(Rec):
    def __init__(self, d, start, t0, status_over=None):
        super().__init__(d)
        self.start, self.t0, self.over = start, t0, status_over or {}
        self._rows = rs.Recorder.summary_rows(self, start)

    def summary_rows(self, from_sample):
        lim = self.start + int((Clock.t - self.t0) * 100_000)
        return [r for r in self._rows if from_sample <= int(r['sample_start']) < lim]

    def status(self):
        st = dict(utc=datetime.now(timezone.utc).isoformat(), output_on=True, guard_tripped=False,
                  mean_uA_last_1s=65000.0, usb_guard_present_while_on=0)
        st.update(self.over)
        return st


logs = []
time.sleep, time.monotonic = fake_sleep, fake_mono
try:
    rec2 = Rec(BASE / 'ppk_esp2')
    ev = rec2.events()
    s0 = next(e for e in ev if e['kind'] == 'segment_start')['sample_index']
    cmp = {}
    for fn_name, fn in (('rs.wait_done', rs.wait_done), ('wait_done_esp', rse.wait_done_esp)):
        Clock.t = 1000.0
        r = Replay(BASE / 'ppk_esp2', s0, Clock.t)
        res = fn(r, s0, Clock.t, 900.0, logs.append)
        cmp[fn_name] = dict(result=res, fake_elapsed_s=Clock.t - 1000.0)
    out['wait_done_equivalence_ppk_esp2_s1'] = cmp
    cases = {}
    for label, over in (('stale', dict(utc=(datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat())),
                        ('off_no_guard', dict(output_on=False, usb_guard_present_while_on=0)),
                        ('off_usb_guard', dict(output_on=False, usb_guard_present_while_on=3)),
                        ('guard_trip', dict(output_on=False, guard_tripped=True)),
                        ('utc_missing', dict(utc=None))):
        Clock.t = 1000.0
        r = Replay(BASE / 'ppk_esp2', s0, Clock.t, over)
        cases[label] = rse.wait_done_esp(r, s0, Clock.t, 900.0, logs.append)

    class Broken(Replay):
        def status(self):
            raise RuntimeError('status.json unreadable')
    Clock.t = 1000.0
    cases['status_unreadable'] = rse.wait_done_esp(Broken(BASE / 'ppk_esp2', s0, Clock.t), s0, Clock.t, 900.0, logs.append)
    out['wait_done_esp_fault_cases'] = cases
finally:
    time.sleep, time.monotonic = real_sleep, real_mono

# 5. safe_command on a FIFO-less recorder dir (tmp) -> False, logged
import tempfile, os  # noqa: E401,E402
with tempfile.TemporaryDirectory() as td:
    os.mkfifo(Path(td) / 'control')           # a FIFO with no reader -> ENXIO
    lg = []
    ok = rse.safe_command(rs.Recorder(Path(td)), 'stop', lg.append)
    out['safe_command_dead_fifo'] = dict(returned=ok, log=lg)
    (Path(td) / 'control').unlink()
    lg = []
    ok = rse.safe_command(rs.Recorder(Path(td)), 'stop', lg.append)
    out['safe_command_missing_fifo'] = dict(returned=ok, log=lg)

print(json.dumps(out, indent=1, default=str))
