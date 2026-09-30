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
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
VENDOR = REPO / "results/ppk2_n6_bringup_20260925_nAivHM/vendor_actual_01"
RESULT_SHA = "220e16ebadb171e1bfecbcfc1a94d5e92a5c098ae2cbcf631289d163bff0e4e4"
ST = Path("/home/thc1006/opt/stedgeai/3.0/Middlewares/ST/AI")
TC = Path("/home/thc1006/opt/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi")
TP = REPO / "firmware/n6/third_party"
GEN = VENDOR / "generate"
FLAGS = ["-mcpu=cortex-m55", "-mthumb", "-mfloat-abi=hard", "-mfpu=auto", "-mcmse"]
DEFS = ["-DSTM32N657xx", "-DCORE_CM55", "-DUSE_HAL_DRIVER",
        "-DLL_ATON_PLATFORM=LL_ATON_PLAT_STM32N6", "-DLL_ATON_OSAL=LL_ATON_OSAL_BARE_METAL",
        "-DLL_ATON_RT_MODE=LL_ATON_RT_POLLING", "-DLL_ATON_SW_FALLBACK=1", "-DUSE_NPU_CACHE"]
INCLUDES = [HERE, GEN, ST/"Inc", ST/"Npu/ll_aton", ST/"Npu/Devices/STM32N6xx",
            TP/"CMSIS_6/CMSIS/Core/Include", TP/"cmsis-device-n6/Include",
            TP/"stm32n6xx-hal-driver/Inc", REPO/"firmware/n6b/hal_conf"]
LIMITS = {"board_ready": False, "board_validated": False, "energy_measured": False,
          "deployment_accepted": False, "compiler_semantic_parity_verified": False}


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


def run(out):
    out=Path(out)
    require(out.is_absolute() and out==out.resolve() and out.parent==HERE, "Use a fresh direct child of firmware_v5")
    require(not os.path.lexists(out), "Existing output cannot be overwritten/resumed")
    # Direct files pinned before any compilation; dependency discovery below adds
    # every preprocessor header before its first actual object compilation.
    direct = [HERE/x for x in ("build.py","main.c","startup.c","syscalls.c","mailbox.h","linker.ld","README.md")]
    result_pin=pin(VENDOR/"RESULT.json")
    require(result_pin["sha256"]==RESULT_SHA, "Wrong vendor result")
    result=json.loads((VENDOR/"RESULT.json").read_text())
    held={str(p):pin(p) for p in direct}
    held[str(VENDOR/"RESULT.json")]=result_pin
    for rel, original in result["artifacts_before_result"]["files"].items():
        if rel.startswith("generate/"):
            p=VENDOR/rel; current=pin(p)
            translations={"device":"st_dev","inode":"st_ino","mode":"st_mode","links":"st_nlink",
                          "size":"st_size","mtime_ns":"st_mtime_ns","ctime_ns":"st_ctime_ns","sha256":"sha256"}
            require(all(current[translations[k]]==v for k,v in original.items()), f"Held generated artifact changed: {rel}")
            held[str(p)]=current
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
    tools={x:TC/"bin"/("arm-none-eabi-"+x) for x in ("gcc","size","readelf","nm","objcopy")}
    for p in sources+[archive]+list(tools.values()): held[str(p)]=pin(p)
    out.mkdir(mode=0o700)
    identity=(out.stat().st_dev,out.stat().st_ino)
    calls=[]
    def guard():
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
        require(not record["timed_out"] and record["actual_return_code"]==0, f"Failed command: {label}; raw logs retained")
        return (out/(label+".stdout")).read_text()
    try:
        write("INTENT.json",encoded({"schema":1,"kind":"n6_v5_offline_firmware_build_intent","direct_pins":held,**LIMITS}))
        version=command("version",[tools["gcc"],"--version"])
        require(version.splitlines()[0] == "arm-none-eabi-gcc (Arm GNU Toolchain 13.2.rel1 (Build arm-13.7)) 13.2.1 20231009",
                "Unexpected ARM compiler version")
        # Explicitly record the actual multilib runtime archives and executable
        # subprocesses selected by this compiler, without executing target code.
        for i,name in enumerate(("libgcc.a","libc_nano.a","libm.a","libnosys.a","nano.specs","nosys.specs")):
            selected=command(f"library_{i}",[tools["gcc"],*FLAGS,"-print-file-name="+name]).strip()
            p=Path(selected).resolve(); require(p.is_file(),f"Missing selected toolchain runtime {name}"); held[str(p)]=pin(p)
        for i,name in enumerate(("cc1","as","ld")):
            selected=command(f"program_{i}",[tools["gcc"],"-print-prog-name="+name]).strip()
            p=Path(selected).resolve();require(p.is_file(),f"Missing compiler program {name}");held[str(p)]=pin(p)
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
        elf=out/"n6_v5.elf"
        command("link",[tools["gcc"],*FLAGS,"-T",HERE/"linker.ld","-nostartfiles","-Wl,--gc-sections",
                        "-Wl,--fatal-warnings","-Wl,--print-memory-usage","-Wl,-Map="+str(out/"n6_v5.map"),
                        *[out/f"object_{i:02}.o" for i in range(len(sources))],archive,
                        "--specs=nano.specs","--specs=nosys.specs","-lm","-o",elf])
        require(elf.is_file() and elf.stat().st_size>0,"Missing ELF")
        command("size",[tools["size"],"-A",elf])
        header=command("readelf",[tools["readelf"],"-h","-l","-S","-A",elf])
        require("Machine:" in header and "ARM" in header,"Not an ARM ELF")
        undefined=command("undefined",[tools["nm"],"-u",elf]);require(not undefined.strip(),"Undefined linked symbols")
        symbols=command("symbols",[tools["nm"],"-n","-S",elf])
        require("g_mailbox" in symbols and "Reset_Handler" in symbols,"Missing protocol/startup symbols")
        command("binary",[tools["objcopy"],"-O","binary",elf,out/"n6_v5.bin"])
        bookend({**held,**objects});guard()
        artifacts={p.name:pin(p) for p in sorted(out.iterdir()) if p.is_file()}
        require(len(artifacts)==len(list(out.iterdir())),"Unexpected output directory/type")
        report={"schema":1,"kind":"n6_v5_offline_firmware_build","arm_compile_link_succeeded":True,
                "calls":calls,"input_pins":held,"artifacts_before_result":artifacts,
                "weights_path":str(GEN/"nsl_qcfs_seed0_atonbuf.xSPI2.raw"),
                "limits":["No FSBL/clock/XSPI/RIF/watchdog initialization supplied or verified.",
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
