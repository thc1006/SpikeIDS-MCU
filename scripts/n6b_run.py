"""Stage 1 host driver: deploy the B2 NPU firmware via pyOCD takeover and measure NPU latency.

Prereq (one-time board actions): weights flashed to XSPI2 0x71000000 (firmware/n6b/flash_weights.sh
in BOOT1=DEV mode), then BOOT1=NORMAL + power-cycle so the OOB maps XSPI2 / enables the NPU. This
driver then takes over (IWDG-defanged), loads n6b.elf into AXISRAM1, runs stai_ids_run on the
Neural-ART timed with DWT, and reports per-iteration cycles + latency.
"""
from __future__ import annotations
import argparse, json, statistics, sys, time
from datetime import datetime, timezone
from pathlib import Path
from elftools.elf.elffile import ELFFile
from pyocd.core.exceptions import TransferFaultError, TransferError
from pyocd.core.helpers import ConnectHelper
from pyocd.core.target import Target

ROOT = Path(__file__).resolve().parent.parent
MB = 0x340F8000; MAGIC = 0x4E365542; VER = 1
OFF = {"magic":0,"version":4,"state":8,"cmd":12,"seq":16,"ack":20,"err":24,"n_results":28,
       "param":32,"boot":64,"last_rc":96,"last_argmax":100,"sink":104,"cycles":108}
STATE = {0:"IDLE",1:"RUNNING",2:"DONE",3:"ERROR",4:"FAULT"}
IWDG_KR = 0x56004800

class B:
    def __init__(s, freq, wait):
        from pyocd.core.exceptions import DebugError
        t0=time.time()
        while True:
            try:
                s.sess=ConnectHelper.session_with_chosen_probe(target_override="stm32n657x0hxq",
                    options={"connect_mode":"halt","frequency":freq,"resume_on_disconnect":False})
                if s.sess is None: raise DebugError("no probe")
                s.sess.open(); break
            except Exception as e:
                if time.time()-t0>wait: raise
                try: s.sess and s.sess.close()
                except Exception: pass
                s.sess=None; print(f"  waiting: {type(e).__name__}",flush=True); time.sleep(0.5)
        s.t=s.sess.board.target; s.seq=0
    def clr(s):
        try: s.t.dp.clear_sticky_err()
        except Exception: pass
    def w32(s,a,v): s.t.write32(a,v)
    def r32(s,a): return s.t.read32(a)
    def takeover(s, elf):
        t=s.t; t.halt()
        cpuid=s.r32(0xE000ED00); assert (cpuid&0xFFF0)==0xD220, f"CPUID {cpuid:#x}"
        try: s.w32(IWDG_KR,0xAAAA)
        except Exception: pass
        with open(elf,"rb") as f:
            e=ELFFile(f); entry=e.header["e_entry"]; loaded=0
            for seg in e.iter_segments():
                if seg["p_type"]!="PT_LOAD" or seg["p_filesz"]==0: continue
                d=seg.data(); t.write_memory_block8(seg["p_paddr"],d)
                assert bytes(t.read_memory_block8(seg["p_paddr"],len(d)))==d,"verify"
                loaded+=len(d)
            est=next(sm["st_value"] for sm in e.get_section_by_name(".symtab").iter_symbols() if sm.name=="_estack")
        for r,v in (("xpsr",0x01000000),("msp",est),("psp",est),("sp",est),("lr",0xFFFFFFFF),("pc",entry&~1),("primask",1),("control",0)):
            t.write_core_register(r,v)
        t.resume()
        t0=time.time()
        while time.time()-t0<3:
            try:
                if s.r32(MB+OFF["magic"])==MAGIC: break
            except (TransferFaultError,TransferError): s.clr()
            time.sleep(0.01)
        else:
            raise SystemExit("firmware did not come up")
        s.seq=s.r32(MB+OFF["seq"])
        return {"loaded":loaded,"entry":entry,
                "boot":[s.r32(MB+OFF["boot"]+4*i) for i in range(8)]}
    def run(s,cmd,p0,timeout=30):
        s.t.write_memory_block32(MB+OFF["param"],[p0]+[0]*7)
        s.w32(MB+OFF["cmd"],cmd); s.seq+=1; s.w32(MB+OFF["seq"],s.seq)
        t0=time.time()
        while True:
            try:
                st=s.r32(MB+OFF["state"]); ack=s.r32(MB+OFF["ack"])
            except (TransferFaultError,TransferError): s.clr(); time.sleep(0.01); st=1; ack=-1
            if st in (2,3,4) and ack==s.seq: break
            if time.time()-t0>timeout: raise TimeoutError(f"cmd {cmd} state={STATE.get(st)}")
            time.sleep(0.002)
        n=s.r32(MB+OFF["n_results"])
        cyc=s.t.read_memory_block32(MB+OFF["cycles"],n) if n else []
        return {"state":STATE[st],"err":s.r32(MB+OFF["err"]),"rc":s.r32(MB+OFF["last_rc"]),
                "argmax":s.r32(MB+OFF["last_argmax"]),"cycles":cyc}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--elf",default=str(ROOT/"firmware/n6b/build/n6b.elf"))
    ap.add_argument("--freq",type=int,default=4_000_000); ap.add_argument("--wait",type=float,default=600)
    ap.add_argument("--iters",type=int,default=100); ap.add_argument("--cpu-hz",type=float,default=800e6)
    ap.add_argument("--out",default=None)
    a=ap.parse_args()
    b=B(a.freq,a.wait)
    try:
        tk=b.takeover(Path(a.elf))
        print(f"firmware up: loaded {tk['loaded']}B  boot={[hex(x) for x in tk['boot']]}",flush=True)
        print(f"  CPUID={tk['boot'][0]:#x} stai_init_rc={tk['boot'][1]} ctx={tk['boot'][2]}B "
              f"in={tk['boot'][3]} out={tk['boot'][4]} iwdg_ok={tk['boot'][5]}")
        r=b.run(1,a.iters,timeout=60)
        cyc=sorted(r["cycles"])
        if r["state"]!="DONE" or not cyc:
            print(f"INFER {r['state']} err={r['err']:#x} rc={r['rc']}"); return
        med=statistics.median(cyc); us=med/a.cpu_hz*1e6
        print(f"=== NPU inference: {r['state']} rc={r['rc']} argmax={r['argmax']} ===")
        print(f"  cycles min/med/max = {cyc[0]}/{med:.0f}/{cyc[-1]}  →  median {us:.3f} us @ {a.cpu_hz/1e6:.0f}MHz")
        out=Path(a.out) if a.out else ROOT/"results"/f"n6_npu_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out.write_text(json.dumps({"timestamp":datetime.now(timezone.utc).isoformat(),"boot":tk["boot"],
            "iters":a.iters,"cpu_hz":a.cpu_hz,"cycles":r["cycles"],"median_cyc":med,"median_us":us,
            "rc":r["rc"],"argmax":r["argmax"]},indent=1))
        print(f"wrote {out}")
    finally:
        b.sess.close()

if __name__=="__main__": main()
