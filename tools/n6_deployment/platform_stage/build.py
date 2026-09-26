"""Offline ARM stage build. No device transport or target commands.

Fresh results/ output, same-FD retention from the pinned vendor writer; no
vendor/model compiler is run. Actual process exit must be observed externally.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import struct
import subprocess

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
TC=Path('/home/thc1006/opt/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi')
VENDOR=HERE.parent/'prepare_vendor.py'
VENDOR_SHA='cd1bb490fa913d0ffde3c5c59ff8108134537228ded9ec130e5ac17939f7a94f'
CMS=REPO/'firmware/n6/third_party/cmsis-device-n6/Include'
CORE=REPO/'firmware/n6/third_party/CMSIS_6/CMSIS/Core/Include'
HEADERS={CMS/'stm32n6xx.h':'d34dc59f4cc80a17832e628d6fb80f0993cf901047c88524db230011b2bae62d',
         CMS/'stm32n657xx.h':'559792ea50e7253ddb386bd77267e475c7f5ecbccfc917adeea9398ef3aaa689',
         CORE/'core_cm55.h':'512b3fe4e5b9975d4178675ec3411df20f904c395d79f46123afb23517754d53'}
FLAGS=['-mcpu=cortex-m55','-mthumb','-mfloat-abi=soft','-mgeneral-regs-only','-mcmse']
LIMITS=dict(hardware_executed=False,platform_initialized=False,board_ready=False,
            model_executed=False,energy_measured=False,flash_written=False)

def layout(raw,abi):
    if raw[:7]!=b'\x7fELF\x01\x01\x01':raise ValueError('ELF32 LE required')
    h=struct.unpack_from('<16sHHIIIIIHHHHHH',raw)
    if h[2]!=40 or h[8]!=52 or h[9]!=32:raise ValueError('ARM ELF required')
    seg=[]
    for i in range(h[10]):
        p=struct.unpack_from('<IIIIIIII',raw,h[5]+i*h[9])
        if p[0]!=1:continue
        _,off,va,pa,fs,ms,flags,alignment=p
        if va!=pa or fs>ms or off+fs>len(raw):raise ValueError('Invalid PT_LOAD')
        seg.append(dict(address=va,file_offset=off,file_bytes=fs,memory_bytes=ms,flags=flags))
    if len(seg)!=3:raise ValueError('Need code/mailbox/stack segments')
    code,mail,stack=seg
    if not (code['address']==abi['code_start'] and code['flags']==5 and
            code['address']+code['memory_bytes']<=abi['code_end_exclusive']):raise ValueError('Code range')
    for got,address,size in ((mail,abi['mailbox_address'],abi['struct_bytes']),
                             (stack,abi['stack_start'],abi['stack_top']-abi['stack_start'])):
        if got!={**got,'address':address,'file_bytes':0,'memory_bytes':size,'flags':6}:raise ValueError('BSS range')
    sp,reset=struct.unpack_from('<II',raw,code['file_offset'])
    if not (sp==abi['stack_top'] and reset==h[4] and reset&1 and
            code['address']<=reset-1<code['address']+code['file_bytes']):raise ValueError('Vectors/entry')
    return dict(entry_thumb=reset,initial_msp=sp,segments=seg)

def build(output):
    own_before=Path(__file__).read_bytes()
    provider=VENDOR.read_bytes()
    if hashlib.sha256(provider).hexdigest()!=VENDOR_SHA:raise ValueError('Pinned writer changed')
    spec=importlib.util.spec_from_file_location('_stage_held_writer',VENDOR)
    v=importlib.util.module_from_spec(spec);exec(compile(provider,str(VENDOR),'exec'),v.__dict__)
    inputs={str(p):v.snapshot(p) for p in [Path(__file__).resolve(),VENDOR,*HEADERS,
         *(HERE/n for n in ('platform_init.c','platform_init.h','main.c','startup.c','mailbox.h','linker.ld','ABI.json'))]}
    v.require(inputs[str(Path(__file__).resolve())]['sha256']==hashlib.sha256(own_before).hexdigest(),'Build source changed')
    v.require(inputs[str(VENDOR)]['sha256']==VENDOR_SHA,'Writer changed')
    for path,sha in HEADERS.items():v.require(inputs[str(path)]['sha256']==sha,'Header changed')
    abi=json.loads((HERE/'ABI.json').read_bytes())
    tools={n:TC/'bin'/('arm-none-eabi-'+n) for n in ('gcc','objcopy','readelf','objdump','nm','size')}
    for p in tools.values():inputs[str(p)]=v.snapshot(p)
    owner=v.Output(output);calls=[]
    def call(label,args):
        owner.guard();row=dict(argv=[str(a) for a in args],actual_return_code=None,timed_out=False)
        with owner.open_new(label+'.stdout') as stdout,owner.open_new(label+'.stderr') as stderr:
            proc=subprocess.Popen(row['argv'],cwd=output,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                env={'PATH':str(TC/'bin')+':/usr/bin:/bin','LANG':'C','LC_ALL':'C','TMPDIR':str(output)},start_new_session=True)
            try:proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                row['timed_out']=True;os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=10)
            finally:
                if proc.poll() is None:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=10)
                row['actual_return_code']=proc.returncode
                owner.finish(stdout,label+'.stdout');owner.finish(stderr,label+'.stderr')
        calls.append(row);owner.write(label+'.json',v.encoded(row))
        v.require(row['actual_return_code']==0 and not row['timed_out'],'Failed '+label)
        return (output/(label+'.stdout')).read_text()
    try:
        owner.write('INTENT.json',v.encoded(dict(schema=1,kind='offline_platform_stage_build_intent',inputs=inputs,**LIMITS)))
        version=call('version',[tools['gcc'],'--version'])
        v.require(version.splitlines()[0]=='arm-none-eabi-gcc (Arm GNU Toolchain 13.2.rel1 (Build arm-13.7)) 13.2.1 20231009','Compiler version')
        for name in ('cc1','as','ld'):
            p=Path(call('tool_'+name,[tools['gcc'],'-print-prog-name='+name]).strip()).resolve()
            inputs[str(p)]=v.snapshot(p)
        base=[tools['gcc'],*FLAGS,'-DSTM32N657xx','-O2','-g3','-std=c11','-Wall','-Wextra','-Werror',
          '-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-pic','-fno-common',
          '-fno-unwind-tables','-fno-asynchronous-unwind-tables','-fno-tree-loop-distribute-patterns',
          '-ffunction-sections','-fdata-sections','-I'+str(HERE),'-I'+str(CMS),'-I'+str(CORE)]
        for name in ('main','startup','platform_init'):
            dep=output/(name+'.d');call('deps_'+name,[*base,'-M','-MF',dep,HERE/(name+'.c')])
            for item in shlex.split(dep.read_text().replace('\\\n',' ').split(':',1)[1]):
                p=Path(item).resolve();current=v.snapshot(p)
                if str(p) in inputs:v.require(inputs[str(p)]==current,'Dependency changed')
                else:inputs[str(p)]=current
        v.recheck(inputs);owner.write('COMPILE_INPUTS.json',v.encoded(inputs))
        objects=[];object_pins={}
        for name in ('main','startup','platform_init'):
            obj=output/(name+'.o');call('compile_'+name,[*base,'-c',HERE/(name+'.c'),'-o',obj])
            objects.append(obj);object_pins[str(obj)]=v.snapshot(obj)
        v.recheck({**inputs,**object_pins})
        elf=output/'stage.elf'
        call('link',[tools['gcc'],*FLAGS,'-nostdlib','-nostartfiles','-nodefaultlibs','-T',HERE/'linker.ld',
             '-Wl,--gc-sections,--fatal-warnings,--build-id=none','-Wl,-Map='+str(output/'stage.map'),*objects,'-o',elf])
        v.require(not call('undefined',[tools['nm'],'-u',elf]).strip(),'Undefined symbols')
        for label,args in [('symbols',[tools['nm'],'-n','-S',elf]),('readelf',[tools['readelf'],'-h','-l','-S','-A',elf]),
                           ('disassembly',[tools['objdump'],'-d',elf]),('size',[tools['size'],'-A',elf]),
                           ('binary',[tools['objcopy'],'-O','binary',elf,output/'stage.bin'])]:call(label,args)
        raw=elf.read_bytes();elf_layout=layout(raw,abi);code=elf_layout['segments'][0]
        v.require((output/'stage.bin').read_bytes()==raw[code['file_offset']:code['file_offset']+code['file_bytes']],'Binary != ELF code')
        v.recheck({**inputs,**object_pins,**owner.pins});owner.guard()
        artifacts=v.inventory(output)
        result=dict(schema=1,kind='offline_secure_sram_platform_stage_build',compile_link_succeeded=True,
          actual_process_exit=None,source_pins=inputs,artifact_pins_before_result=artifacts,abi=abi,
          elf_layout=elf_layout,calls=calls,**LIMITS)
        result['content_sha256']=hashlib.sha256(v.encoded(result)).hexdigest()
        owner.write('RESULT.json',v.encoded(result))
        v.recheck({**inputs,**owner.pins,**{str(output/n):p for n,p in artifacts['files'].items()}})
        v.require({p.name for p in output.iterdir()}==set(artifacts['files'])|{'RESULT.json'},'Unexpected output')
        v.recheck(inputs);owner.guard();return result
    except BaseException as exc:
        try:owner.write('FAILED.json',v.encoded(dict(error=str(exc),calls=calls,**LIMITS)))
        except BaseException:pass
        raise
    finally:owner.close()

def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--output-dir',required=True,type=Path);args=p.parse_args()
    result=build(args.output_dir)
    print(json.dumps(dict(compile_link_succeeded=True,content_sha256=result['content_sha256'],**LIMITS)))
    return 0
if __name__=='__main__':raise SystemExit(main())
