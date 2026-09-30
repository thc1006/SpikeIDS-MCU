#!/usr/bin/env python3
"""Load the CPU-int8 baseline firmware (M55, Helium/MVE) via pyOCD and read back the DWT-timed
per-inference cycle counts. The firmware runs N inferences on startup, stores cycles[i] in the
mailbox, SCB_CleanDCache()s, publishes MAGIC and spins; this driver waits for MAGIC then reads.
Same-chip counterpart to scripts/n6_validate_pathB.py (NPU)."""
from __future__ import annotations
import argparse, json, statistics, sys, time
from datetime import datetime, timezone
from pathlib import Path
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper
from pyocd.core.exceptions import TransferFaultError, TransferError

ROOT = Path(__file__).resolve().parent.parent
MB = 0x340F8000; MAGIC = 0x4E365542
OFF = {"magic":0,"version":4,"state":8,"cmd":12,"seq":16,"ack":20,"err":24,"n_results":28,
       "param":32,"boot":64,"last_rc":96,"last_argmax":100,"sink":104,"cycles":108}


def run(elf: Path, cpu_hz: float, probe_wait: float, out: Path | None):
    t0 = time.time(); sess = None
    while True:
        try:
            sess = ConnectHelper.session_with_chosen_probe(target_override="stm32n657x0hxq",
                options={"connect_mode":"halt","frequency":4_000_000,"resume_on_disconnect":False})
            if sess is None: raise RuntimeError("no probe")
            sess.open(); break
        except Exception as e:
            if time.time()-t0 > probe_wait: raise
            try: sess and sess.close()
            except Exception: pass
            print(f"  waiting for probe: {type(e).__name__}", flush=True); time.sleep(0.5)
    t = sess.board.target
    try:
        try: t.reset_and_halt()
        except Exception: t.halt()
        cpuid = t.read32(0xE000ED00); assert (cpuid & 0xFFF0) == 0xD220, f"CPUID {cpuid:#x}"
        loaded = 0; sp0 = None
        with open(elf, "rb") as f:
            e = ELFFile(f)
            for seg in e.iter_segments():
                if seg["p_type"] != "PT_LOAD" or seg["p_filesz"] == 0: continue
                d = seg.data(); a = seg["p_paddr"]; t.write_memory_block8(a, d)
                assert bytes(t.read_memory_block8(a, len(d))) == d, "verify"
                if sp0 is None and a == 0x34064000: sp0 = int.from_bytes(d[0:4], "little")
                loaded += len(d)
            entry = e.header["e_entry"]
        for r, v in (("xpsr",0x01000000),("msp",sp0),("psp",sp0),("sp",sp0),
                     ("pc",entry & ~1),("primask",1),("control",0)):
            if v is not None: t.write_core_register(r, v)
        for r in ("msplim","psplim"):
            try: t.write_core_register(r, 0)
            except Exception: pass
        t.resume()
        print(f"[cpu] loaded {loaded}B, started @ {entry:#x} (SP={sp0:#x})", flush=True)
        # wait for the firmware to finish its N inferences + publish MAGIC
        t1 = time.time(); ok = False
        while time.time()-t1 < 5.0:
            try:
                if t.read32(MB+OFF["magic"]) == MAGIC: ok = True; break
            except (TransferFaultError, TransferError):
                try: t.dp.clear_sticky_err()
                except Exception: pass
            time.sleep(0.02)
        t.halt()
        if not ok:
            pc = t.read_core_register("pc")
            raise SystemExit(f"[cpu] no MAGIC: pc={pc:#x} magic={t.read32(MB+OFF['magic']):#x} "
                             f"boot7/phase={t.read32(MB+OFF['boot']+28):#x} init_rc={t.read32(MB+OFF['boot']+4):#x}")
        n = t.read32(MB+OFF["n_results"])
        boot = [t.read32(MB+OFF["boot"]+4*i) for i in range(8)]
        argmax = t.read32(MB+OFF["last_argmax"]); rc = t.read32(MB+OFF["last_rc"])
        overhead = t.read32(MB+OFF["param"])
        reported_hz = t.read32(MB+OFF["param"]+8)   # param[2] = on-device HAL_RCC_GetCpuClockFreq()
        cyc = [t.read32(MB+OFF["cycles"]+4*i) for i in range(min(n, 512))]
        # independent empirical clock: DWT CYCCNT delta over a known wall-clock interval while spinning
        CYCCNT = 0xE0001004
        t.halt(); e0 = t.read32(CYCCNT); t.resume(); time.sleep(2.0); t.halt(); e1 = t.read32(CYCCNT)
        emp_hz = ((e1 - e0) & 0xFFFFFFFF) / 2.0
    finally:
        try: sess.close()
        except Exception: pass

    # use the empirically-measured clock (ground truth) for the latency, not an assumed value
    clk = emp_hz if emp_hz > 1e6 else cpu_hz
    cyc_s = sorted(cyc); med = statistics.median(cyc_s)
    us = med / clk * 1e6
    ccr = boot[6]; dcache = bool(ccr & (1 << 16)); icache = bool(ccr & (1 << 17))
    print(f"[cpu] init_rc={boot[1]} set_act_rc={boot[5]} ctx={boot[2]}B in={boot[3]} out={boot[4]} "
          f"argmax={argmax} rc={rc} n={n}")
    print(f"[cpu] CCR={ccr:#x} -> D-cache={'ON' if dcache else 'OFF'} I-cache={'ON' if icache else 'OFF'} "
          f"| cyc() overhead={overhead} cyc")
    print(f"[cpu] CLOCK: on-device reported={reported_hz/1e6:.1f}MHz  empirical(CYCCNT/2s)={emp_hz/1e6:.1f}MHz")
    print(f"=== M55 CPU-int8 inference: cycles min/med/max = {cyc_s[0]}/{med:.0f}/{cyc_s[-1]}  "
          f"→  median {us:.3f} us @ {clk/1e6:.1f}MHz (empirical) ===")
    res = {"timestamp":datetime.now(timezone.utc).isoformat(),"platform":"STM32N6_M55_CPU_int8_MVE",
           "clock_hz":clk,"reported_hz":reported_hz,"empirical_hz":emp_hz,"n":n,"cycles":cyc,
           "median_cyc":med,"median_us":us,"min_us":cyc_s[0]/clk*1e6,"max_us":cyc_s[-1]/clk*1e6,
           "argmax":argmax,"boot":boot,"ccr":ccr,"dcache_on":dcache,"icache_on":icache,"cyc_overhead":overhead}
    if out:
        out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(res, indent=1))
        print(f"[cpu] wrote {out}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default="/tmp/claude-1000/-home-thc1006-dev-SpikeIDS-MCU/e287e8df-b593-44ae-b9b0-05620b77d9a7/scratchpad/n6cpu_fw/n6cpu.elf")
    ap.add_argument("--cpu-hz", type=float, default=800e6)
    ap.add_argument("--probe-wait", type=float, default=40.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = Path(a.out) if a.out else ROOT/"results"/f"n6_cpu_int8_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    run(Path(a.elf), a.cpu_hz, a.probe_wait, out)


if __name__ == "__main__": main()
