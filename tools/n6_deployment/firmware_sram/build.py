#!/usr/bin/env python3
"""Offline ARM compile/link only. No vendor regeneration, loading or flashing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import struct
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
VENDOR = REPO / "results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01"
REVIEW = HERE.parent / "internal_sram"
REVIEW_HASHES = {
 "SAVED_REVIEW_ACTUAL_01.json": "e024e446e6c1dca394c61081e9ba1251e0483dce80d5d7d7a303538b6bc7528d",
 "SAVED_REVIEW_ACTUAL_01_EXIT.json": "30cb08b2498e9d246dee46e0b713f6981f75129ae60b60c137cafaa73cd297c3",
 "ACTUAL_01_REVIEW_SNAPSHOT.json": "ddf5338a4724bb5ec25487fd1a1f28426d49689dd538419304d6d02d23513d75"}
OLD_BUILD_RESULT = HERE.parent / "firmware_v5/build_actual_03/RESULT.json"
OLD_BUILD_RESULT_SHA = "3d4495b676421e56d4b30dd4e47c1fe9f9d052348a2b124102fa3e30b373021e"
RESERVED = [(0x34200000,0x34240000),(0x34240000,0x34244000)]
ST = Path("/home/thc1006/opt/stedgeai/3.0/Middlewares/ST/AI")
TC = Path("/home/thc1006/opt/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi")
TP = REPO / "firmware/n6/third_party"
GEN = VENDOR / "generate"
FLAGS = ["-mcpu=cortex-m55", "-mthumb", "-mfloat-abi=hard", "-mfpu=auto", "-mcmse"]
DEFS = ["-DSTM32N657xx", "-DCORE_CM55", "-DUSE_HAL_DRIVER",
        "-DLL_ATON_PLATFORM=LL_ATON_PLAT_STM32N6", "-DLL_ATON_OSAL=LL_ATON_OSAL_BARE_METAL",
        "-DLL_ATON_RT_MODE=LL_ATON_RT_POLLING", "-DLL_ATON_SW_FALLBACK=1"]
INCLUDES = [HERE, GEN, ST/"Inc", ST/"Npu/ll_aton", ST/"Npu/Devices/STM32N6xx",
            TP/"CMSIS_6/CMSIS/Core/Include", TP/"cmsis-device-n6/Include",
            TP/"stm32n6xx-hal-driver/Inc", REPO/"firmware/n6b/hal_conf"]
LIMITS = {"board_ready": False, "board_validated": False, "energy_measured": False,
          "deployment_accepted": False, "compiler_semantic_parity_verified": False,
          "hardware_executed": False, "platform_initialized": False,
          "original_generation_failure_reclassified": False}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+"\n").encode()


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path == path.resolve(), f"Noncanonical file: {path}")
    with path.open("rb") as stream:
        a = os.fstat(stream.fileno())
        require(stat.S_ISREG(a.st_mode), f"Not a regular file: {path}")
        h = hashlib.file_digest(stream, "sha256").hexdigest()
        b = os.fstat(stream.fileno())
    keys = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(all(getattr(a,k)==getattr(b,k)==getattr(path.stat(),k) for k in keys), f"Changed while reading {path}")
    return {**{k:getattr(a,k) for k in keys}, "sha256":h}


def bookend(pins):
    for path, expected in pins.items():
        require(pin(path)==expected, f"Input changed: {path}")
    for path, expected in pins.items():
        s=Path(path).stat()
        require(all(getattr(s,k)==v for k,v in expected.items() if k!="sha256"), f"Late input change: {path}")


def hold(pins,path):
    name=str(path);current=pin(path)
    if name in pins:require(pins[name]==current,"Original committed input changed; no fresh adoption")
    else:pins[name]=current
    return current


def candidate_namespace():
    require(VENDOR==VENDOR.resolve() and not VENDOR.is_symlink(),"Retained root changed")
    files=set();directories=[]
    for base,dirs,names in os.walk(VENDOR,followlinks=False):
        for name in dirs:
            p=Path(base)/name;require(stat.S_ISDIR(p.lstat().st_mode),"Retained nonordinary directory")
            directories.append(str(p.relative_to(VENDOR)))
        for name in names:
            p=Path(base)/name;require(stat.S_ISREG(p.lstat().st_mode),"Retained nonordinary file")
            files.add(str(p.relative_to(VENDOR)))
    return files,sorted(directories)


def candidate_pins():
    """Bind the saved review plus the original failed generation, not a new success."""
    held={}
    for name,digest in REVIEW_HASHES.items():
        p=REVIEW/name;held[str(p)]=pin(p);require(held[str(p)]["sha256"]==digest,"Wrong fixed saved review")
    review=json.loads((REVIEW/"SAVED_REVIEW_ACTUAL_01.json").read_bytes())
    receipt=json.loads((REVIEW/"SAVED_REVIEW_ACTUAL_01_EXIT.json").read_bytes())
    require(type(receipt["actual_return_code"]) is int and receipt["actual_return_code"]==0,"Saved review exit")
    require(review["saved_descriptor_review_passed"] is True and review["original_wrapper_return_code"]==1 and
            review["original_compiler_return_code"]==0 and review["original_failure_preserved"] is True,"Original failure history")
    translation={"device":"st_dev","inode":"st_ino","mode":"st_mode","links":"st_nlink",
                 "size":"st_size","mtime_ns":"st_mtime_ns","ctime_ns":"st_ctime_ns","sha256":"sha256"}
    for name,original in review["held_inputs_and_reviewer_sources"].items():
        require(set(original)==set(translation),"Unexpected original pin domain")
        current=pin(name);require(current=={translation[k]:value for k,value in original.items()},"Saved-review source/input changed")
        held[name]=current
    inventory=review["retained_failure_inventory"]
    actual_files=set();actual_dirs=[]
    for base,dirs,files in os.walk(VENDOR,followlinks=False):
        for n in dirs:
            p=Path(base)/n;require(not p.is_symlink() and p.is_dir(),"Retained nonordinary directory")
            actual_dirs.append(str(p.relative_to(VENDOR)))
        for n in files:actual_files.add(str((Path(base)/n).relative_to(VENDOR)))
    require(actual_files==set(inventory["files"]) and sorted(actual_dirs)==inventory["directories"],"Retained namespace changed")
    require("FAILED.json" in actual_files and "RESULT.json" not in actual_files,"Failed generation history changed")
    for name,original in inventory["files"].items():
        p=VENDOR/name;current=pin(p)
        require(set(original)==set(translation) and current=={translation[k]:value for k,value in original.items()},"Retained generated artifact changed")
        held[str(p)]=current
    # Reuse exact previously linked tool/runtime/header identities, not just current captures.
    previous=pin(OLD_BUILD_RESULT);require(previous["sha256"]==OLD_BUILD_RESULT_SHA,"Prior runtime evidence changed")
    held[str(OLD_BUILD_RESULT)]=previous
    previous=json.loads(OLD_BUILD_RESULT.read_bytes())["input_pins"]
    roots=(ST,TC,TP,REPO/"firmware/n6b/hal_conf")
    for name,original in previous.items():
        if any(Path(name).is_relative_to(root) for root in roots):
            require(pin(name)==original,"Previously compiled runtime/tool/header changed");held[name]=original
    bookend(held)
    require(candidate_namespace()==(set(inventory["files"]),inventory["directories"]),"Late retained namespace changed")
    return held


def elf_layout(raw):
    require(raw[:7]==b"\x7fELF\x01\x01\x01","Expected little-endian ARM ELF32")
    h=struct.unpack_from("<16sHHIIIIIHHHHHH",raw)
    require(h[2]==40 and h[8]==52 and h[9]==32,"ARM ELF header")
    entry=h[4];segments=[]
    for i in range(h[10]):
        t,off,address,paddr,filesz,memsz,flags,align=struct.unpack_from("<IIIIIIII",raw,h[5]+i*h[9])
        if t!=1:continue
        require(paddr==address and filesz<=memsz and off+filesz<=len(raw),"PT_LOAD extent")
        require(all(address+memsz<=lo or address>=hi for lo,hi in RESERVED),"ELF overlaps complete reserved SRAM pool")
        segments.append({"address":address,"file_offset":off,"file_bytes":filesz,"memory_bytes":memsz,"flags":flags})
    require(len(segments)==4,"Expected RX/data/stack/mailbox segments")
    code,data,stack,mail=segments
    require(code["address"]==0x34064000 and code["flags"]==5 and code["address"]+code["memory_bytes"]<=0x340F0000,"RX range")
    require(data["flags"]==6 and code["address"]+code["memory_bytes"]<=data["address"] and
            data["address"]+data["memory_bytes"]<=0x340F0000,"RW data range")
    require(stack["address"]==0x340F0000 and stack["memory_bytes"]==0x8000 and stack["file_bytes"]==0 and stack["flags"]==6,"Stack segment")
    require(mail["address"]==0x340F8000 and mail["memory_bytes"]==512 and mail["file_bytes"]==0 and mail["flags"]==6,"Mailbox segment")
    msp,reset=struct.unpack_from("<II",raw,code["file_offset"])
    require(msp==0x340F8000 and reset==entry and entry&1 and code["address"]<=entry-1<code["address"]+code["file_bytes"],"Vectors/entry")
    return {"entry_thumb":entry,"initial_msp":msp,"segments":segments,"reserved_pools":[list(x) for x in RESERVED]}


def run(out):
    out=Path(out)
    require(out.is_absolute() and out==out.resolve() and out.parent==HERE, "Use a fresh direct child of firmware_sram")
    require(not os.path.lexists(out), "Existing output cannot be overwritten/resumed")
    parent_stat=HERE.lstat();parent_identity=(parent_stat.st_dev,parent_stat.st_ino,parent_stat.st_mode)
    # Direct files pinned before any compilation; dependency discovery below adds
    # every preprocessor header before its first actual object compilation.
    direct = [HERE/x for x in ("build.py","main.c","startup.c","syscalls.c","mailbox.h","linker.ld","README.md","ABI.json")]
    held={str(p):pin(p) for p in direct}
    held.update(candidate_pins())
    candidate_record=json.loads((REVIEW/"SAVED_REVIEW_ACTUAL_01.json").read_bytes())["retained_failure_inventory"]
    expected_candidate_namespace=(set(candidate_record["files"]),candidate_record["directories"])
    runtime=[ST/"Npu/ll_aton"/(x+".c") for x in
             ("ll_aton","ll_aton_cipher","ll_aton_debug","ll_aton_dbgtrc","ll_aton_lib",
              "ll_aton_lib_sw_operators","ll_aton_runtime","ll_aton_util","ll_sw_float","ll_sw_integer",
              "ll_aton_stai_internal")]
    devices=[ST/"Npu/Devices/STM32N6xx"/(x+".c") for x in ("mcu_cache","npu_cache")]
    # HAL sources are retained for the exact runtime's optional clock/cache code;
    # gc-sections removes unused code. The adapter never calls board initialization.
    hal=[TP/"stm32n6xx-hal-driver/Src"/(x+".c") for x in
         ("stm32n6xx_hal","stm32n6xx_hal_rcc","stm32n6xx_hal_rcc_ex","stm32n6xx_hal_cacheaxi","stm32n6xx_hal_cortex")]
    sources=[HERE/"startup.c",HERE/"main.c",HERE/"syscalls.c",GEN/"nsl_qcfs_seed0.c",GEN/"stai_nsl_qcfs_seed0.c"]+runtime+devices+hal
    archive=ST/"Lib/GCC/ARMCortexM55/NetworkRuntime1100_CM55_GCC.a"
    tools={x:TC/"bin"/("arm-none-eabi-"+x) for x in ("gcc","size","readelf","nm","objcopy","objdump")}
    for p in sources+[archive]+list(tools.values()):hold(held,p)
    current=HERE.lstat()
    require(HERE==HERE.resolve() and (current.st_dev,current.st_ino,current.st_mode)==parent_identity,"Original output parent changed")
    parent_fd=os.open(HERE,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        current=os.fstat(parent_fd)
        require((current.st_dev,current.st_ino,current.st_mode)==parent_identity,"Parent FD changed")
        os.mkdir(out.name,mode=0o700,dir_fd=parent_fd)
        child=os.stat(out.name,dir_fd=parent_fd,follow_symlinks=False)
        identity=(child.st_dev,child.st_ino)
    finally:os.close(parent_fd)
    calls=[]
    def guard():
        s=HERE.lstat();require(HERE==HERE.resolve() and (s.st_dev,s.st_ino,s.st_mode)==parent_identity,"Original output parent changed")
        require(out==out.resolve() and (out.stat().st_dev,out.stat().st_ino)==identity, "Owned output directory changed")
    def write(name,data):
        guard()
        with (out/name).open("xb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        require(hashlib.sha256((out/name).read_bytes()).digest()==hashlib.sha256(data).digest(), "Publication bytes changed")
    def command(label,args):
        guard()
        record={"label":label,"argv":[str(x) for x in args],"cwd":str(out),"actual_return_code":None,"timed_out":False}
        start=time.monotonic()
        proc=None
        with (out/(label+".stdout")).open("xb") as stdout,(out/(label+".stderr")).open("xb") as stderr:
            try:
                proc=subprocess.Popen(record["argv"],cwd=out,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                                      env={"PATH":str(TC/"bin")+":/usr/bin:/bin","LANG":"C","LC_ALL":"C","TMPDIR":str(out)},
                                      start_new_session=True)
                try: proc.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    record["timed_out"]=True; os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=10)
            finally:
                if proc is not None and proc.poll() is None:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=10)
                record["actual_return_code"]=None if proc is None else proc.returncode
                record["elapsed_seconds"]=time.monotonic()-start
                stdout.flush();stderr.flush();os.fsync(stdout.fileno());os.fsync(stderr.fileno())
                calls.append(record)
                write(label+".json",encoded(record))
        require(not record["timed_out"] and type(record["actual_return_code"]) is int and record["actual_return_code"]==0, f"Failed command: {label}; raw logs retained")
        return (out/(label+".stdout")).read_text()
    try:
        write("INTENT.json",encoded({"schema":1,"kind":"n6_sram_offline_firmware_build_intent","direct_pins":held,**LIMITS}))
        version=command("version",[tools["gcc"],"--version"])
        require(version.splitlines()[0] == "arm-none-eabi-gcc (Arm GNU Toolchain 13.2.rel1 (Build arm-13.7)) 13.2.1 20231009",
                "Unexpected ARM compiler version")
        # Explicitly record the actual multilib runtime archives and executable
        # subprocesses selected by this compiler, without executing target code.
        for i,name in enumerate(("libgcc.a","libc_nano.a","libm.a","libnosys.a","nano.specs","nosys.specs")):
            selected=command(f"library_{i}",[tools["gcc"],*FLAGS,"-print-file-name="+name]).strip()
            p=Path(selected).resolve(); require(p.is_file(),f"Missing selected toolchain runtime {name}");hold(held,p)
        for i,name in enumerate(("cc1","as","ld")):
            selected=command(f"program_{i}",[tools["gcc"],"-print-prog-name="+name]).strip()
            p=Path(selected).resolve();require(p.is_file(),f"Missing compiler program {name}");hold(held,p)
        base=[tools["gcc"],*FLAGS,*DEFS,*["-I"+str(p) for p in INCLUDES],"-O2","-g3",
              "-ffunction-sections","-fdata-sections","-fno-common"]
        compile_args=[]
        for i,source in enumerate(sources):
            extra=["-include","stm32n6xx_hal.h"] if source in devices+hal else []
            dep=out/f"object_{i:02}.d"
            command(f"deps_{i:02}",[*base,*extra,"-M","-MF",dep,"-MT",f"object_{i:02}.o",source])
            payload=dep.read_text().replace("\\\n", " ").split(":",1)[1]
            for item in shlex.split(payload):
                path=Path(item).resolve();current=pin(path)
                if str(path) in held: require(held[str(path)]==current,"Dependency changed during discovery")
                else: held[str(path)]=current
            compile_args.append([*base,*extra,"-c",source,"-o",out/f"object_{i:02}.o"])
        bookend(held)
        write("COMPILE_INPUTS.json",encoded(held))
        objects={}
        for i,args in enumerate(compile_args):
            command(f"compile_{i:02}",args)
            object_path=out/f"object_{i:02}.o"
            objects[str(object_path)]=pin(object_path)
        bookend({**held,**objects})
        elf=out/"n6_sram.elf"
        command("link",[tools["gcc"],*FLAGS,"-T",HERE/"linker.ld","-nostartfiles","-Wl,--gc-sections",
                        "-Wl,--fatal-warnings","-Wl,--print-memory-usage","-Wl,-Map="+str(out/"n6_sram.map"),
                        *[out/f"object_{i:02}.o" for i in range(len(sources))],archive,
                        "--specs=nano.specs","--specs=nosys.specs","-lm","-o",elf])
        require(elf.is_file() and elf.stat().st_size>0,"Missing ELF")
        command("size",[tools["size"],"-A",elf])
        header=command("readelf",[tools["readelf"],"-h","-l","-S","-A",elf])
        require("Machine:" in header and "ARM" in header,"Not an ARM ELF")
        undefined=command("undefined",[tools["nm"],"-u",elf]);require(not undefined.strip(),"Undefined linked symbols")
        symbols=command("symbols",[tools["nm"],"-n","-S",elf])
        require("g_mailbox" in symbols and "Reset_Handler" in symbols,"Missing protocol/startup symbols")
        command("disassembly",[tools["objdump"],"-d",elf])
        layout=elf_layout(elf.read_bytes())
        command("binary",[tools["objcopy"],"-O","binary",elf,out/"n6_sram.bin"])
        bookend({**held,**objects});guard()
        artifacts={p.name:pin(p) for p in sorted(out.iterdir()) if p.is_file()}
        require(len(artifacts)==len(list(out.iterdir())),"Unexpected output directory/type")
        report={"schema":1,"kind":"n6_sram_offline_firmware_build","arm_compile_link_succeeded":True,
                "actual_process_exit":None,"elf_layout":layout,"calls":calls,"input_pins":held,"artifacts_before_result":artifacts,
                "original_generation_wrapper_exit":1,"original_st_generate_exit":0,"saved_review_exit":0,
                "weights_path":str(GEN/"nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw"),
                "limits":["No FSBL/SRAM-clock/NPU/RIF/watchdog initialization supplied or verified.",
                          "RAM-load image only; no loader, flashing, device execution or inference performed.",
                          "No native or on-target numerical parity claim; all five logits require later validation.",
                          "Discovered compilation headers and selected tools/libraries are pinned, not all transitive host libraries.",
                          "Metadata/hash bookends are finite observations, not atomic snapshots."],**LIMITS}
        report["content_sha256"]=hashlib.sha256(encoded(report)).hexdigest()
        write("RESULT.json",encoded(report)); result_pin=pin(out/"RESULT.json")
        bookend(held)
        require(set(p.name for p in out.iterdir())==set(artifacts)|{"RESULT.json"},"Late output namespace change")
        for name,expected in {**artifacts,"RESULT.json":result_pin}.items():require(pin(out/name)==expected,"Output changed at endpoint")
        bookend(held);guard()
        allpins={**held,**{str(out/n):p for n,p in {**artifacts,"RESULT.json":result_pin}.items()}}
        for name,p in allpins.items():
            s=Path(name).lstat();require(all(getattr(s,k)==value for k,value in p.items() if k!="sha256"),"Final original stat changed")
        require(set(p.name for p in out.iterdir())==set(artifacts)|{"RESULT.json"},"Final exact output namespace changed")
        require(candidate_namespace()==expected_candidate_namespace,"Final retained candidate namespace changed")
        return report
    except BaseException as exc:
        try: write("FAILED.json",encoded({"schema":1,"exception":str(exc),"calls":calls,**LIMITS}))
        except BaseException: pass
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument("--output-dir",required=True,type=Path)
    args=parser.parse_args(argv)
    try: result=run(args.output_dir)
    except Exception as exc:
        print(f"OFFLINE BUILD FAILED: {exc}",file=sys.stderr);return 1
    print(json.dumps({"arm_compile_link_succeeded":True,"content_sha256":result["content_sha256"],**LIMITS},sort_keys=True));return 0

if __name__=="__main__":raise SystemExit(main())
