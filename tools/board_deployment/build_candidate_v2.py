"""Additive v2: fixed offline crossbuild with explicit ESP SDK symbol/RTC policy.

Original build_candidate.py and its successful RA / failed ESP records remain
unchanged. No flashing, transport, source generation, or numerical replay.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import struct
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PORTABLE=HERE/'portable_qdq'
MODEL=ROOT/'results/portable_qdq_native_20260925_01/model_sources/model.c'
RA=Path('/home/thc1006/dev/SpikeIDS-RA4E1/firmware/ra4e1_skeleton')
ARM=Path('/home/thc1006/opt/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi/bin')
IDF=Path('/home/thc1006/esp/esp-idf')
PYTHON=Path('/home/thc1006/.espressif/python_env/idf5.4_py3.14_env/bin/python')
XTENSA=Path('/home/thc1006/.espressif/tools/xtensa-esp-elf/esp-14.2.0_20260121/xtensa-esp-elf/bin')
FIXED={MODEL:'bba723cc7b031815c2aaf848f6893eb87dd91cb05f5580f93df611be489bb1e9',
       PORTABLE/'portable_qdq.c':'e389a691656fd8dfbb75771c205e51ab16f491adfad65213b6e0ec951e0e4851',
       PORTABLE/'portable_qdq.h':'e8abd58b44e15806eff54df5245757c23aa491bd044f579dd59d0efc7c5be406',
       ROOT/'results/portable_qdq_native_20260925_01/RESULT.json':'cb3536b760e40ad2fe6ce942e677ab2472837e2a73ffb86edd15700c3a171a93',
       PORTABLE/'NATIVE_ACTUAL_01_EXECUTION.json':'5222d43668261d9cbd2a2c29fa19d9cd86c300354a71a5020717dc882b732de2'}
FP=('-std=c11','-O2','-fno-fast-math','-ffp-contract=off','-fexcess-precision=standard',
    '-ffunction-sections','-fdata-sections')
ESP_FORCED={'__cxx_fatal_exception','start_app','start_app_other_cores'}
ESP_CMAKES=(IDF/'components/esp_system/CMakeLists.txt',IDF/'components/cxx/CMakeLists.txt')
FIELDS=('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
def require(ok,message):
    if not ok: raise ValueError(message)
def encoded(x): return (json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def snapshot(path):
    p=Path(path); require(p.is_absolute() and p.resolve()==p, 'canonical input')
    a=p.stat(); require(stat.S_ISREG(a.st_mode), 'ordinary file')
    raw=p.read_bytes(); b=p.stat()
    require(all(getattr(a,k)==getattr(b,k) for k in FIELDS), 'file changed while reading')
    return raw,dict(sha256=hashlib.sha256(raw).hexdigest(),**{k:getattr(a,k) for k in FIELDS})
def stats(pins):
    for p,pin in pins.items():
        p=Path(p); require(p.resolve()==p,'late symlink')
        st=p.stat(follow_symlinks=False)
        require(all(getattr(st,k)==pin[k] for k in FIELDS), 'late file change: '+str(p))
def owned(path,identity):
    st=path.stat(follow_symlinks=False)
    require(path.resolve()==path and stat.S_ISDIR(st.st_mode) and
            (st.st_dev,st.st_ino)==identity, 'owned directory rebound')
def inventory(path):
    files={}; dirs=[]
    for base,children,names in os.walk(path,followlinks=False):
        for name in children:
            p=Path(base)/name; require(not p.is_symlink(), 'output symlink')
            dirs.append(str(p.relative_to(path)))
        for name in names:
            p=Path(base)/name; files[str(p.relative_to(path))]=snapshot(p)[1]
    return {'files':files,'directories':sorted(dirs)}
def namespace(path,inv):
    files=[]; dirs=[]
    for base,children,names in os.walk(path,followlinks=False):
        for name in children:
            p=Path(base)/name; require(not p.is_symlink(), 'late output symlink')
            dirs.append(str(p.relative_to(path)))
        files.extend(str((Path(base)/name).relative_to(path)) for name in names)
    require(set(files)==set(inv['files']) and sorted(dirs)==inv['directories'],'output namespace changed')
def environment(board,tmp):
    env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C','TZ':'UTC','TMPDIR':str(tmp),
         'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
         'PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'0','PYTHONOPTIMIZE':'0'}
    if board=='ra4e1': env['PATH']=str(ARM)+':'+env['PATH']
    else:
        env.update(PATH=str(XTENSA)+':'+str(PYTHON.parent)+':'+env['PATH'],IDF_PATH=str(IDF),
                   IDF_TOOLS_PATH='/home/thc1006/.espressif',IDF_PYTHON_ENV_PATH=str(PYTHON.parent.parent),
                   IDF_COMPONENT_MANAGER='0')
    return env
def elf_layout(raw,board):
    require(raw[:7]==b'\x7fELF\x01\x01\x01', 'ELF32 little endian')
    h=struct.unpack_from('<16sHHIIIIIHHHHHH',raw)
    require(h[1]==2 and h[2]==(40 if board=='ra4e1' else 94), 'executable architecture')
    phoff,phsize,count=h[5],h[9],h[10]
    require(phsize==32 and 0<count<30 and phoff+count*32<=len(raw), 'ELF program headers')
    segments=[]; rtc_segments=0
    for i in range(count):
        typ,off,va,pa,fs,ms,flags,align=struct.unpack_from('<8I',raw,phoff+i*32)
        if typ!=1: continue
        require(fs<=ms and off+fs<=len(raw), 'ELF file range')
        if not ms: continue
        if board=='ra4e1':
            require((0<=va and va+ms<=0x80000) or (0x20000000<=va and va+ms<=0x20020000),'RA memory range')
            require(not fs or pa+fs<=0x80000, 'RA non-flash programming record')
        else:
            areas=((0x3c000000,0x3e000000),(0x42000000,0x44000000),
                   (0x3fc88000,0x3fd00000),(0x40370000,0x403e0000),(0x50000000,0x50002000))
            if (va,pa,fs,ms,flags)==(0x600fffe8,0x600fffe8,0,24,6):
                rtc_segments+=1
            else:
                require(any(lo<=va and va+ms<=hi for lo,hi in areas), 'ESP mapped/internal memory range')
        segments.append(dict(address=va,physical=pa,file_bytes=fs,memory_bytes=ms,flags=flags,alignment=align))
    require(segments, 'empty executable')
    if board=='esp32s3':
        # The sole allowed extra RTC region is the SDK's 24-byte reserved
        # NOBITS area, not an expanded arbitrary RTC executable/file payload.
        shoff,shsize,shnum,shnames=h[6],h[11],h[12],h[13]
        require(shsize==40 and 0<shnum<200 and shoff+shnum*40<=len(raw) and shnames<shnum,'ELF section table')
        sections=[struct.unpack_from('<10I',raw,shoff+i*40) for i in range(shnum)]
        string_section=sections[shnames]
        require(string_section[1]==3 and string_section[4]+string_section[5]<=len(raw),'section string table')
        strings=raw[string_section[4]:string_section[4]+string_section[5]]
        rtc=[]
        for s in sections:
            require(s[0]<len(strings) and b'\0' in strings[s[0]:],'section name')
            name=strings[s[0]:].split(b'\0',1)[0]
            require(not (s[1] in (4,9) and s[5]),'ESP relocation section')
            if name==b'.rtc_reserved':rtc.append(s)
            elif s[2]&2 and s[5] and 0x600fe000<=s[3]<0x60100000:
                raise ValueError('unexpected allocated RTC section')
        require(rtc_segments==1 and len(rtc)==1,'exact RTC reservation presence')
        s=rtc[0]
        require((s[1],s[2],s[3],s[5],s[8])==(8,3,0x600fffe8,24,8),'exact RTC NOBITS reservation')
    return {'entry':h[4],'segments':segments,'runtime_relocations':0 if board=='esp32s3' else None}

def numeric_policy(rows):
    result={}
    for source in (PORTABLE/'portable_qdq.c',HERE/'shared_v5/wire.c',MODEL):
        selected=[x for x in rows if x.get('file')==str(source)]
        require(len(selected)==1 and type(selected[0].get('command')) is str,'exact numeric compile unit')
        argv=shlex.split(selected[0]['command'])
        require(all(flag in argv for flag in FP[:5]),'exact FP compile tokens')
        standards=[x for x in argv if x.startswith('-std=')]
        optimize=[x for x in argv if re.fullmatch(r'-O(?:[0-3gsz]|fast)?',x)]
        require(standards[-1:]==['-std=c11'] and optimize[-1:]==['-O2'],'effective C/optimization mode')
        bad={'-ffast-math','-Ofast','-funsafe-math-optimizations','-ffinite-math-only',
             '-fassociative-math','-freciprocal-math','-fno-signed-zeros','-fno-rounding-math'}
        require(not (bad & set(argv)) and not any(x.startswith('@') for x in argv),'hidden/unsafe compiler control')
        require(all(x=='-ffp-contract=off' for x in argv if x.startswith('-ffp-contract=')) and
                all(x=='-fexcess-precision=standard' for x in argv if x.startswith('-fexcess-precision=')),
                'conflicting FP controls')
        require('-c' in argv and argv[argv.index('-c')+1]==str(source),'compiler source argument')
        result[source.name]=argv
    return result

def esp_symbol_policy(undefined,archive_undefined,cmakes,raw_elf):
    def names(raw,final=False):
        # Ignore archive/member labels; only ordinary nm undefined entries.
        result=set()
        for line in raw.decode().splitlines():
            if not line.strip() or line.endswith(':'):continue
            fields=line.split()
            require(len(fields)==2 and fields[0] in ('U','w','v'),'unrecognized nm undefined record')
            require(not final or fields[0]=='U','final forced symbols must be global undefined')
            result.add(fields[1])
        return result
    require(names(undefined,True)==ESP_FORCED,'exact SDK forced undefined symbol set')
    require(not (names(archive_undefined)&ESP_FORCED),'forced symbol has object reference')
    require(type(cmakes) is tuple and len(cmakes)==2,'fixed SDK CMake evidence')
    for name in ESP_FORCED:
        owner=cmakes[1] if name=='__cxx_fatal_exception' else cmakes[0]
        require(re.search(r'^\s*target_link_libraries\(\$\{COMPONENT_LIB\} INTERFACE "-u '+
                          re.escape(name)+r'"\)\s*$',owner,re.M),'SDK -u directive missing')
    layout=elf_layout(raw_elf,'esp32s3')
    return {'forced_undefined':sorted(ESP_FORCED),'forced_object_references':[],
            'runtime_relocations':layout['runtime_relocations']}

def ra_sources():
    bsp=RA/'ra/fsp/src/bsp'
    return [HERE/'ra4e1_v5/app.c',HERE/'shared_v5/wire.c',PORTABLE/'portable_qdq.c',MODEL]+[
        RA/'ra_gen'/n for n in ('main.c','common_data.c','hal_data.c','pin_data.c','vector_data.c')]+[
        RA/'ra/fsp/src'/n for n in ('r_can/r_can.c','r_ioport/r_ioport.c')]+[
        *sorted((bsp/'mcu/all').glob('*.c')),bsp/'mcu/ra4e1/bsp_linker.c',
        bsp/'cmsis/Device/RENESAS/Source/startup.c',bsp/'cmsis/Device/RENESAS/Source/system.c']

def run(board,output):
    require(board in ('ra4e1','esp32s3') and sys.flags.optimize==0,'board/optimization')
    output=Path(output).absolute(); parent=output.parent
    require(parent.resolve()==parent and parent.is_dir() and not output.exists() and not output.is_symlink(),'fresh output')
    pfd=os.open(parent,os.O_DIRECTORY|os.O_RDONLY|os.O_NOFOLLOW)
    pst=os.fstat(pfd); parentid=(pst.st_dev,pst.st_ino); identity=None; pins={}; commands=[]
    def hold(path):
        path=Path(path).resolve(); raw,pin=snapshot(path)
        if str(path) in pins: require(pins[str(path)]==pin,'original input changed')
        else: pins[str(path)]=pin
        return raw
    def write(name,data):
        owned(output,identity)
        require(Path(name).name==name,'flat record path')
        fd=os.open(output/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f: f.write(data);f.flush();os.fsync(f.fileno())
    def command(label,args,timeout=180):
        owned(parent,parentid); owned(output,identity)
        args=[str(x) for x in args]
        try: p=subprocess.run(args,cwd=output,env=environment(board,output/'tmp'),capture_output=True,timeout=timeout,check=False)
        except subprocess.TimeoutExpired as e:
            write(label+'.stdout',e.stdout or b'');write(label+'.stderr',e.stderr or b'')
            write(label+'.json',encoded({'argv':args,'returncode':None,'timeout':True}));raise
        write(label+'.stdout',p.stdout);write(label+'.stderr',p.stderr)
        rec={'argv':args,'returncode':p.returncode,'timeout':False};commands.append(rec)
        write(label+'.json',encoded(rec));require(p.returncode==0,label+' exit '+str(p.returncode));return p.stdout
    try:
        for path,sha in FIXED.items(): require(hashlib.sha256(hold(path)).hexdigest()==sha,'fixed native-passed source')
        for path in (Path(__file__),HERE/'TWO_BOARD_BUILD_PLAN.md',HERE/'shared_v5/wire.c',HERE/'shared_v5/wire.h',HERE/'shared_v5/WIRE_ABI.json'): hold(path)
        project=HERE/(board+'_v5')
        for path in sorted(project.rglob('*')):
            if path.is_file(): hold(path)
        if board=='ra4e1':
            tools={n:ARM/('arm-none-eabi-'+n) for n in ('gcc','objcopy','readelf','nm','size','objdump')}
            sources=ra_sources()
            for path in sources: hold(path)
            for sub in ('ra','ra_cfg','ra_gen'):
                for path in sorted((RA/sub).rglob('*')):
                    if path.is_file() and path.suffix in ('.h','.c','.ld'):hold(path)
            for name in ('memory_regions.ld','fsp_gen.ld'):hold(RA/name)
        else:
            tools={n:XTENSA/('xtensa-esp32s3-elf-'+n) for n in ('gcc','objcopy','readelf','nm','size','objdump')}
            for path in (PYTHON,Path('/usr/bin/cmake'),Path('/usr/bin/ninja'),
                         IDF/'tools/cmake/project.cmake',IDF/'components/esp_common/include/esp_idf_version.h',
                         *ESP_CMAKES,IDF/'components/esp_system/ld/esp32s3/memory.ld.in'):
                hold(path)
        for path in tools.values():hold(path)
        owned(parent,parentid);os.mkdir(output.name,dir_fd=pfd)
        st=output.stat();identity=(st.st_dev,st.st_ino);owned(output,identity)
        (output/'tmp').mkdir()
        write('STARTED.json',encoded({'kind':'offline_crossbuild_intent','board':board,'input_pins':pins,
              'environment':environment(board,output/'tmp'),'hardware_accessed':False,'automatic_retry':False}))
        command('compiler_version',[tools['gcc'],'--version'],10)
        if board=='ra4e1':
            incs=[project,RA/'ra/arm/CMSIS_6/CMSIS/Core/Include',RA/'ra/fsp/inc',RA/'ra/fsp/inc/api',
                  RA/'ra/fsp/inc/instances',RA/'ra_cfg/fsp_cfg',RA/'ra_cfg/fsp_cfg/bsp',RA/'ra_gen',RA/'src',RA,
                  HERE/'shared_v5',PORTABLE]
            flags=['-mcpu=cortex-m33','-mthumb','-mfloat-abi=hard','-mfpu=fpv5-sp-d16',
                   '-D_RA_CORE=CM33','-D_RA_ORDINAL=1','-D_RENESAS_RA_',*FP]
            objects=[]
            for i,src in enumerate(sources):
                obj=output/f'obj_{i:02}.o';objects.append(obj)
                extra=['-DBSP_BOOTLOADED_APPLICATION'] if src.name=='bsp_linker.c' else []
                command(f'compile_{i:02}',[tools['gcc'],*flags,*extra,*[x for p in incs for x in ('-I',p)],
                        '-MMD','-MF',output/f'obj_{i:02}.d','-c',src,'-o',obj])
            elf=output/'firmware.elf'
            command('link',[tools['gcc'],*flags,'--specs=nano.specs','--specs=nosys.specs',*objects,
                    '-T',project/'linker.ld','-Wl,--gc-sections',f'-Wl,-Map={output}/firmware.map','-lm','-o',elf])
            command('binary',[tools['objcopy'],'-O','binary',elf,output/'firmware.bin'])
            command('hex',[tools['objcopy'],'-O','ihex',elf,output/'firmware.hex'])
        else:
            build=output/'build'
            command('configure',['/usr/bin/cmake','-S',project,'-B',build,'-G','Ninja',
                    '-DPYTHON='+str(PYTHON),'-DIDF_TARGET=esp32s3','-DSDKCONFIG='+str(build/'sdkconfig'),
                    '-DSDKCONFIG_DEFAULTS='+str(project/'sdkconfig.defaults'),'-DPYTHON_DEPS_CHECKED=1'],180)
            command('build',['/usr/bin/cmake','--build',build,'-j2'],600)
            elf=build/'spikeids_v5_qdq.elf'
            config=(build/'sdkconfig').read_text()
            require('CONFIG_SPIRAM=y' not in config and 'CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y' not in config
                    and all(x in config.splitlines() for x in ('CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y',
                    'CONFIG_ESP_CONSOLE_NONE=y','CONFIG_ESP_CONSOLE_SECONDARY_NONE=y')),'ESP bounded config')
            cc=json.loads((build/'compile_commands.json').read_text())
            numeric=numeric_policy(cc)
        command('readelf',[tools['readelf'],'-W','-a',elf])
        undefined=command('undefined',[tools['nm'],'-u',elf])
        if board=='ra4e1':require(not undefined.strip(),'undefined symbols');symbol_policy=None
        else:
            archives=sorted(build.rglob('*.a'));require(archives,'missing build archives')
            archived_pins={str(p):snapshot(p)[1] for p in archives}
            archive_undefined=command('archive_undefined',[tools['nm'],'-u',*archives])
            symbol_policy=esp_symbol_policy(undefined,archive_undefined,tuple(hold(p).decode() for p in ESP_CMAKES),elf.read_bytes())
            symbol_policy['build_archives_checked']=len(archives)
            symbol_policy['original_archive_pins']=archived_pins
            require(all(snapshot(p)[1]==pin for p,pin in archived_pins.items()),'archive observation bookend')
        symbols=command('symbols',[tools['nm'],'-S','-n',elf]).decode()
        command('size',[tools['size'],'-A',elf])
        command('disassembly',[tools['objdump'],'-d',elf])
        layout=elf_layout(elf.read_bytes(),board)
        if board=='ra4e1':
            require(re.search(r'^2001f000 00000200 [Bb] g_v5_mailbox$',symbols,re.M),'RA mailbox symbol')
            require(re.search(r'^[0-9a-f]+ 00002000 [Bb] g_main_stack$',symbols,re.M),'RA 8 KiB stack')
        require(all(snapshot(p)[1]==pin for p,pin in pins.items()),'input hash bookend')
        inv=inventory(output)
        record={'schema':1,'kind':'offline_two_board_v5_crossbuild','board':board,'input_pins':pins,
                'artifact_inventory':inv,'commands':commands,'elf_layout':layout,'numeric_flags':FP,
                'esp_symbol_policy':symbol_policy,'numeric_command_tokens':numeric if board=='esp32s3' else None,
                'model_sha256':'22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d',
                'vectors_sha256':'cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb',
                'environment':environment(board,output/'tmp'),'actual_process_exit':None,'hardware_accessed':False,
                'target_parity_accepted':False,'physical_esp_sku_confirmed':False,'npu_execution_claimed':False,
                'full_sdk_toolchain_dependency_closure_claimed':False,'automatic_retry':False}
        write('RESULT.json',encoded(record));inv['files']['RESULT.json']=snapshot(output/'RESULT.json')[1]
        require(all(snapshot(p)[1]==pin for p,pin in pins.items()),'last input hashes')
        owned(parent,parentid);owned(output,identity);namespace(output,inv)
        stats(pins|{str(output/n):pin for n,pin in inv['files'].items()})
        return record
    except Exception as exc:
        if identity is not None:
            try:write('FAILED.json',encoded({'kind':'offline_crossbuild_failure','error':str(exc),'commands':commands}))
            except (ValueError,OSError):pass
        raise
    finally:os.close(pfd)

if __name__=='__main__':
    p=argparse.ArgumentParser(allow_abbrev=False)
    p.add_argument('--board',required=True,choices=('ra4e1','esp32s3'))
    p.add_argument('--output-dir',required=True)
    a=p.parse_args()
    r=run(a.board,a.output_dir)
    print(json.dumps({'board':r['board'],'status':'offline_build_complete','commands':len(r['commands']),
                      'artifacts':len(r['artifact_inventory']['files']),'hardware_accessed':False}))
