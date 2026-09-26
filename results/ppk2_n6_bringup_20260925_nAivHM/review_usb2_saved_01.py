"""Saved-only comparison. Prints JSON; never opens USB or modifies captures.

Ranges are independently unpacked, but current conversion reuses the pinned
decoder. This is not an independent calibrated-current implementation.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import struct

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
DECODER = REPO / 'tools/ppk2_energy/analyze.py'
PINS = {
    DECODER: '7eae8347391b11e747be73a7368f55587a9f154e7749f622844e5fae8a9869a9',
    ROOT / 'fixed_am_observation_01/report.json': 'd718b7dd1fe708c467ca9a670c22db00f1544dd9e5364a9fbf36176385fc959d',
    ROOT / 'fixed_am_observation_01/samples.u32le': '594b60173f76e7e08df1de75bebf7a701fbb409972bff83671375e0d632fd29e',
    ROOT / 'usb2_fixed_am_observation_01/report.json': '63c604f007c01f7a2f535d6046e42b03d32173a49bf6cdf8e26e11c544205f06',
    ROOT / 'usb2_fixed_am_observation_01/samples.u32le': 'f3a8c4656fcd92c9ac0a0c6ee9d783ca92af95d8c7c583035d03c5825f9eda97',
}


def check_pins():
    for path, expected in PINS.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Saved input changed: {path}')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def main():
    check_pins()
    spec = importlib.util.spec_from_file_location('saved_ppk_decoder', DECODER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results = []
    for name in ('fixed_am_observation_01', 'usb2_fixed_am_observation_01'):
        report = json.loads((ROOT / name / 'report.json').read_text())
        raw = (ROOT / name / 'samples.u32le').read_bytes()
        require(report['acquisition_completed'] is True, 'Acquisition incomplete')
        require(report['metadata_fields']['mode'] == '1', 'Not Ampere mode')
        require(len(raw) == report['raw_size_bytes'] and len(raw) % 4 == 0, 'Length')
        require(hashlib.sha256(raw).hexdigest() == report['raw_sha256'], 'Raw hash')
        require(report['source_pins_before'] == report['source_pins_after'], 'Source drift')
        commands = report['commands']
        require([c['hex'] for c in commands] == ['0c00', '06', '0c01', '0c00', '07'], 'Commands')
        require(all(c['write_completed'] is True for c in commands), 'Incomplete command')
        words = [v[0] for v in struct.iter_unpack('<I', raw)]
        adc = [w & 16383 for w in words]
        ranges = [(w >> 14) & 7 for w in words]
        counters = [(w >> 18) & 63 for w in words]
        hist = [ranges.count(r) for r in range(5)]
        require(sum(hist) == len(words), 'Invalid range')
        require(hist == report['range_histogram'], 'Reported histogram mismatch')
        gaps = sum(b != (a + 1) % 64 for a, b in zip(counters, counters[1:]))
        require(gaps == 0, 'Visible counter gap')
        upper = [i for i, a in enumerate(adc) if a == 16383]
        require(len(upper) == report['saturated_adc_observations'], 'ADC-top mismatch')
        boundaries = [0] + [i for i in range(1, len(ranges)) if ranges[i] != ranges[i-1]] + [len(ranges)]
        runs = [{'start': a, 'stop_exclusive': b, 'range': ranges[a]}
                for a, b in zip(boundaries, boundaries[1:])]
        current = []
        for volts in (.8, 5.):
            for filt in ('none', 'nordic-4.4.1'):
                decoder = module.Decoder(report['metadata_fields'], volts, 'metadata-exact', filt)
                values = [decoder.current_ua(a, r) for a, r in zip(adc, ranges)]
                tail = values[100000:]
                current.append(dict(assumed_correction_v=volts, filter=filt,
                    decoded_max_ua=max(values), max_sample=values.index(max(values)),
                    tail_start_sample=100000, tail_samples=len(tail),
                    tail_mean_ua=statistics.fmean(tail), tail_min_ua=min(tail), tail_max_ua=max(tail)))
        results.append(dict(capture=name, frames=len(words), range_histogram=hist,
            range_runs=runs, visible_counter_gaps=gaps,
            adc_top_samples=len(upper), adc_top_first=upper[0] if upper else None,
            adc_top_last=upper[-1] if upper else None,
            adc_top_ranges=sorted(set(ranges[i] for i in upper)),
            tail_adc_top_samples=sum(a == 16383 for a in adc[100000:]),
            digital_values=sorted(set(w >> 24 for w in words)),
            host_on_attempt_to_off_attempt_s=report['host_intervals']['on_attempt_to_off_attempt_s'],
            current_sensitivity=current))
    check_pins()
    print(json.dumps(dict(kind='saved_only_usb2_comparison', captures=results,
        pins={str(p): h for p, h in PINS.items()}, hash_bookends_equal=True,
        physical_current_peak_certified=False, voltage_measured=False,
        model_executed=False, energy_accepted=False,
        limits=['Nominal 100 kHz time, not a measured electrical ON edge.',
                'Correction voltage endpoints are assumptions, not an uncertainty interval.',
                'Range transition and ADC-top samples do not certify a physical peak.',
                'Modulo-64 continuity does not exclude losses in multiples of 64.',
                'Current decoder reused; no independent instrument calibration.']), indent=2))


if __name__ == '__main__':
    main()
