"""Independent, offline-only adversarial controls; no author tests imported.

Hand-packed frames and rational expectations follow the documented Nordic
v4.4.1 serialDevice.ts layout/formula. No serial, power, board or capture API
is imported or called. All input bytes below are synthetic.
"""
import csv
from contextlib import redirect_stdout, redirect_stderr
from fractions import Fraction
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest


SOURCE = Path(__file__).with_name('analyze.py')
SPEC = importlib.util.spec_from_file_location('ppk2_independent_target', SOURCE)
a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(a)


def metadata():
    # Deliberately not a copy of analyzer DEFAULTS: simple linear calibration.
    values = {'R': 1, 'GS': 0, 'GI': 1, 'O': 0, 'S': 0, 'I': 0, 'UG': 1}
    return {f'{key}{index}': value for key, value in values.items() for index in range(5)}


def decoder(meta=None, correction=3.0, policy='metadata-exact', spike_filter='none'):
    return a.Decoder(metadata() if meta is None else meta, correction, policy, spike_filter)


def frames(adcs, highs, *, channel=0, counters=None, ranges=None, extra_bits=0):
    counters = list(range(len(adcs))) if counters is None else counters
    ranges = [0] * len(adcs) if ranges is None else ranges
    return b''.join(struct.pack('<I', adc | (r << 14) | ((counter % 64) << 18) |
                              ((extra_bits | ((1 << channel) if high else 0)) << 24))
                    for adc, high, counter, r in zip(adcs, highs, counters, ranges))


def analyze(raw, dec=None, **options):
    arguments = dict(channel=0, baseline=[0,1], min_samples=1,
                     inferences=1, expected_windows=1, energy_voltage_v=3.0)
    arguments.update(options)
    return a.analyze_stream(io.BytesIO(raw), decoder() if dec is None else dec, **arguments)


def expected_ua(adc, coefficients, r, correction):
    q = lambda key: Fraction(str(coefficients[f'{key}{r}']))
    v = Fraction(str(correction))
    linear = (4*adc-q('O')) * Fraction(9,819200) / q('R')
    # Expanded polynomial, independently evaluated as exact rational values.
    return float((q('UG')*q('GS')*linear**2 + q('UG')*q('GI')*linear +
                  q('UG')*q('S')*v + q('UG')*q('I')) * 1000000)


class FormulaControls(unittest.TestCase):
    def test_adc_times_four_and_amp_to_microamp(self):
        result = decoder().current_ua(1024,0)
        self.assertEqual(result,45000.0)
        self.assertNotEqual(result,11250.0)

    def test_all_ranges_full_polynomial_independent_rational(self):
        meta=metadata()
        for r in range(5):
            for key,value in {'R':2**(r+1),'GS':.25,'GI':.75,'O':7,
                              'S':-.0002,'I':.0009,'UG':1.125}.items():
                meta[f'{key}{r}']=value
        d=decoder(meta,correction=1.8)
        for r in range(5):
            with self.subTest(range=r):
                target=expected_ua(1234,meta,r,1.8)
                self.assertTrue(math.isclose(d.current_ua(1234,r),target,rel_tol=1e-13,abs_tol=1e-12))

    def test_exact_zero_gain_preserved_gui_substitution_explicit(self):
        meta=metadata();meta['GI0']=0
        exact=decoder(meta)
        gui=decoder(meta,policy='nordic-gui-4.4.1')
        self.assertEqual(exact.current_ua(100,0),0.0)
        self.assertGreater(gui.current_ua(100,0),0.0)
        self.assertEqual(exact.substitutions,{})
        self.assertEqual(gui.substitutions['GS0'],{'raw':0.0,'effective':1.0})
        self.assertEqual(gui.substitutions['GI0'],{'raw':0.0,'effective':1.0})

    def test_zero_resistance_or_user_gain_requires_policy(self):
        for key in ('R0','UG0'):
            meta=metadata();meta[key]=0
            with self.subTest(key=key), self.assertRaises(ValueError):decoder(meta)
            self.assertGreater(decoder(meta,policy='nordic-gui-4.4.1').coef[key.rstrip('0')][0],0)

    def test_correction_voltage_not_energy_voltage_or_metadata_vdd(self):
        meta=metadata();meta['GI0']=0;meta['S0']=.001;meta['VDD']=4999
        raw=frames([0]*4,[False,True,True,False])
        result=analyze(raw,decoder(meta,correction=1.2),energy_voltage_v=4.)
        self.assertAlmostEqual(result['windows'][0]['energy_estimate_uJ'],.096,places=14)
        self.assertAlmostEqual(result['mean_current_uA'],1200.,places=10)

    def test_negative_current_and_energy_are_not_clamped(self):
        meta=metadata();meta['GI0']=0;meta['I0']=-.001
        result=analyze(frames([0]*4,[False,True,True,False]),decoder(meta))
        self.assertTrue(result['window_checks_passed'])
        self.assertEqual(result['minimum_current_uA'],-1000.)
        self.assertAlmostEqual(result['windows'][0]['energy_estimate_uJ'],-.06,places=14)

    def test_filter_range4_hold_then_lowpass_is_not_continuous_average(self):
        d=decoder(spike_filter='nordic-4.4.1')
        self.assertEqual(d.current_ua(0,0),0.)
        self.assertEqual(d.current_ua(100,4),0.)
        self.assertEqual(d.current_ua(100,4),0.)
        self.assertAlmostEqual(d.current_ua(100,4),expected_ua(100,metadata(),4,3)*.06,places=10)
        self.assertEqual(d.current_ua(100,4),expected_ua(100,metadata(),4,3))

    def test_filter_subtraction_preserves_nordic_binary64_operation(self):
        # Independent reviewer reproduced this one-ULP difference on the old
        # .82 literal. Nordic computes (1.0 - alpha), not decimal .82.
        meta=metadata()
        for r in range(5):meta[f'GI{r}']=0
        meta['I0']=1.23e-5;meta['I1']=1e-6
        d=decoder(meta,spike_filter='nordic-4.4.1')
        d.current_ua(0,0)
        observed=d.current_ua(0,1)
        expected=(.18*1e-6+(1.0-.18)*1.23e-5)*1e6
        wrong=(.18*1e-6+.82*1.23e-5)*1e6
        self.assertNotEqual(struct.pack('>d',expected),struct.pack('>d',wrong))
        self.assertEqual(struct.pack('>d',observed),struct.pack('>d',expected))

    def test_invalid_metadata_coefficient_values(self):
        for bad in (True,None,[],float('nan'),float('inf'),'-inf'):
            meta=metadata();meta['GI0']=bad
            with self.subTest(value=bad), self.assertRaises(ValueError):decoder(meta)
        for key in ('R0','UG0'):
            meta=metadata();meta[key]=-1
            with self.subTest(key=key),self.assertRaises(ValueError):decoder(meta)

    def test_missing_and_case_colliding_coefficients(self):
        meta=metadata();del meta['R4']
        with self.assertRaises(ValueError):decoder(meta)
        meta=metadata();meta['r0']=1
        with self.assertRaises(ValueError):decoder(meta)
        lower={key.lower():v for key,v in metadata().items()}
        self.assertEqual(decoder(lower).current_ua(1024,0),45000.)

    def test_adc_range_voltage_and_policy_domain(self):
        for adc,r in ((True,0),(-1,0),(16384,0),(1.0,0),(0,True),(0,-1),(0,5),(0,7)):
            with self.subTest(adc=adc,r=r),self.assertRaises(ValueError):decoder().current_ua(adc,r)
        for v in (True,0,.79999,5.00001,float('nan'),float('inf')):
            with self.subTest(voltage=v),self.assertRaises(ValueError):decoder(correction=v)
        with self.assertRaises(ValueError):decoder(policy='fallback')
        with self.assertRaises(ValueError):decoder(spike_filter='guess')


class WindowControls(unittest.TestCase):
    def test_energy_units_half_open_window_and_declared_divisor(self):
        raw=frames([10,100,100,10],[False,True,True,False])
        result=analyze(raw,inferences=2)
        w=result['windows'][0]
        self.assertEqual((w['start_sample'],w['stop_sample_exclusive'],w['samples']),(1,3,2))
        expected=expected_ua(100,metadata(),0,3)*2*1e-5*3
        baseline=expected_ua(10,metadata(),0,3)*2*1e-5*3
        self.assertAlmostEqual(w['energy_estimate_uJ'],expected,places=14)
        self.assertAlmostEqual(w['incremental_energy_estimate_uJ'],expected-baseline,places=14)
        self.assertAlmostEqual(w['gross_uJ_per_declared_inference'],expected/2,places=14)
        self.assertEqual(result['raw_sha256'],hashlib.sha256(raw).hexdigest())

    def test_negative_incremental_energy_not_clamped(self):
        result=analyze(frames([100,10,10,100],[False,True,True,False]))
        self.assertTrue(result['window_checks_passed'])
        self.assertLess(result['windows'][0]['incremental_energy_estimate_uJ'],0)

    def test_omitted_energy_voltage_retains_charge_but_no_energy(self):
        r=analyze(frames([10,100,100,10],[False,True,True,False]),energy_voltage_v=None)
        self.assertTrue(r['window_checks_passed'])
        w=r['windows'][0]
        self.assertAlmostEqual(w['charge_estimate_uC'],expected_ua(100,metadata(),0,3)*2e-5,places=14)
        self.assertIsNone(w['energy_estimate_uJ'])
        self.assertIsNone(w['incremental_energy_estimate_uJ'])
        self.assertIsNone(w['gross_uJ_per_declared_inference'])

    def test_complete_minimum_length_and_postwindow_baseline(self):
        r=analyze(frames([10]*5,[False,True,True,False,False]),min_samples=2,baseline=[3,5])
        self.assertTrue(r['window_checks_passed'])
        self.assertEqual(r['baseline_samples'],2)
        self.assertEqual(r['windows'][0]['incremental_energy_estimate_uJ'],0.)

    def test_counter_wrap_is_valid_but_gap_and_duplicate_reject(self):
        raw=frames([10]*4,[False,True,True,False],counters=[62,63,0,1])
        self.assertTrue(analyze(raw)['window_checks_passed'])
        for counters in ([62,63,1,2],[62,63,63,0]):
            with self.subTest(counters=counters),self.assertRaises(ValueError):
                analyze(frames([10]*4,[False,True,True,False],counters=counters))

    def test_initial_high_is_truncated_not_integrated(self):
        r=analyze(frames([10]*3,[True,True,False]),baseline=[2,3])
        self.assertFalse(r['window_checks_passed'])
        self.assertFalse(r['windows'][0]['start_edge_observed'])
        self.assertIsNone(r['windows'][0]['energy_estimate_uJ'])

    def test_trailing_high_does_not_bless_prior_complete_window(self):
        r=analyze(frames([10]*6,[False,True,False,False,True,True]))
        self.assertEqual(len(r['windows']),1)
        self.assertFalse(r['window_checks_passed'])
        self.assertTrue(any('ends HIGH' in p for p in r['problems']))

    def test_baseline_overlap_and_out_of_bounds_refuse(self):
        raw=frames([10]*4,[False,True,True,False])
        for baseline in ([0,2],[3,5],[4,5],[1,1],[-1,1],[False,1],[0,1.0]):
            with self.subTest(baseline=baseline),self.assertRaises(ValueError):analyze(raw,baseline=baseline)

    def test_short_window_is_not_reported_as_energy_measurement(self):
        r=analyze(frames([10]*3,[False,True,False]),min_samples=2)
        self.assertFalse(r['window_checks_passed'])
        self.assertFalse(r['windows'][0]['minimum_samples_met'])
        self.assertIsNone(r['windows'][0]['energy_estimate_uJ'])

    def test_missing_baseline_keeps_only_unaccepted_gross_energy(self):
        r=analyze(frames([10]*3,[False,True,False]),baseline=None)
        self.assertFalse(r['window_checks_passed'])
        self.assertIsNotNone(r['windows'][0]['energy_estimate_uJ'])
        self.assertIsNone(r['windows'][0]['incremental_energy_estimate_uJ'])

    def test_wrong_window_count_and_adc_saturation_fail(self):
        r=analyze(frames([10]*3,[False,True,False]),expected_windows=2)
        self.assertFalse(r['window_checks_passed'])
        r=analyze(frames([16383,10,10],[False,True,False]))
        self.assertFalse(r['window_checks_passed']);self.assertEqual(r['upper_rail_adc_samples'],1)

    def test_gpio_channel_seven_and_other_bits_do_not_change_window(self):
        raw=frames([10]*4,[False,True,True,False],channel=7,extra_bits=1)
        r=analyze(raw,channel=7)
        self.assertTrue(r['window_checks_passed']);self.assertEqual(r['windows'][0]['samples'],2)

    def test_range_histogram_and_current_csv_decoding(self):
        stream=io.StringIO();raw=frames([11,22,33,44],[False,True,True,False],ranges=[0,1,4,2],counters=[63,0,1,2])
        r=analyze(raw,writer=csv.writer(stream))
        self.assertEqual(r['range_histogram'],[1,1,1,0,1]);self.assertEqual(r['range_transitions'],3)
        rows=list(csv.reader(io.StringIO(stream.getvalue())))
        self.assertEqual(rows[2][:6],['1','1e-05','0','1','22','1'])

    def test_empty_partial_and_invalid_range_bytes_reject(self):
        for raw in (b'',b'\x00',frames([0,0,0],[False,True,False],ranges=[0,7,0])):
            with self.subTest(raw=raw),self.assertRaises(ValueError):analyze(raw)

    def test_invalid_analysis_integer_options(self):
        raw=frames([10]*3,[False,True,False])
        for kwargs in ({'channel':True},{'channel':8},{'min_samples':0},{'inferences':0},
                       {'inferences':1.0},{'expected_windows':0},{'expected_windows':100001}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):analyze(raw,**kwargs)

    def test_finite_samples_cannot_create_accepted_infinite_energy(self):
        meta=metadata();meta['GI0']=0;meta['I0']=1e302
        # Every decoded sample is finite (~1e308 uA), but their sum overflows.
        with self.assertRaises(ValueError):
            analyze(frames([0]*4,[False,True,True,False]),decoder(meta))


class OfflineCLIControls(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='ppk2-independent-')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.capture=self.root/'capture';self.capture.mkdir()
        raw=frames([10,100,100,10],[False,True,True,False])
        (self.capture/'samples.u32le').write_bytes(raw)
        fields={key:str(value) for key,value in metadata().items()}
        self.report={'schema':'ppk2-transport-diagnostic-v1','transport_check_passed':True,
                     'metadata_fields':fields,'raw_metadata':'\n'.join(f'{k}: {v}' for k,v in fields.items())+'\nEND\n',
                     'device':{'serial':'synthetic-no-device'},
                     'analysis':{'sha256':hashlib.sha256(raw).hexdigest(),'samples':4,'raw_bytes':len(raw)}}
        self.report_path=self.capture/'report.json'
        self.report_path.write_text(json.dumps(self.report))
        self.original_report=self.report_path.read_bytes()
        self.original_raw=raw

    def arguments(self):
        return ['--capture',str(self.capture),'--capture-report-sha256',hashlib.sha256(self.original_report).hexdigest(),
                '--output',str(self.root/'output'),'--correction-voltage-v','1.2',
                '--correction-voltage-basis','synthetic','--energy-voltage-v','4',
                '--energy-voltage-basis','synthetic','--coefficient-policy','metadata-exact',
                '--spike-filter','none','--channel','0','--baseline','0','1',
                '--min-window-samples','2','--inferences-per-window','2','--expected-windows','1']

    def invoke(self,args):
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):return a.main(args)

    def saved(self):return json.loads((self.root/'output'/'analysis.json').read_text())

    def test_real_entry_success_never_promotes_research_acceptance(self):
        self.assertEqual(self.invoke(self.arguments()),0)
        saved=self.saved();self.assertIs(saved['analysis_checks_passed'],True)
        for key in ('research_measurement_accepted','physical_voltage_verified_by_this_tool',
                    'logic_reference_and_wiring_verified','calibration_accuracy_verified',
                    'sample_clock_accuracy_verified','board_model_and_inference_count_verified',
                    'metadata_vdd_used_as_voltage'):
            self.assertIs(saved[key],False)
        self.assertEqual(self.report_path.read_bytes(),self.original_report)
        self.assertEqual((self.capture/'samples.u32le').read_bytes(),self.original_raw)

    def test_changed_report_refuses_original_caller_hash(self):
        # Coherent report still semantically parseable, but not the promised bytes.
        self.report['device']['serial']='different-synthetic-device'
        self.report_path.write_text(json.dumps(self.report))
        self.assertEqual(self.invoke(self.arguments()),1)
        self.assertIn('caller-supplied SHA256',self.saved()['error'])
        self.assertIs(self.saved()['analysis_completed'],False)

    def test_rehashed_metadata_must_match_original_raw_response(self):
        self.report['metadata_fields']['GI0']='2'
        self.report_path.write_text(json.dumps(self.report))
        args=self.arguments();args[args.index('--capture-report-sha256')+1]=hashlib.sha256(self.report_path.read_bytes()).hexdigest()
        self.assertEqual(self.invoke(args),1)
        self.assertIn('original device response',self.saved()['error'])

    def test_changed_raw_payload_refuses_original_count_and_sha(self):
        replacement=frames([10,200,200,10],[False,True,True,False])
        (self.capture/'samples.u32le').write_bytes(replacement)
        self.assertEqual(self.invoke(self.arguments()),1)
        self.assertIn('Raw payload identity',self.saved()['error'])
        self.assertIs(self.saved()['research_measurement_accepted'],False)

    def test_output_overlap_rejected_before_creating_anything(self):
        for output in (self.capture,self.capture/'nested-output',self.root):
            args=self.arguments();args[args.index('--output')+1]=str(output)
            with self.subTest(output=output),self.assertRaises(SystemExit) as caught:self.invoke(args)
            self.assertEqual(caught.exception.code,2)
        self.assertEqual(sorted(p.name for p in self.capture.iterdir()),['report.json','samples.u32le'])

    def test_missing_voltage_basis_rejected_before_output(self):
        for flag in ('--energy-voltage-basis','--correction-voltage-basis'):
            args=self.arguments();i=args.index(flag);del args[i:i+2]
            with self.subTest(flag=flag),self.assertRaises(SystemExit) as caught:self.invoke(args)
            self.assertEqual(caught.exception.code,2)
        self.assertFalse((self.root/'output').exists())


if __name__=='__main__':unittest.main()
