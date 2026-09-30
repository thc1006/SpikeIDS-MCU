#!/usr/bin/env python3
"""One fixed-model, offline internal-SRAM ST generate call. Never execute target."""
from __future__ import annotations
import argparse
import ast
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import zipfile

SELF=Path(__file__).resolve();HERE=SELF.parent;REPO=HERE.parents[2]
HELPER=HERE.parent/'prepare_vendor.py'
HELPER_SHA='cd1bb490fa913d0ffde3c5c59ff8108134537228ded9ec130e5ac17939f7a94f'
raw=HELPER.read_bytes()
if hashlib.sha256(raw).hexdigest()!=HELPER_SHA: raise RuntimeError('Wrong vendor helper source')
v=importlib.util.module_from_spec(importlib.util.spec_from_file_location('held_vendor_helper',HELPER))
exec(compile(raw,str(HELPER),'exec'),v.__dict__)
OUTPUT_PARENT=REPO/'results/ppk2_n6_bringup_20260925_nAivHM'
PROFILE_HASHES={'internal_sram.mpool':'4969fd25574d5db4e603080f9fa03ef092b12ffa7b26b29bc65aab22daf94a15',
                'neural_art.json':'64fb217c2a0fce1452f97b21ac31dd74f07149a0d5e7d25cce68fbe1e9c959f9'}
DOC_HASHES={'Documentation/stneuralart_memory_initializers.html':'1236cd79f6b32f3bb3a3e8d9df8c949e546c8e04d4e9ff382c663157316403d9',
 'Documentation/stneuralart_neural_art_compiler.html':'20215905ac72e08e614ea0a751cf81821a78f1468ddb4384aa8287458453dfe9',
 'scripts/N6_reloc/test/mpools/stm32n6_int2.mpool':'dcce1bb3221edfbf8634501a86c2181fc129fbf028c094e0dfd267533abf3d2f'}
POOLS={'weights_sram':(0x34200000,0x40000,'ACC_READ','SRAM_WEIGHTS',True),
       'activations_sram':(0x34240000,0x4000,'ACC_WRITE','SRAM_ACTIVATIONS',False)}
LIMITS={**v.LIMITS,'platform_initialized':False,'hardware_executed':False,
        'numerical_equivalence_verified':False,'original_export_matrix_changed':False}
require=v.require

def load_json(path):
    def pairs(items):
        out={}
        for k,val in items:
            require(k not in out,'Duplicate JSON key');out[k]=val
        return out
    return json.loads(path.read_bytes(),object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

def integer(n,minimum=0):
    require(type(n) is int and n>=minimum,'Expected typed integer');return n

def reference_headers(path):
    expected={'x.npy':('<f4',(1024,41)),'reference_logits.npy':('<f4',(1024,5)),
              'original_logits.npy':('<f4',(1024,5)),'validation_row_ids.npy':('<i8',(1024,))}
    with zipfile.ZipFile(path) as z:
        require(len(z.namelist())==4 and set(z.namelist())==set(expected),'Reference archive names')
        for name,(dtype,shape) in expected.items():
            with z.open(name) as f:
                magic=f.read(8);require(magic[:6]==b'\x93NUMPY' and magic[6:] in (b'\x01\x00',b'\x02\x00'),'NPY version')
                size=int.from_bytes(f.read(2 if magic[6]==1 else 4),'little')
                require(0<size<=4096,'NPY header size')
                h=ast.literal_eval(f.read(size).decode('latin1'))
                require(h=={'descr':dtype,'fortran_order':False,'shape':shape} and
                        h['fortran_order'] is False and all(type(n) is int for n in h['shape']),'Reference shape/type')
    return {k:{'dtype':d,'shape':list(s)} for k,(d,s) in expected.items()}

def capture_inputs():
    pins={str(SELF):v.snapshot(SELF),str(HERE/'PLAN.md'):v.snapshot(HERE/'PLAN.md')}
    pins.update(v.capture_inputs())
    require(pins[str(HELPER)]['sha256']==HELPER_SHA,'Helper changed after import')
    for base,expected in ((HERE,PROFILE_HASHES),(v.INSTALL,DOC_HASHES)):
        for rel,digest in expected.items():
            p=base/rel;pin=v.snapshot(p);require(pin['sha256']==digest,'Fixed configuration/source SHA changed');pins[str(p)]=pin
    refs=reference_headers(v.PAYLOAD/'validation_vectors.npz')
    v.recheck(pins);return pins,refs

def command(output):
    return [str(v.TOOL),'generate','--model',str(output/'model_qdq_int8.onnx'),'--type','onnx',
        '--target','stm32n6','--name',v.NAME,'--st-neural-art',f'internal_sram@{output / "neural_art.json"}',
        '--c-api','st-ai','--input-data-type','float32','--output-data-type','float32','--compression','lossless',
        '--optimization','balanced','--workspace',str(output/'generate_workspace'),'--output',str(output/'generate'),
        '--verbosity','2','--binary']

def invoke(owner,pins):
    owner.guard();v.recheck({**pins,**owner.pins})
    r={'phase':'generate','argv':command(owner.path),'cwd':str(owner.path),'environment':v.environment(owner.path),
       'actual_return_code':None,'timed_out':False,'exception':None}
    start=time.monotonic();proc=None
    with owner.open_new('generate.stdout') as stdout,owner.open_new('generate.stderr') as stderr:
        try:
            proc=subprocess.Popen(r['argv'],cwd=owner.path,env=r['environment'],stdin=subprocess.DEVNULL,
                                  stdout=stdout,stderr=stderr,start_new_session=True,close_fds=True)
            try:proc.wait(timeout=900)
            except subprocess.TimeoutExpired:
                r['timed_out']=True;os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=10)
        except BaseException as exc:
            r['exception']=f'{type(exc).__name__}: {exc}'
        finally:
            if proc is not None and proc.poll() is None:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=10)
            r['actual_return_code']=None if proc is None else proc.returncode
            r['elapsed_seconds']=time.monotonic()-start
            r['stdout']=owner.finish(stdout,'generate.stdout');r['stderr']=owner.finish(stderr,'generate.stderr')
    owner.write('generate.json',v.encoded(r))
    require(r['exception'] is None and r['timed_out'] is False and type(r['actual_return_code']) is int and r['actual_return_code']==0,
            'Single compiler call failed; partial output retained, no retry')
    v.recheck({**pins,**owner.pins});owner.guard();return r

def validate_generated(directory):
    before=v.inventory(directory)
    name=v.NAME
    for n in (f'{name}.c',f'{name}.h',f'stai_{name}.c',f'stai_{name}.h',f'{name}_c_info.json',f'{name}_generate_report.txt'):
        require(n in before['files'] and before['files'][n]['size']>0,'Missing generated artifact')
    info=load_json(directory/f'{name}_c_info.json')
    require(info['json_schema_version']=='2.0' and info['ec_blobs_info']==[],'Unsupported metadata/epoch-controller blobs')
    pools=info['memory_pools'];require(type(pools) is list and len(pools)==2,'Exactly two physical pools required')
    byid={};observed={}
    for p in pools:
        require(p['name'] in POOLS and p['name'] not in observed,'Unknown/duplicate pool')
        base,size,rights,fname,is_weights=POOLS[p['name']]
        ident=integer(p['id'],1);require(ident not in byid,'Duplicate pool ID')
        require(type(p['address']) is str and p['address']==str(base),'Pool base')
        require(type(p['size_bytes']) is int and p['size_bytes']==size and p['rights']==rights,'Pool size/rights')
        require(p['cacheable']=='CACHEABLE_OFF' and p['subpools']==[] and p['user_allocated'] is False,'Cache/virtual/user pool')
        require(p['attributes']['use_for_initrs'] is is_weights and p['fname']==f'atonbuf.{fname}.raw','Initializer domain')
        used=integer(p['used_size_bytes'],1);require(used<=size,'Pool overrun')
        byid[ident]=p;observed[p['name']]=p
    buffers=info['buffers'];require(type(buffers) is list and buffers,'Empty buffers')
    ids=set();maxends={n:0 for n in POOLS}
    for buf in buffers:
        ident=integer(buf['id'],1);require(ident not in ids,'Duplicate buffer');ids.add(ident)
        poolid=integer(buf['mpool_id'],1);require(poolid in byid,'Buffer references unlisted pool')
        p=byid[poolid];require(type(buf['is_param']) is bool and buf['is_param']==(p['name']=='weights_sram'),'Weight/activation spill')
        start=integer(buf['offset_start']);size=integer(buf['size_bytes'],1)
        require(start+size<=p['used_size_bytes'],'Buffer beyond used pool')
        alignment=integer(buf['alignment'],1);require(alignment&(alignment-1)==0 and (int(p['address'])+start)%alignment==0,'Buffer alignment')
        maxends[p['name']]=max(maxends[p['name']],start+size)
    for p in pools:
        require(type(p['buffers']) is list and len(p['buffers'])==len(set(p['buffers'])) and
                set(p['buffers'])=={b['id'] for b in buffers if b['mpool_id']==p['id']} and
                all(type(n) is int for n in p['buffers']),'Pool buffer membership')
        require(maxends[p['name']]>0,'Unused role pool')
    foot=info['memory_footprint']
    for key,pool in (('weights','weights_sram'),('activations','activations_sram')):
        require(type(foot[key]) is int and foot[key]==observed[pool]['used_size_bytes'],'Footprint mismatch')
    raw_name=f'{name}_atonbuf.SRAM_WEIGHTS.raw'
    raws={n for n in before['files'] if n.endswith(('.raw','.bin'))}
    require(raws=={raw_name} and before['files'][raw_name]['size']==observed['weights_sram']['used_size_bytes'],'Raw initializer namespace/size')
    graphs=info['graphs'];require(type(graphs) is list and len(graphs)==1,'One graph required')
    graph=graphs[0]
    for key,width in (('original_inputs',41),('original_outputs',5)):
        io=graph[key];require(type(io) is list and len(io)==1,'One input/output required')
        fmt=io[0]['data_format']
        require(io[0]['shape']==[1,width] and all(type(n) is int for n in io[0]['shape']) and
                fmt['type']=='FLOAT' and type(fmt['size']) is int and fmt['size']==32 and fmt['quantizer']=='NONE','41/5 FP32 interface')
    for key,width in (('inputs',41),('outputs',5)):
        role=graph[key];require(type(role) is list and len(role)==1,'One allocated input/output required')
        ident=integer(role[0],1);require(ident in ids,'Allocated I/O buffer missing')
        buf=next(b for b in buffers if b['id']==ident)
        require(byid[buf['mpool_id']]['name']=='activations_sram' and buf['is_param'] is False and
                buf['shape']==[1,width] and all(type(n) is int for n in buf['shape']) and
                buf['format']=='STAI_FORMAT_FLOAT' and type(buf['nbits']) is int and buf['nbits']==32 and
                buf['size_bytes']==4*width,'Allocated 41/5 FP32 interface')
    mapping=v.mapping_report(directory/f'{name}_generate_report.txt')
    kinds={'NODE_SW':'software','NODE_SW_HW':'hybrid','NODE_HW':'hardware'}
    counts=Counter();epochs=[];nodeids=set()
    for node in graph['nodes']:
        ident=integer(node['id'],1);require(ident not in nodeids,'Duplicate graph node');nodeids.add(ident)
        k=node['mapping'];require(k in kinds or k=='NODE_NO_X','Unknown epoch mapping')
        if k in kinds:counts[kinds[k]]+=1;epochs.append({'id':ident,'name':node['name'],'mapping':k})
    expected={**{k:counts[k] for k in kinds.values()},'total':len(epochs)}
    require(mapping['reported_epochs']==expected and len(epochs)>0,'Epoch log/metadata mismatch')
    # Fixed generated-C dialect: validate actual absolute address expressions,
    # and reject other address-like literals after removing comments/strings.
    text=(directory/f'{name}.c').read_text()
    code=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"','',text,flags=re.S)
    hexes=[int(x,16) for x in re.findall(r'0x([0-9a-fA-F]+)',code)]
    address=lambda n:any(base<=n<base+size for base,size,*_ in POOLS.values())
    for n in hexes:
        if 0x10000000<=n<0xe0000000:require(address(n),'Generated out-of-pool address literal')
    calls=re.findall(r'ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR\(\s*(0x[0-9a-fA-F]+)(?:UL|U|L)?\s*(?:\+\s*(\d+))?\s*\)',code)
    require(calls and len(calls)==code.count('ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR('),'Unsupported/unobserved address expression')
    for base,off in calls:
        base=int(base,16);pointer=base+int(off or 0)
        require(any(int(p['address'])<=base<=pointer<int(p['address'])+p['used_size_bytes']
                    for p in pools),'Generated pointer used-range')
    for field in ('cacheable','cache_allocate'):
        values=re.findall(r'\.'+field+r'\s*=\s*([^,}\n]+)',code)
        require(values and all(re.fullmatch(r'0(?:U|UL|L)?',value.strip()) for value in values),'Generated cache field enabled/missing')
    require(v.inventory(directory)==before,'Generated bytes changed during validation')
    return {'pools':observed,'buffer_count':len(buffers),'initializer_file':raw_name,
            'initializer_sha256':before['files'][raw_name]['sha256'],'footprint':foot,
            'mapping':mapping,'epochs':epochs,'address_expressions_checked':len(calls),
            'generated_metadata_and_address_scope_checked':True,'numerical_equivalence_verified':False}

def run(output):
    output=Path(output);v.canonical(output)
    require(output.parent==OUTPUT_PARENT and re.fullmatch(r'internal_sram_actual_[0-9]{2}',output.name),'Fixed output parent/name required')
    pins,refs=capture_inputs();owner=v.Output(output)
    try:
        for n in ('tmp','cache','generate','generate_workspace'):owner.directory(n)
        owner.write('INTENT.json',v.encoded({'schema':1,'kind':'offline_internal_sram_generation_intent',
                    'held_inputs_source_tools':pins,'reference_headers':refs,'single_generate_only':True,**LIMITS}))
        for name,source,digest in [('model_qdq_int8.onnx',v.PAYLOAD/'model_qdq_int8.onnx',v.INPUT_HASHES['model_qdq_int8.onnx'])]+[
            (name,HERE/name,digest) for name,digest in PROFILE_HASHES.items()]:
            p=owner.write(name,source.read_bytes());require(p['sha256']==digest,'Copied fixed input mismatch')
        call=invoke(owner,pins)
        generated_before=v.inventory(output/'generate')
        observations=validate_generated(output/'generate')
        require(v.inventory(output/'generate')==generated_before,'Generated namespace changed')
        artifacts=v.inventory(output);require('FAILED.json' not in artifacts['files'],'Failure marker exists')
        v.recheck({**pins,**owner.pins})
        result={'schema':1,'kind':'offline_n6_internal_sram_candidate','actual_process_exit':None,
                'offline_generation_completed':True,'model_sha256':v.INPUT_HASHES['model_qdq_int8.onnx'],
                'expected_tool_version':v.VERSION,'reference_headers':refs,'call':call,'observations':observations,
                'held_inputs_source_tools':pins,'artifacts_before_result':artifacts,**LIMITS}
        result['content_sha256']=hashlib.sha256(v.encoded(result)).hexdigest()
        own=owner.write('RESULT.json',v.encoded(result))
        expected={'files':{**artifacts['files'],'RESULT.json':own},'directories':artifacts['directories']}
        require(v.inventory(output)==expected,'Late output namespace/bytes change')
        v.recheck({**pins,**owner.pins,**{str(output/n):p for n,p in expected['files'].items()}})
        owner.guard();require(v.inventory(output)==expected,'Final output namespace change');v.recheck(pins)
        # No more hash callbacks: compare original pins and exact names directly.
        owner.guard()
        allpins={**pins,**{str(output/n):p for n,p in expected['files'].items()}}
        for name,pin in allpins.items():
            require(v.stat_record(Path(name).lstat())=={k:pin[k] for k in v.stat_record(Path(name).lstat())},'Final original stat change')
        names=[];dirs=[]
        for base,children,files in os.walk(output,followlinks=False):
            for name in children:
                item=Path(base)/name;require(stat.S_ISDIR(item.lstat().st_mode),'Final nonordinary directory');dirs.append(str(item.relative_to(output)))
            names.extend(str((Path(base)/name).relative_to(output)) for name in files)
        require(set(names)==set(expected['files']) and sorted(dirs)==expected['directories'],'Final exact namespace change')
        return result
    except BaseException as exc:
        try:owner.guard();owner.write('FAILED.json',v.encoded({'schema':1,'kind':'offline_internal_sram_candidate_failure','exception':str(exc),**LIMITS}))
        except BaseException:pass
        raise
    finally:owner.close()

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);p.add_argument('--output-dir',required=True,type=Path)
    args=p.parse_args(argv)
    try:r=run(args.output_dir)
    except Exception as exc:print(f'INTERNAL SRAM GENERATION FAILED: {exc}',file=sys.stderr);return 1
    print(json.dumps({'offline_generation_completed':True,'content_sha256':r['content_sha256'],**LIMITS},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
