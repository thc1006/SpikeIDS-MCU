"""Bounded offline host-C controls and ARM object checks. No target/device I/O."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
ST=Path('/home/thc1006/opt/stedgeai/3.0/Middlewares/ST/AI')
RT=ST/'Npu/ll_aton'
GEN=REPO/'results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate'
TC=Path('/home/thc1006/opt/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi/bin')
FIXED={
 GEN/'nsl_qcfs_seed0.c':'8b7a8703240811f4b4f12517f33ce5c77bc004911c088514435340bc92c3b43e',
 GEN/'stai_nsl_qcfs_seed0.c':'32c26141b873b1265d02d2966ce2323ec2506d7d3de02036a31cd7989e0b467c',
 RT/'ll_aton_stai_internal.c':'0c3005eb626bb7409cc73db3293453d7bdac6b93051fa9060e1954397f3b7c18',
 RT/'ll_aton_runtime.c':'198a0a536e9db7427511ab41b95462c94caea07c47241840354e3ab7a259462d',
 RT/'ll_aton_NN_interface.h':'ce8beece610de46ca31d3f215f09b82038384b5f754710be8b25bc05e533a580',
 RT/'ll_aton_lib.c':'2e30a045a58e6680ff767ef7b7e0a3050f87a3b263250f1a2a6d70da6b267e7a'}
DEFS=['-DSTM32N657xx','-DCORE_CM55','-DLL_ATON_PLATFORM=LL_ATON_PLAT_STM32N6','-DLL_ATON_OSAL=LL_ATON_OSAL_BARE_METAL',
      '-DLL_ATON_RT_MODE=LL_ATON_RT_POLLING','-DLL_ATON_SW_FALLBACK=1']
INCLUDES=['-I'+str(HERE)]+[part for p in (ST/'Inc',RT,GEN,ST/'Npu/Devices/STM32N6xx',
    REPO/'firmware/n6/third_party/CMSIS_6/CMSIS/Core/Include',
    REPO/'firmware/n6/third_party/cmsis-device-n6/Include',
    REPO/'firmware/n6/third_party/stm32n6xx-hal-driver/Inc',REPO/'firmware/n6b/hal_conf') for part in ('-isystem',str(p))]

def pin(path):
    path=Path(path)
    with path.open('rb') as f:
        before=os.fstat(f.fileno());digest=hashlib.file_digest(f,'sha256').hexdigest();after=os.fstat(f.fileno())
    keys=('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
    assert path==path.resolve() and path.is_file()
    assert all(getattr(before,k)==getattr(after,k)==getattr(path.stat(),k) for k in keys)
    return {**{k:getattr(before,k) for k in keys},'sha256':digest}

def run(out):
    assert out.parent==HERE and out==out.resolve() and not out.exists()
    own=[HERE/n for n in ('check.py','npu_trace.c','npu_trace.h','npu_trace_bind.c','test_npu_trace.c')]
    held={str(p):pin(p) for p in own+list(FIXED)}
    for p,sha in FIXED.items():assert held[str(p)]['sha256']==sha
    host=Path('/usr/bin/cc').resolve();arm=(TC/'arm-none-eabi-gcc').resolve()
    for p in (host,arm):held[str(p)]=pin(p)
    out.mkdir(mode=0o700);calls=[]
    def save(name,obj):
        with (out/name).open('xb') as f:f.write((json.dumps(obj,indent=2,sort_keys=True)+'\n').encode())
    def call(label,args):
        with (out/(label+'.stdout')).open('xb') as a,(out/(label+'.stderr')).open('xb') as b:
            try:
                cp=subprocess.run([str(x) for x in args],stdout=a,stderr=b,stdin=subprocess.DEVNULL,
                                  cwd=out,timeout=45,check=False)
                row=dict(argv=[str(x) for x in args],actual_return_code=cp.returncode,timed_out=False)
            except subprocess.TimeoutExpired:
                row=dict(argv=[str(x) for x in args],actual_return_code=None,timed_out=True)
        calls.append(row);save(label+'.json',row)
        if row['actual_return_code']!=0:raise RuntimeError('Command failed: '+label)
        return (out/(label+'.stdout')).read_text()
    def bookend():
        for p,expected in held.items():assert pin(p)==expected,p
        for p,expected in held.items():
            st=Path(p).stat();assert all(getattr(st,k)==v for k,v in expected.items() if k!='sha256'),p
    try:
        # Independently derive the literal model descriptor projection from pinned C text.
        source=(GEN/'nsl_qcfs_seed0.c').read_text()
        body=source.split('static const EpochBlock_ItemTypeDef ll_atonn_rt_epoch_block_array[] = {',1)[1].split('return ll_atonn_rt_epoch_block_array;',1)[0]
        entries=re.findall(r'\{(.*?)\}',body,re.S);assert len(entries)==41
        rows=[]
        for i,e in enumerate(entries[:-1]):
            kind=re.search(r'Flags_(pure_sw|pure_hw|hybrid)',e)[1]
            rows.append(dict(index=i,compiler_epoch=int(re.search(r'\.epoch_num = (\d+)',e)[1]),
                             flags={'pure_sw':35,'pure_hw':19,'hybrid':67}[kind],
                             wait_mask=int(re.search(r'\.wait_mask = (0x[0-9a-fA-F]+)',e)[1],16),kind=kind))
        assert entries[-1].strip()=='.flags = EpochBlock_Flags_last_eb,'
        target=(HERE/'npu_trace.c').read_text()
        for name,key in [('epoch_numbers','compiler_epoch'),('expected_flags','flags'),('expected_wait','wait_mask')]:
            values=re.search(r'\b'+name+r'\[NPU_TRACE_EPOCHS\]=\{(.*?)\};',target,re.S)[1]
            assert [int(x) for x in re.findall(r'\d+',values)]==[r[key] for r in rows]
        save('MODEL_DESCRIPTOR_PROJECTION.json',dict(rows=rows,terminating_sentinel_index=40,
          sentinel_executes=False,expected_epoch_callback_events=160,expected_lifecycle_events=[5,4],
          expected_total_callback_events=162,model_file_sha256=FIXED[GEN/'nsl_qcfs_seed0.c']))
        call('host_version',[host,'--version']);version=call('arm_version',[arm,'--version'])
        assert version.splitlines()[0]=='arm-none-eabi-gcc (Arm GNU Toolchain 13.2.rel1 (Build arm-13.7)) 13.2.1 20231009'
        base=['-std=c11','-O2','-Wall','-Wextra','-Werror',*INCLUDES,*DEFS]
        armflags=['-mcpu=cortex-m55','-mthumb','-mfloat-abi=hard','-mfpu=auto','-mcmse']
        for label,cc,flags,names in [('host',host,['-DNPU_TRACE_HOST_CONTROL'],['npu_trace','npu_trace_bind','test_npu_trace']),
                                    ('arm',arm,armflags,['npu_trace','npu_trace_bind'])]:
            for name in names:
                dep=out/(label+'_'+name+'.d')
                call(label+'_deps_'+name,[cc,*base,*flags,'-M','-MF',dep,HERE/(name+'.c')])
                for item in shlex.split(dep.read_text().replace('\\\n',' ').split(':',1)[1]):
                    p=Path(item).resolve();got=pin(p)
                    if str(p) in held:assert held[str(p)]==got
                    else:held[str(p)]=got
        bookend();save('COMPILE_INPUTS.json',held)
        exe=out/'host_controls'
        call('host_compile',[host,*base,'-DNPU_TRACE_HOST_CONTROL',HERE/'npu_trace.c',HERE/'npu_trace_bind.c',HERE/'test_npu_trace.c','-o',exe])
        controls=json.loads(call('host_controls',[exe]))
        assert controls['host_control_tests_passed']>=30 and controls['hardware_executed'] is False
        for name in ('npu_trace','npu_trace_bind'):
            obj=out/(name+'.o');call('arm_compile_'+name,[arm,*base,*armflags,'-c',HERE/(name+'.c'),'-o',obj])
            raw=obj.read_bytes();assert raw[:7]==b'\x7fELF\x01\x01\x01' and struct.unpack_from('<HH',raw,16)==(1,40)
        bookend()
        save('RESULT.json',dict(schema=1,kind='offline_npu_trace_module_check',host_controls=controls,
            original_input_pins=held,calls=calls,artifact_sha256_before_result={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()},
            arm_relocatable_objects_only=True,full_firmware_linked=False,generated_model_executed=False,
            hardware_executed=False,hardware_independently_proven=False,performance_accepted=False,
            limits=['Host callbacks and generated registration are synthetic, not live runtime execution.',
                    'Dependency headers pinned after preprocessing and before compilation; not a complete host/compiler runtime environment attestation.']))
        bookend();return controls
    except BaseException as exc:
        save('FAILED.json',dict(error=str(exc),calls=calls,hardware_executed=False));raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);p.add_argument('--output',type=Path,required=True)
    print(json.dumps(run(p.parse_args().output)))
