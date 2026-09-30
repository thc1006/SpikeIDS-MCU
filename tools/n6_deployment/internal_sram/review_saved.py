#!/usr/bin/env python3
"""Review retained compiler output; never generate, compile C, or execute target."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent;SELF=Path(__file__).resolve()
OLD=HERE/'generate.py'
OLD_SHA='673fae4638731a6f0edbe45c5ef8e61c152e57b52ce1afae38e4224901cbf19a'
raw=OLD.read_bytes()
if hashlib.sha256(raw).hexdigest()!=OLD_SHA:raise RuntimeError('Frozen generator changed')
g=importlib.util.module_from_spec(importlib.util.spec_from_file_location('frozen_sram_673',OLD))
exec(compile(raw,str(OLD),'exec'),g.__dict__)
v=g.v;require=v.require
RUNTIME={
 'Middlewares/ST/AI/Npu/ll_aton/ll_aton.h':'d8a70bceaa40d016a11680fe65e3adec6ad0bff87987d54a8d3018fb555ccbc2',
 'Middlewares/ST/AI/Npu/ll_aton/ll_aton.c':'9cdd88f5ac450c65a48e164608b59ca215df3dd3afe74fd4572ebbe5b7b7f7e2'}

# Visible copy of frozen placement validation. The sole body delta is removal
# of the explicit-cache-designator loop; descriptors() supplies its stricter
# typed aggregate replacement. No runtime AST transformation is used.
load_json=g.load_json;integer=g.integer;POOLS=g.POOLS

def placement(directory):
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
    require(v.inventory(directory)==before,'Generated bytes changed during validation')
    return {'pools':observed,'buffer_count':len(buffers),'initializer_file':raw_name,
            'initializer_sha256':before['files'][raw_name]['sha256'],'footprint':foot,
            'mapping':mapping,'epochs':epochs,'address_expressions_checked':len(calls),
            'generated_metadata_and_address_scope_checked':True,'numerical_equivalence_verified':False}


FIELDS=set('dir raw raw_out continuous noblk noinc align_right mem_lsb sync_with_other nbits_unsigned bus_cid cacheable cache_allocate bus_pfetch cache_linesize cipher_en key_sel sync_dma addr_base offset_start offset_end offset_limit frame_count fwidth fheight batch_depth batch_offset frame_offset line_offset loop_offset frame_loop_cnt loop_offset2 frame_loop_cnt2 frame_tot_cnt nbits_in nbits_out'.split())
UINT=r'(?:0[xX][0-9a-fA-F]+|0|[1-9][0-9]*)(?:UL|U|L)?'

def number(text):
    require(re.fullmatch(UINT,text.strip()) is not None,'Nonliteral descriptor integer')
    value=int(re.sub(r'(?:UL|U|L)$','',text.strip()),0) if text.strip().lower().startswith('0x') else int(re.sub(r'(?:UL|U|L)$','',text.strip()),10)
    require(0<=value<=0xffffffff,'Descriptor uint32 overflow');return value

def descriptors(text,pools):
    """Narrow generated dialect, not a general C evaluator or DMA simulator."""
    code=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    forbidden=FIELDS|{'LL_Streng_TensorInitTypeDef','LL_Streng_TensorInit','static','const'}
    for name in re.findall(r'^\s*#\s*define\s+(\w+)',code,re.M):require(name not in forbidden,'Descriptor macro substitution')
    pattern=r'\bstatic\s+const\s+LL_Streng_TensorInitTypeDef\s+(\w+)\s*=\s*\{(.*?)\}\s*;'
    declarations=list(re.finditer(pattern,code,re.S));require(declarations,'No static descriptor aggregates')
    require(len(declarations)==len(re.findall(r'\bLL_Streng_TensorInitTypeDef\b',code)),'Alternate/nonconst descriptor type')
    records=[];names=set();cache_tokens=0
    for match in declarations:
        name,body=match.groups();require(name not in names,'Duplicate descriptor');names.add(name)
        require(len(re.findall(r'\b'+re.escape(name)+r'\b',code))==2,'Descriptor alias/write/extra reference')
        fields={};position=0
        member=re.compile(r'\s*\.(\w+)\s*=\s*(\{[^{}]*\}|[^,{}]+)\s*,',re.S)
        while position<len(body):
            if not body[position:].strip():break
            m=member.match(body,position);require(m is not None,'Unsupported aggregate member syntax')
            key,value=m.groups();require(key in FIELDS and key not in fields,'Unknown/duplicate descriptor member')
            if key=='addr_base':
                addr=re.fullmatch(r'\{\s*\(\s*unsigned\s+char\s*\*\s*\)\s*\(\s*('+UINT+r')\s*\)\s*\}',value)
                if addr is None:
                    addr=re.fullmatch(r'\{\s*\(\s*unsigned\s+char\s*\*\s*\)\s*ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR\(\s*('+UINT+r')\s*\)\s*\}',value)
                require(addr is not None,'Unknown DMA base expression');fields[key]=number(addr[1])
            else:fields[key]=number(value)
            position=m.end()
        require({'addr_base','dir','offset_start','offset_end','offset_limit'}<=fields.keys(),'Missing DMA extent/role')
        for key in ('cacheable','cache_allocate','bus_pfetch','cache_linesize','cipher_en'):
            require(fields.get(key,0)==0,'Enabled descriptor cache/prefetch/cipher')
        cache_tokens+=sum(k in fields for k in ('cacheable','cache_allocate'))
        base=fields['addr_base'];matching=[p for p in pools.values() if int(p['address'])==base]
        require(len(matching)==1,'DMA base not exact declared pool')
        pool=matching[0];start,end,limit=(fields[k] for k in ('offset_start','offset_end','offset_limit'))
        require(fields['dir'] in (0,1) and (fields['dir']==0 or pool['rights']=='ACC_WRITE'),'DMA write into weights')
        require(0<=start<end<=pool['used_size_bytes'],'DMA data interval exceeds used pool')
        require(end<=limit<=pool['size_bytes'],'DMA prefetch stop exceeds reserved pool')
        require(fields.get('raw',0)==1,'Only raw DMA dialect reviewed')
        records.append({'name':name,'pool':pool['name'],'fields':fields,
          'effective_cacheable':fields.get('cacheable',0),'effective_cache_allocate':fields.get('cache_allocate',0),
          'cache_members_explicit':{k:k in fields for k in ('cacheable','cache_allocate')},
          'prefetch_limit_beyond_used_bytes':max(0,limit-pool['used_size_bytes'])})
    calls=re.findall(r'\bLL_Streng_TensorInit\s*\(\s*('+UINT+r')\s*,\s*&\s*(\w+)\s*,\s*1\s*\)\s*;',code)
    require(len(calls)==len(re.findall(r'\bLL_Streng_TensorInit\s*\(',code))==len(records),'Unknown/unmatched descriptor call')
    require(Counter(name for _,name in calls)==Counter(names),'Descriptor call binding')
    require(len(re.findall(r'\.\s*(?:cacheable|cache_allocate)\b',code))==cache_tokens,'Cache assignment outside fixed aggregate')
    return records

def validate(directory):
    before=v.inventory(directory)
    observed=placement(directory)
    records=descriptors((directory/f'{v.NAME}.c').read_text(),observed['pools'])
    require(v.inventory(directory)==before,'Saved generated artifacts changed')
    return {'placement':observed,'dma_descriptors':records,'dma_descriptor_count':len(records),
        'cache_semantics':'zero-valued omitted scalar members in static const designated aggregate',
        'full_dma_traversal_simulated':False,'hardware_register_state_verified':False,
        'reserved_pool_exclusion_required':True}

def audit(candidate):
    candidate=Path(candidate);require(candidate==g.OUTPUT_PARENT/'internal_sram_actual_01','Only retained actual01')
    snapshot_path=HERE/'ACTUAL_01_REVIEW_SNAPSHOT.json'
    pins={str(p):v.snapshot(p) for p in (SELF,OLD,g.HELPER,HERE/'ACTUAL_01_EXECUTION.json',snapshot_path)}
    require(pins[str(OLD)]['sha256']==OLD_SHA,'Generator source pin')
    require(pins[str(HERE/'ACTUAL_01_EXECUTION.json')]['sha256']=='306855057d1eb069a7a0dd60293cdd13c57685b3505e2328f19508092ff3b2b1','External exit binding')
    require(pins[str(snapshot_path)]['sha256']=='ddf5338a4724bb5ec25487fd1a1f28426d49689dd538419304d6d02d23513d75','Independent retained snapshot binding')
    for rel,digest in RUNTIME.items():
        p=v.INSTALL/rel;pin=v.snapshot(p);require(pin['sha256']==digest,'Runtime definition changed');pins[str(p)]=pin
    original=v.inventory(candidate)
    retained=g.load_json(snapshot_path)
    mapping={'device':'st_dev','inode':'st_ino','size':'st_size','mtime_ns':'st_mtime_ns',
             'ctime_ns':'st_ctime_ns','mode':'st_mode','links':'st_nlink','sha256':'sha256'}
    require(all(set(pin)==set(mapping.values()) for pin in retained['files'].values()),'Snapshot field domain')
    converted={name:{key:pin[field] for key,field in mapping.items()} for name,pin in retained['files'].items()}
    require(retained['root']==str(candidate) and original=={'files':converted,'directories':retained['directories']},'Original retained artifact snapshots differ')
    require('RESULT.json' not in original['files'],'Original failure unexpectedly replaced')
    for name,digest in [('FAILED.json','e0f185738bef0ee8a48a12371a9cf8ea097cba8937318e3655da0787a75210d5'),
                        ('generate.json','83f7b960b9509b5bc1ea91b8345d0618d8cf602d199fa4ad963a86a13a1e2a3a')]:
        require(original['files'][name]['sha256']==digest,'Original failure/process record changed')
    intent=g.load_json(candidate/'INTENT.json');held=intent['held_inputs_source_tools']
    require(held[str(OLD)]['sha256']==OLD_SHA,'Original invocation source')
    v.recheck(held);observed=validate(candidate/'generate')
    v.recheck({**held,**pins});require(v.inventory(candidate)==original,'Retained failure namespace changed')
    allpins={**held,**pins,**{str(candidate/n):p for n,p in original['files'].items()}}
    for name,pin in allpins.items():
        now=v.stat_record(Path(name).lstat());require(now=={k:pin[k] for k in now},'Final original stat change')
    names=[];dirs=[]
    for base,children,files in g.os.walk(candidate,followlinks=False):
        for name in children:
            item=Path(base)/name;require(g.stat.S_ISDIR(item.lstat().st_mode),'Final nonordinary directory');dirs.append(str(item.relative_to(candidate)))
        names.extend(str((Path(base)/name).relative_to(candidate)) for name in files)
    require(set(names)==set(original['files']) and sorted(dirs)==original['directories'],'Final retained namespace change')
    return {'schema':1,'kind':'saved_internal_sram_candidate_review','actual_process_exit':None,
        'original_wrapper_return_code':1,'original_compiler_return_code':0,'original_failure_preserved':True,
        'held_inputs_and_reviewer_sources':{**held,**pins},'retained_failure_inventory':original,
        'observations':observed,'saved_descriptor_review_passed':True,**g.LIMITS}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);p.add_argument('--candidate',type=Path,required=True)
    args=p.parse_args(argv)
    try:result=audit(args.candidate)
    except Exception as exc:print(str(exc),file=sys.stderr);return 1
    print(json.dumps(result,sort_keys=True,indent=2,allow_nan=False));return 0
if __name__=='__main__':raise SystemExit(main())
