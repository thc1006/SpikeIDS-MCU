"""Read-only observation of ESP02 artifacts; does not reclassify failed wrapper."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

HERE=Path(__file__).resolve().parent
WRAPPER=HERE/'build_candidate.py'
if hashlib.sha256(WRAPPER.read_bytes()).hexdigest()!='786df9ccd494acf1a0b8e21d6b7b6e4a353197ac243180f408dedb10351d3de3':
    raise ValueError('reviewed build helper changed')
spec=importlib.util.spec_from_file_location('fixed_build_observer',WRAPPER)
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
SOURCE=b.ROOT/'results/esp32s3_v5_build_20260925_02'
EXPECTED={'STARTED.json':'3ff60506cef1281e43f6961529ab00c38c5deedb74029eb3856c261a5328a3cb',
          'build.json':'374bc94719cc2878f035fc2694fa05369636eda274ca1723b039b78f6563d076',
          'FAILED.json':'f6f780a715d147f4ab9ef92f46969a27550b8af6203e1e0949f1f2c503b43ef7',
          'build/spikeids_v5_qdq.elf':'6f07e705dff6548a780fcd338f040f607e6838482b8aa1d5ac2b0a8000a9f9a9',
          'build/spikeids_v5_qdq.bin':'fc0ac37783d99faddfe1c82966632ad244a92556b9b1e016b338be9e32146fab'}
FORCED={'__cxx_fatal_exception','start_app','start_app_other_cores'}

def run():
    b.require(sys.flags.optimize==0,'optimize forbidden')
    own={str(p):b.snapshot(p)[1] for p in (Path(__file__),WRAPPER)}
    inv=b.inventory(SOURCE)
    for name,sha in EXPECTED.items():b.require(inv['files'][name]['sha256']==sha,'saved original commitment')
    started=json.loads((SOURCE/'STARTED.json').read_text())
    pins=started['input_pins']
    b.require(all(b.snapshot(p)[1]==pin for p,pin in pins.items()),'original input pins')
    b.require(not (SOURCE/'RESULT.json').exists() and json.loads((SOURCE/'FAILED.json').read_text())['error']=='undefined symbols','failure preserved')
    b.require(json.loads((SOURCE/'build.json').read_text())['returncode']==0,'compiler subprocess')
    elf=SOURCE/'build/spikeids_v5_qdq.elf';raw=elf.read_bytes()
    b.require(raw[:7]==b'\x7fELF\x01\x01\x01','ELF32')
    h=struct.unpack_from('<16sHHIIIIIHHHHHH',raw)
    b.require(h[1:4]==(2,94,1) and h[9]==32 and h[10]==8,'Xtensa executable header')
    areas=((0x3c000000,0x3e000000),(0x42000000,0x44000000),(0x3fc88000,0x3fd00000),
           (0x40370000,0x403e0000),(0x50000000,0x50002000),(0x600fe000,0x60100000))
    segments=[]
    for i in range(h[10]):
        typ,off,va,pa,fs,ms,flags,align=struct.unpack_from('<8I',raw,h[5]+32*i)
        b.require(typ==1 and fs<=ms and off+fs<=len(raw) and any(lo<=va and va+ms<=hi for lo,hi in areas),'mapped/internal segment')
        segments.append(dict(address=hex(va),file_bytes=fs,memory_bytes=ms,flags=flags))
    readelf=(SOURCE/'readelf.stdout').read_text()
    b.require('There are no relocations in this file.' in readelf,'no linked relocations')
    undef={line.split()[-1] for line in (SOURCE/'undefined.stdout').read_text().splitlines()}
    b.require(undef==FORCED,'exact forced undefined names')
    sdk_paths=[b.IDF/'components/esp_system/CMakeLists.txt',b.IDF/'components/cxx/CMakeLists.txt',
               b.IDF/'components/esp_system/startup.c',b.IDF/'components/freertos/app_startup.c',
               b.IDF/'components/esp_system/ld/esp32s3/memory.ld.in']
    evidence={str(p):b.snapshot(p)[1] for p in sdk_paths}
    cmakes='\n'.join(p.read_text() for p in sdk_paths[:2])
    b.require(all('"-u '+name+'"' in cmakes for name in FORCED),'SDK forced symbol provenance')
    archives=sorted((SOURCE/'build/esp-idf').rglob('*.a'))
    nm=b.XTENSA/'xtensa-esp32s3-elf-nm'
    proc=subprocess.run([str(nm),'-u',*[str(p) for p in archives]],capture_output=True,timeout=30,check=False,
                        env=b.environment('esp32s3',SOURCE/'tmp'))
    b.require(proc.returncode==0,'archive reference inspection')
    actual_refs={line.split()[-1] for line in proc.stdout.decode().splitlines() if re.match(r'^\s+[Uwv]\s+',line)}
    b.require(not FORCED & actual_refs,'forced names have archive references')
    mapping=(SOURCE/'build/spikeids_v5_qdq.map').read_text()
    for name in ('esp_startup_start_app','esp_startup_start_app_other_cores','pq_infer','v5_process','app_main'):
        b.require(re.search(r'0x[0-9a-f]+\s+'+name+r'\s*$',mapping,re.M),'real function linked '+name)
    config=(SOURCE/'build/sdkconfig').read_text()
    for yes in ('CONFIG_ESP_CONSOLE_NONE=y','CONFIG_ESP_CONSOLE_SECONDARY_NONE=y',
                'CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y','CONFIG_ESP_MAIN_TASK_STACK_SIZE=8192'):
        b.require(yes in config,'fixed configuration')
    b.require('CONFIG_SPIRAM=y' not in config,'no PSRAM assumption')
    commands=json.loads((SOURCE/'build/compile_commands.json').read_text())
    numeric={}
    for name in ('portable_qdq.c','wire.c','model.c'):
        rows=[x for x in commands if Path(x['file']).name==name];b.require(len(rows)==1,'numeric TU')
        command=rows[0]['command'];b.require(all(f in command for f in b.FP[:5]),'numeric flags')
        numeric[name]=command
    subprocess_records={}
    for label,args in [('size',['-A']),('symbols',['-S','-n']),('disassembly',['-d'])]:
        tool=b.XTENSA/('xtensa-esp32s3-elf-'+{'symbols':'nm','disassembly':'objdump'}.get(label,label))
        done=subprocess.run([str(tool),*args,str(elf)],capture_output=True,timeout=30,check=False,
                            env=b.environment('esp32s3',SOURCE/'tmp'))
        b.require(done.returncode==0,'saved binary observation '+label)
        subprocess_records[label]={'returncode':done.returncode,'stdout_sha256':hashlib.sha256(done.stdout).hexdigest()}
        if label=='size':subprocess_records[label]['stdout']=done.stdout.decode()
    b.require(b.inventory(SOURCE)==inv,'saved outputs changed')
    b.require(all(b.snapshot(p)[1]==pin for p,pin in (pins|own|evidence).items()),'final inputs')
    b.namespace(SOURCE,inv);b.stats(pins|own|evidence|{str(SOURCE/n):p for n,p in inv['files'].items()})
    keys=['build/spikeids_v5_qdq.elf','build/spikeids_v5_qdq.bin','build/spikeids_v5_qdq.map',
          'build/bootloader/bootloader.bin','build/partition_table/partition-table.bin','build/flasher_args.json',
          'STARTED.json','FAILED.json','build.json']
    return {'kind':'saved_esp02_build_observation','source_pins':own,'sdk_observation_pins':evidence,
            'original_input_count':len(pins),'saved_files':len(inv['files']),'saved_directories':len(inv['directories']),
            'saved_inventory_sha256':hashlib.sha256(b.encoded(inv)).hexdigest(),
            'selected_original_pins':{n:inv['files'][n] for n in keys},'segments':segments,
            'forced_undefined_symbols':sorted(undef),'component_archives_checked':len(archives),
            'forced_symbol_archive_references':[],'archive_nm_returncode':proc.returncode,
            'archive_nm_stdout_sha256':hashlib.sha256(proc.stdout).hexdigest(),
            'numeric_compile_commands':numeric,'observations':subprocess_records,
            'compiler_subprocess_exit':0,'original_wrapper_exit':1,'original_FAILED_preserved':True,
            'no_RESULT_adopted':True,'hardware_accessed':False,'target_parity_accepted':False,
            'full_sdk_dependency_or_reference_closure_claimed':False,'actual_process_exit':None}

if __name__=='__main__':print(json.dumps(run(),sort_keys=True,indent=2))
