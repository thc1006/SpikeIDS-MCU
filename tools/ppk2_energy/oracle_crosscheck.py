"""Bounded offline cross-language check of fixed Nordic arithmetic.

Fetches one literal-pinned official source via gh, extracts two pure methods
in memory, removes only their TypeScript annotations, and executes them in
Node with synthetic plain-object state. Never imports a device/serial module.
No source, test, capture, power or hardware state is changed.
"""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import re
import struct
import subprocess
import sys

HERE=Path(__file__).resolve().parent
DECODER=HERE/'analyze.py'
DECODER_SHA='7eae8347391b11e747be73a7368f55587a9f154e7749f622844e5fae8a9869a9'
TEST=HERE/'test_independent.py'
TEST_SHA='235f0fda7796a7bc2e68f59a22ab36240106b15e8e74ad4843dc3634db1bb1e9'
COMMIT='4cbb4c41c420ddb8125638fffc6d72f6b21c5aaa'
OFFICIAL_SHA='37bda3ca2fb927ec67aa0d981773ec09371a2a799138397f2da6b362bd1ae926'
API=f'repos/NordicSemiconductor/pc-nrfconnect-ppk/contents/src/device/serialDevice.ts?ref={COMMIT}'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def method(source,signature,replacement):
    if source.count(signature)!=1:raise ValueError('Method extraction is not unique')
    start=source.index(signature);opening=source.index('{',start);depth=1;end=opening+1
    while depth and end<len(source):
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    if depth:raise ValueError('Unbalanced fixed method')
    original=source[start:end]
    javascript=original.replace(signature,replacement,1)
    javascript,count=re.subn(r'(this\.\w+)!',r'\1',javascript)
    return original,javascript,count


def scenarios():
    rng=random.Random(20260925)
    route=[0,4,4,4,4,1,1,2,4,4,0,3,4,4,4,4,4,2,2]
    samples=[[([0,16383,1,8191][i] if i<4 else rng.randrange(16384)),route[i%len(route)]] for i in range(512)]
    general={}
    for r in range(5):
        for key,value in {'R':[1000,100,10,1,.05][r],'GS':[1,1.1,-.25,0,2][r],
                          'GI':[.97,1.1,1.,.99,1.02][r],'O':[-4,0,5,1,100][r],
                          'S':1e-6*(r-2),'I':1e-8*(r+1),'UG':.91+r*.03}.items():
            general[f'{key}{r}']=value
    zero=general.copy()
    for r in range(5):
        for key in ('GS','GI','S','I','O'):zero[f'{key}{r}']=0
    gui_zero=zero.copy();gui_zero['R0']=0;gui_zero['UG4']=0
    result=[]
    for profile,metadata in [('general',general),('zero-coefficients',zero),('gui-zero-resistance-gain',gui_zero)]:
        policies=['nordic-gui-4.4.1'] if profile.startswith('gui') else ['metadata-exact','nordic-gui-4.4.1']
        for policy in policies:
            for volts in (.8,1.8,3.3,4.,5.):
                for filter_name in ('none','nordic-4.4.1'):
                    result.append(dict(name=f'{profile}/{policy}/{volts}/{filter_name}',metadata=metadata,
                                       policy=policy,volts=volts,filter=filter_name,samples=samples))
    return result


NODE = r'''
const fs = require('node:fs');
const request=JSON.parse(fs.readFileSync(0,'utf8'));
const getAdcResult=Function('return ('+request.current+')')();
const parseMeta=Function('return ('+request.parse_meta+')')();
const originalDefaults=Function('return ('+request.defaults+')')();
const adcMult=Function('return ('+request.adc_multiplier+')')();
function state(test) {
  const object={modifiers:structuredClone(originalDefaults),adcMult,currentVdd:test.volts*1000,
    spikeFilter:{alpha:.18,alpha5:.06,samples:3},consecutiveRangeSample:0,afterSpike:0};
  if(test.policy==='nordic-gui-4.4.1') {
    const meta=Object.fromEntries(Object.entries(test.metadata).map(([k,v])=>[k.toLowerCase(),v]));
    parseMeta.call(object,meta);
  } else {
    for(const key of Object.keys(object.modifiers))
      object.modifiers[key]=object.modifiers[key].map((unused,i)=>test.metadata[key.toUpperCase()+i]);
  }
  return object;
}
const result=request.cases.map(test=>{
  let object=state(test);const effective=structuredClone(object.modifiers);
  const bits=test.samples.map(([adc,range])=>{
    // No-filter uses a fresh state: the official method then returns its raw
    // calibration result without entering any range-transition branch.
    if(test.filter==='none') object=state(test);
    const ua=getAdcResult.call(object,range,adc*4)*1e6;
    if(!Number.isFinite(ua)) throw new Error('Nonfinite official synthetic value '+JSON.stringify({name:test.name,adc,range,object}));
    const bytes=Buffer.alloc(8);bytes.writeDoubleBE(ua);return bytes.toString('hex');
  });
  return {name:test.name,effective,bits};
});
process.stdout.write(JSON.stringify(result));
'''


def main():
    before={str(path):sha(path.read_bytes()) for path in (Path(__file__).resolve(),DECODER,TEST)}
    if before[str(DECODER)]!=DECODER_SHA or before[str(TEST)]!=TEST_SHA:raise ValueError('Held local source mismatch')
    response=subprocess.run(['gh','api',API],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    remote=json.loads(response.stdout)
    if remote.get('encoding')!='base64':raise ValueError('Unexpected official source encoding')
    raw=base64.b64decode(remote['content'])
    if sha(raw)!=OFFICIAL_SHA:raise ValueError('Official whole-source SHA mismatch')
    source=raw.decode('utf-8')
    original,current,count=method(source,'getAdcResult(range: number, adcVal: number): number {','function(range, adcVal) {')
    meta_original,parse_meta,meta_count=method(source,'parseMeta(meta: any) {','function(meta) {')
    if count!=5 or meta_count!=0:raise ValueError('Unexpected TypeScript non-null annotations')
    defaults=re.findall(r'public modifiers: modifiers = (\{.*?\});',source,re.S)
    if len(defaults)!=1:raise ValueError('Official defaults extraction not unique')
    adc_multiplier=re.findall(r'private adcMult = ([^;]+);',source)
    if len(adc_multiplier)!=1:raise ValueError('Official ADC scale extraction not unique')
    cases=scenarios()
    request=dict(current=current,parse_meta=parse_meta,defaults=defaults[0],adc_multiplier=adc_multiplier[0],cases=cases)
    encoded=json.dumps(request,separators=(',',':')).encode()
    node=subprocess.run(['node','-e',NODE],input=encoded,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False,timeout=60)
    if node.returncode:raise RuntimeError('Node pure-method driver failed: '+node.stderr.decode())
    official=json.loads(node.stdout)
    spec=importlib.util.spec_from_file_location('ppk2_cross_language_target',DECODER)
    target=importlib.util.module_from_spec(spec);spec.loader.exec_module(target)
    summaries=[];mismatches=[]
    for test,reference in zip(cases,official,strict=True):
        if test['name']!=reference['name']:raise ValueError('Case ordering changed')
        decoder=target.Decoder(test['metadata'],test['volts'],test['policy'],test['filter'])
        effective={k.lower():v for k,v in decoder.coef.items()}
        if effective!=reference['effective']:raise ValueError('Effective coefficient disagreement')
        actual=[struct.pack('>d',decoder.current_ua(adc,r)).hex() for adc,r in test['samples']]
        bad=[i for i,(a,b) in enumerate(zip(actual,reference['bits'],strict=True)) if a!=b]
        for i in bad[:8]:
            if len(mismatches)<32:mismatches.append(dict(case=test['name'],sample=i,adc=test['samples'][i][0],
                range=test['samples'][i][1],python_bits=actual[i],official_js_bits=reference['bits'][i]))
        summaries.append(dict(case=test['name'],samples=len(actual),bitwise_mismatches=len(bad),
            python_bits_sha256=sha(''.join(actual).encode()),official_bits_sha256=sha(''.join(reference['bits']).encode())))
    after={str(path):sha(path.read_bytes()) for path in (Path(__file__).resolve(),DECODER,TEST)}
    if before!=after:raise ValueError('Local source changed during crosscheck')
    total_bad=sum(s['bitwise_mismatches'] for s in summaries)
    result=dict(schema=1,kind='ppk2_offline_cross_language_arithmetic_review',passed=total_bad==0,
        official_source_url=f'https://github.com/NordicSemiconductor/pc-nrfconnect-ppk/blob/{COMMIT}/src/device/serialDevice.ts',
        official_source_sha256=sha(raw),official_version='4.4.1',official_current_method_sha256=sha(original.encode()),
        official_parse_metadata_method_sha256=sha(meta_original.encode()),current_signature_type_edits=1,
        parse_metadata_signature_type_edits=1,non_null_assertions_removed=count,defaults_from_original_source=True,
        adc_multiplier_from_original_source=adc_multiplier[0],
        hardware_initialization_extracted=False,source_bookends=before,source_bookends_equal=True,
        node_version=subprocess.run(['node','--version'],check=True,stdout=subprocess.PIPE,timeout=10).stdout.decode().strip(),
        python_version=sys.version,synthetic_cases=len(cases),synthetic_samples=sum(s['samples'] for s in summaries),
        filter_modes=['none via fresh official state','nordic-4.4.1 via carried official state'],
        exact_binary64_comparison=True,bitwise_mismatches=total_bad,cases=summaries,first_mismatches=mismatches,
        node_driver_sha256=sha(NODE.encode()),input_and_extracted_method_sha256=sha(encoded),
        hardware_accessed=False,serial_opened=False,power_changed=False,physical_accuracy_verified=False,
        full_gui_initialization_replayed=False,research_measurement_accepted=False,actual_return_code=None)
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0 if total_bad==0 else 1


if __name__=='__main__':sys.exit(main())
