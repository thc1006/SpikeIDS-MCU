"""One saved-only PPK2 pulse comparison; never opens a device or changes power."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
CAPTURE=HERE/'power_pulse_01'
REPORT=CAPTURE/'report.json'
RAW=CAPTURE/'samples.u32le'
ORACLE=ROOT/'tools/ppk2_energy/oracle_crosscheck.py'
DECODER=ROOT/'tools/ppk2_energy/analyze.py'
EXPECTED={REPORT:'97fff127ff94ffb318bd3201225a9db51132b1d058eb54ec7d410c3a96130d62',
 RAW:'41424033b7b7235ba7cd1cd5c36d0406e7ae901a5babba675765cf4ffc8daada',
 ORACLE:'8f9483a0f44644c941c05f8f561a9c3a42ced2b61817371aae6bae4cced66932',
 DECODER:'7eae8347391b11e747be73a7368f55587a9f154e7749f622844e5fae8a9869a9'}


def read(path,expected):
    before=path.stat();raw=path.read_bytes();after=path.stat()
    if before!=after or hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Held bytes changed: '+str(path))
    return raw,before


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value);return value


def main():
    held={path:read(path,sha) for path,sha in EXPECTED.items()}
    report=json.loads(held[REPORT][0]);raw=held[RAW][0]
    if len(raw)!=20480 or len(raw)%4 or report['raw_sha256']!=EXPECTED[RAW]:raise ValueError('Raw frame binding')
    cross=module(ORACLE,'held_ppk_crosscheck');a=module(DECODER,'held_ppk_decoder')
    if a.metadata_text(report['raw_metadata'])!=report['metadata_fields']:raise ValueError('Original metadata mismatch')
    voltage=report['nominal_correction_voltage_v']
    if type(voltage) is not float or voltage!=5.0:raise ValueError('Expected recorded nominal correction voltage')
    numeric={k:float(v) for k,v in report['metadata_fields'].items()}
    words=[v[0] for v in struct.iter_unpack('<I',raw)]
    frames=[dict(index=i,adc=w&16383,range=(w>>14)&7,counter=(w>>18)&63,digital=(w>>24)&255)
            for i,w in enumerate(words)]
    gaps=[i for i in range(1,len(frames)) if frames[i]['counter']!=(frames[i-1]['counter']+1)%64]
    if gaps:raise ValueError('Saved counter discontinuity')
    fetched=subprocess.run(['gh','api',cross.API],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=60)
    source_raw=base64.b64decode(json.loads(fetched.stdout)['content'])
    if cross.sha(source_raw)!=cross.OFFICIAL_SHA:raise ValueError('Official source SHA changed')
    source=source_raw.decode()
    original,current,count=cross.method(source,'getAdcResult(range: number, adcVal: number): number {','function(range, adcVal) {')
    meta_original,parse_meta,meta_count=cross.method(source,'parseMeta(meta: any) {','function(meta) {')
    defaults=re.findall(r'public modifiers: modifiers = (\{.*?\});',source,re.S)
    multiplier=re.findall(r'private adcMult = ([^;]+);',source)
    if count!=5 or meta_count!=0 or len(defaults)!=1 or len(multiplier)!=1:raise ValueError('Fixed extraction changed')
    cases=[dict(name=policy+'/'+filter_name,policy=policy,filter=filter_name,metadata=numeric,volts=voltage,
                samples=[[v['adc'],v['range']] for v in frames])
           for policy in ('metadata-exact','nordic-gui-4.4.1') for filter_name in ('none','nordic-4.4.1')]
    request=dict(current=current,parse_meta=parse_meta,defaults=defaults[0],adc_multiplier=multiplier[0],cases=cases)
    js=subprocess.run(['node','-e',cross.NODE],input=json.dumps(request).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=60)
    reference=json.loads(js.stdout);decoded={};summaries=[]
    for case,expected in zip(cases,reference,strict=True):
        d=a.Decoder(report['metadata_fields'],voltage,case['policy'],case['filter'])
        values=[d.current_ua(v['adc'],v['range']) for v in frames]
        bits=[struct.pack('>d',x).hex() for x in values]
        if case['name']!=expected['name'] or bits!=expected['bits']:raise ValueError('Official/Python binary64 mismatch')
        decoded[case['name']]=values
        peak=max(range(len(values)),key=values.__getitem__)
        summaries.append(dict(case=case['name'],samples=len(values),binary64_mismatches=0,
            stream_bits_sha256=cross.sha(''.join(bits).encode()),minimum_uA=min(values),maximum_uA=values[peak],
            maximum_index=peak,mean_uA=sum(values)/len(values),last_uA=values[-1]))
    unfiltered=decoded['metadata-exact/none'];filtered=decoded['metadata-exact/nordic-4.4.1']
    peak=max(range(len(unfiltered)),key=unfiltered.__getitem__)
    transitions=[v['index'] for v in frames[1:] if v['range']!=frames[v['index']-1]['range']]
    first_nonzero_range=next((v['index'] for v in frames if v['range']!=0),None)
    def details(index):
        return dict(frames[index],nominal_time_s=index*1e-5,unfiltered_uA=unfiltered[index],
                    nordic_filtered_uA=filtered[index])
    for path,(initial,stat) in held.items():
        again,newstat=read(path,EXPECTED[path])
        if again!=initial or newstat!=stat:raise ValueError('Held source/input endpoint changed')
    result=dict(schema=1,kind='saved_actual_ppk2_pulse_official_arithmetic_comparison',passed=True,
        raw_sha256=EXPECTED[RAW],report_sha256=EXPECTED[REPORT],held_source_sha256={str(p):h for p,h in EXPECTED.items()},
        official_source_sha256=cross.OFFICIAL_SHA,official_method_sha256=cross.sha(original.encode()),
        source_and_input_bookends_equal=True,saved_bytes=len(raw),saved_frames=len(frames),
        online_processed_frames=report['samples'],saved_but_not_online_processed_frames=len(frames)-report['samples'],
        complete_64_frame_losses_excluded=False,counter_discontinuities=gaps,
        nominal_full_saved_duration_s=len(frames)*1e-5,first_nonzero_range_index=first_nonzero_range,
        nominal_samples_after_first_nonzero_range=len(frames)-first_nonzero_range,
        nominal_duration_after_first_nonzero_range_s=(len(frames)-first_nonzero_range)*1e-5,
        range_histogram={str(r):sum(v['range']==r for v in frames) for r in range(5)},
        range_transitions=[details(i) for i in transitions],raw_peak=details(peak),
        peak_neighborhood=[details(i) for i in range(max(0,peak-4),min(len(frames),peak+9))],
        final_samples=[details(i) for i in range(len(frames)-8,len(frames))],comparisons=summaries,
        compared_values=len(cases)*len(frames),binary64_mismatches=0,nominal_correction_voltage_v=voltage,
        voltage_measured=False,pulse_target_seconds=report['pulse_target_seconds'],
        original_pulse_completed=report['power_probe_completed'],
        source_report_error=report['error'],hardware_accessed=False,power_changed=False,
        filter_proves_true_current=False,three_second_stability_established=False,
        normal_board_current_established=False,research_measurement_accepted=False,actual_return_code=None)
    print(json.dumps(result,sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
