#!/usr/bin/env python3
"""Bounded offline freestanding build. No device/USB/flash/target commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import struct
import subprocess
import sys

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
TP=REPO/'firmware/n6/third_party'
TC=Path('/home/thc1006/opt/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi')
FLAGS=['-mcpu=cortex-m55','-mthumb','-mfloat-abi=soft','-mgeneral-regs-only','-mcmse']
PINNED={
 str(TP/'cmsis-device-n6/Include/stm32n6xx.h'):'d34dc59f4cc80a17832e628d6fb80f0993cf901047c88524db230011b2bae62d',
 str(TP/'cmsis-device-n6/Include/stm32n657xx.h'):'559792ea50e7253ddb386bd77267e475c7f5ecbccfc917adeea9398ef3aaa689',
 str(TP/'CMSIS_6/CMSIS/Core/Include/core_cm55.h'):'512b3fe4e5b9975d4178675ec3411df20f904c395d79f46123afb23517754d53',
 str(TP/'stm32n6xx-hal-driver/Inc/stm32n6xx_hal.h'):'0bc08f69f86161be2d8bbdf123cf57aef4411286471892fb7c17131cd63f2a32',
 str(REPO/'tools/n6_deployment/firmware_v5/linker.ld'):'7bb333c935a7da04f3758d6df381385c5c4cd994e7b60d427c362c888706532d',
 '/home/thc1006/opt/stedgeai/3.0/Projects/STM32N6570-DK/Applications/SNS/cubeIDE/FSBL/STM32N657X0HXQ_RAM.ld':'321e6275ad1fdbdc8b22b8f6ab0df2e39d022e7a68e45fa63cfd982a6de7da0c'}
LIMITS={'hardware_executed':False,'ram_access_verified':False,'platform_initialized':False,
        'board_ready':False,'inference_performed':False,'energy_measured':False}
KEYS=('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')

def require(ok,message):
    if not ok: raise RuntimeError(message)

def encode(value):
    return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def pin(path):
    p=Path(path)
    require(p.is_absolute() and p==p.resolve(),f'Noncanonical input {p}')
    with p.open('rb') as f:
        a=os.fstat(f.fileno());require(stat.S_ISREG(a.st_mode),'Not ordinary file')
        digest=hashlib.file_digest(f,'sha256').hexdigest();b=os.fstat(f.fileno())
    require(all(getattr(a,k)==getattr(b,k)==getattr(p.stat(),k) for k in KEYS),'Input changed')
    return {**{k:getattr(a,k) for k in KEYS},'sha256':digest}

def unchanged(pins):
    for name,p in pins.items(): require(pin(name)==p,f'Changed: {name}')
    for name,p in pins.items():
        s=Path(name).stat();require(all(getattr(s,k)==p[k] for k in KEYS),'Late changed input')

def elf_layout(raw,abi):
    require(raw[:7]==b'\x7fELF\x01\x01\x01','Expected ELF32 little endian')
    h=struct.unpack_from('<16sHHIIIIIHHHHHH',raw)
    require(h[2]==40 and h[8]==52 and h[9]==32,'Expected ARM ELF header')
    entry=h[4];segments=[]
    for i in range(h[10]):
        p=struct.unpack_from('<IIIIIIII',raw,h[5]+i*h[9])
        if p[0]!=1: continue
        _,off,vaddr,paddr,filesz,memsz,flags,align=p
        require(paddr==vaddr and filesz<=memsz and off+filesz<=len(raw),'Bad PT_LOAD')
        segments.append(dict(address=vaddr,file_offset=off,file_bytes=filesz,memory_bytes=memsz,flags=flags))
    require(len(segments)==3,'Expected code/stack/mailbox PT_LOAD')
    code,stack,mail=segments
    require(code['address']==abi['code_start'] and code['flags']==5 and
            code['address']+code['memory_bytes']<=abi['code_end_exclusive'],'Code range')
    require(stack==dict(address=abi['stack_start'],file_offset=stack['file_offset'],file_bytes=0,
                        memory_bytes=abi['stack_top']-abi['stack_start'],flags=6),'Stack range')
    require(mail==dict(address=abi['mailbox_address'],file_offset=mail['file_offset'],file_bytes=0,
                       memory_bytes=abi['struct_bytes'],flags=6),'Mailbox range')
    msp,reset=struct.unpack_from('<II',raw,code['file_offset'])
    require(msp==abi['stack_top'] and reset==entry and entry&1 and
            abi['code_start']<=entry-1<abi['code_end_exclusive'],'Vector/entry contract')
    return {'entry_thumb':entry,'initial_msp':msp,'segments':segments}

def build(out):
    out=Path(out)
    require(out.is_absolute() and out==out.resolve() and out.parent==HERE,'Fresh direct child required')
    require(not os.path.lexists(out),'Output already exists')
    held={str(HERE/n):pin(HERE/n) for n in ('build.py','ABI.json','DESIGN.md','main.c','startup.c','mailbox.h','linker.ld')}
    for p,digest in PINNED.items():
        held[p]=pin(p);require(held[p]['sha256']==digest,'Pinned local evidence changed')
    abi=json.loads((HERE/'ABI.json').read_bytes())
    tools={n:TC/'bin'/('arm-none-eabi-'+n) for n in ('gcc','objcopy','readelf','objdump','nm','size')}
    for p in tools.values(): held[str(p)]=pin(p)
    out.mkdir(mode=0o700);identity=(out.stat().st_dev,out.stat().st_ino)
    calls=[]
    def guard():
        require(out==out.resolve() and (out.stat().st_dev,out.stat().st_ino)==identity,'Owned output replaced')
    def write(name,raw):
        guard()
        with (out/name).open('xb') as f: f.write(raw);f.flush();os.fsync(f.fileno())
        require((out/name).read_bytes()==raw,'Published bytes replaced')
    def command(label,args):
        guard();r={'argv':[str(a) for a in args],'actual_return_code':None,'timed_out':False}
        with (out/(label+'.stdout')).open('xb') as stdout,(out/(label+'.stderr')).open('xb') as stderr:
            p=subprocess.Popen(r['argv'],cwd=out,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                env={'PATH':str(TC/'bin')+':/usr/bin:/bin','LANG':'C','LC_ALL':'C','TMPDIR':str(out)},start_new_session=True)
            try: p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                r['timed_out']=True;os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=10)
            finally:
                if p.poll() is None: os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=10)
                r['actual_return_code']=p.returncode
                stdout.flush();stderr.flush();os.fsync(stdout.fileno());os.fsync(stderr.fileno())
        calls.append(r);write(label+'.json',encode(r))
        require(r['actual_return_code']==0 and not r['timed_out'],f'Command failed: {label}')
        return (out/(label+'.stdout')).read_text()
    try:
        write('INTENT.json',encode({'schema':1,'kind':'offline_ram_probe_build_intent','input_pins':held,**LIMITS}))
        version=command('version',[tools['gcc'],'--version'])
        require(version.splitlines()[0]=='arm-none-eabi-gcc (Arm GNU Toolchain 13.2.rel1 (Build arm-13.7)) 13.2.1 20231009','Compiler version')
        for name in ('cc1','as','ld'):
            selected=command('tool_'+name,[tools['gcc'],'-print-prog-name='+name]).strip()
            p=Path(selected).resolve();held[str(p)]=pin(p)
        base=[tools['gcc'],*FLAGS,'-DSTM32N657xx','-O2','-g3','-std=c11','-Wall','-Wextra','-Werror',
              '-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-pic','-fno-common',
              '-fno-unwind-tables','-fno-asynchronous-unwind-tables','-fno-tree-loop-distribute-patterns',
              '-ffunction-sections','-fdata-sections','-I'+str(HERE),
              '-I'+str(TP/'CMSIS_6/CMSIS/Core/Include'),'-I'+str(TP/'cmsis-device-n6/Include')]
        for name in ('main','startup'):
            dep=out/(name+'.d')
            command('deps_'+name,[*base,'-M','-MF',dep,HERE/(name+'.c')])
            for item in shlex.split(dep.read_text().replace('\\\n',' ').split(':',1)[1]):
                p=Path(item).resolve();current=pin(p)
                if str(p) in held: require(held[str(p)]==current,'Changed dependency')
                else: held[str(p)]=current
        unchanged(held);write('COMPILE_INPUTS.json',encode(held))
        objects={}
        for name in ('main','startup'):
            obj=out/(name+'.o');command('compile_'+name,[*base,'-c',HERE/(name+'.c'),'-o',obj]);objects[str(obj)]=pin(obj)
        unchanged({**held,**objects})
        elf=out/'probe.elf'
        command('link',[tools['gcc'],*FLAGS,'-nostdlib','-nostartfiles','-nodefaultlibs','-T',HERE/'linker.ld',
            '-Wl,--gc-sections,--fatal-warnings,--build-id=none','-Wl,-Map='+str(out/'probe.map'),
            out/'startup.o',out/'main.o','-o',elf])
        require(not command('undefined',[tools['nm'],'-u',elf]).strip(),'Undefined symbols')
        command('symbols',[tools['nm'],'-n','-S',elf])
        command('readelf',[tools['readelf'],'-h','-l','-S','-A',elf])
        command('disassembly',[tools['objdump'],'-d',elf])
        command('size',[tools['size'],'-A',elf])
        command('binary',[tools['objcopy'],'-O','binary',elf,out/'probe.bin'])
        layout=elf_layout(elf.read_bytes(),abi)
        code=layout['segments'][0]
        require((out/'probe.bin').read_bytes()==elf.read_bytes()[code['file_offset']:code['file_offset']+code['file_bytes']],'BIN != code segment')
        unchanged({**held,**objects});guard()
        artifacts={p.name:pin(p) for p in sorted(out.iterdir())}
        report={'schema':1,'kind':'offline_n6_secure_ram_probe_build','actual_process_exit':None,
                'compile_link_succeeded':True,'abi':abi,'elf_layout':layout,'calls':calls,
                'input_pins':held,'artifacts_before_result':artifacts,
                'limits':['No target execution or access.','No platform initialization.',
                          'Header/tool finite bookends, not complete host runtime closure.'],**LIMITS}
        report['content_sha256']=hashlib.sha256(encode(report)).hexdigest()
        write('RESULT.json',encode(report));artifacts['RESULT.json']=pin(out/'RESULT.json')
        unchanged(held)
        require(set(p.name for p in out.iterdir())==set(artifacts),'Output namespace changed')
        unchanged({str(out/n):p for n,p in artifacts.items()});unchanged(held);guard()
        return report
    except BaseException as exc:
        try: write('FAILED.json',encode({'exception':str(exc),'calls':calls,**LIMITS}))
        except BaseException: pass
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--output-dir',type=Path,required=True);args=p.parse_args()
    result=build(args.output_dir)
    print(json.dumps({'compile_link_succeeded':True,'content_sha256':result['content_sha256'],**LIMITS},sort_keys=True))
    return 0
if __name__=='__main__':raise SystemExit(main())
