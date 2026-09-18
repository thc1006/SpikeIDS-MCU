"""Host driver for firmware/n6 (STM32N6570-DK, Cortex-M55) via pyOCD + ST-LINK.

Takes over the running board without any ST tool: halt, disable the core caches, load the
RAM image into SRAM3, point SP/PC at it, resume, then drive experiments through the mailbox.
Every experiment records per-iteration DWT cycle counts; the report carries the platform
state captured by the firmware (CPU/XSPI clocks decoded by the HAL, cache/MPU state at entry)
plus a host-side measurement of the CPU clock (DWT cycles vs wall clock).

Usage:
    uv run scripts/n6_bench.py --elf firmware/n6/build/n6_bench.elf --plan all
    uv run scripts/n6_bench.py --probe            # only test which memories are readable
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from elftools.elf.elffile import ELFFile
from pyocd.core.exceptions import TransferFaultError, TransferError
from pyocd.core.helpers import ConnectHelper
from pyocd.core.target import Target

ROOT = Path(__file__).resolve().parent.parent

# ---- mailbox layout (must match firmware/n6/src/mailbox.h) ----------------------------
MB_ADDR = 0x34260000
MB_MAGIC = 0x4E36424E
MB_VERSION = 3
MB_MAX_RES = 1024
# mailbox.h: magic, version, boot[8], state, cmd, seq, ack, err, n_results, param[16], info[64], sink, results[]
_b = 8 + 8 * 4                      # after magic+version+boot[8]
OFF = {"magic": 0, "version": 4, "boot": 8, "state": _b, "cmd": _b + 4, "seq": _b + 8,
       "ack": _b + 12, "err": _b + 16, "n_results": _b + 20, "param": _b + 24,
       "info": _b + 24 + 16 * 4, "sink": _b + 24 + 16 * 4 + 64 * 4,
       "results": _b + 24 + 16 * 4 + 64 * 4 + 4}
BOOT = ["IWDG_SR", "WWDG_CR", "RCC_APB1ENR1", "WWDG_CFR", "IWDG_OK", "WWDG_PRESENT", "SETUP_FAULT", "PHASE"]
STATE = {0: "IDLE", 1: "RUNNING", 2: "DONE", 3: "ERROR", 4: "FAULT"}
CMD = {"NOP": 0, "READ_BW": 1, "MLP_FP32": 2, "MLP_S8": 3, "FILL": 4, "MEMCPY": 5, "PEEK": 6}
CM_ICACHE, CM_DCACHE, CM_INVAL_EACH = 1, 2, 4
CACHE_MODES = {"off": 0, "on_cold": CM_ICACHE | CM_DCACHE | CM_INVAL_EACH, "on_warm": CM_ICACHE | CM_DCACHE}
RW = {"ldr32": 0, "ldrd64": 1, "mve128": 2, "ldm32x8": 3}
INFO = ["CPUID", "CCR_AT_ENTRY", "MPU_CTRL_AT_ENTRY", "MPU_TYPE", "CPU_HZ_HAL", "SYS_HZ_HAL",
        "XSPI2_KER_HZ_HAL", "XSPI1_KER_HZ_HAL", "XSPI2_CR", "XSPI2_DCR1", "XSPI2_DCR2", "XSPI2_CCR",
        "XSPI2_TCR", "RCC_AHB5ENR", "RCC_APB5ENR", "LTDC_WAS_ON", "CLIDR", "CCSIDR_I", "CCSIDR_D",
        "FPSCR", "CFSR_LAST", "HFSR_LAST", "BFAR_LAST", "FAULT_PC", "MB_VERSION", "BUILD_ID", "IWDG_SR", "WWDG_CR"]

# ---- memory map used by the experiments (secure aliases) -----------------------------
SRAM2 = 0x34100000      # 1 MB   weights (SRAM condition)
SRAM4 = 0x34270000      # 448 KB scratch / work buffers
SRAM1 = 0x34064000      # 624 KB fallback scratch
XSPI2 = 0x70000000      # memory-mapped external NOR flash (weights, flash condition)
XSPI1 = 0x90000000      # memory-mapped external PSRAM (informational)
DWT_CYCCNT = 0xE0001004
SCB_CCR = 0xE000ED14

# Model shapes: v3 IDS_MLP on the four datasets (d -> 256 -> 256 -> 128 -> C) and the RA4E1
# CAN-IDS width sweep (11 -> H -> H -> H/2 -> 5), so the N6 columns line up with both papers.
MODELS = {
    "v3_nslkdd":  (41, 256, 256, 128, 5),
    "v3_unsw":    (34, 256, 256, 128, 10),
    "v3_cicids":  (78, 256, 256, 128, 15),
    "v3_iot23":   (23, 256, 256, 128, 5),
    "can_h256":   (11, 256, 256, 128, 5),
    "can_h128":   (11, 128, 128, 64, 5),
    "can_h96":    (11, 96, 96, 48, 5),
    "can_h64":    (11, 64, 64, 32, 5),
    "can_h32":    (11, 32, 32, 16, 5),
}


def macs(d): return d[0] * d[1] + d[1] * d[2] + d[2] * d[3] + d[3] * d[4]
def outs(d): return d[1] + d[2] + d[3] + d[4]


class Board:
    """Open the debug session. The OOB firmware makes the core's access port unreachable
    ~1 min after boot (low-power state), so with wait_s > 0 we retry the connection until the
    board appears and then halt it at once; the caller must take over immediately."""
    def __init__(self, uid: str | None, freq: int, wait_s: float = 0.0):
        from pyocd.core.exceptions import DebugError
        t0 = time.time()
        while True:
            try:
                self.session = ConnectHelper.session_with_chosen_probe(
                    unique_id=uid, target_override="stm32n657x0hxq",
                    options={"connect_mode": "halt", "frequency": freq, "resume_on_disconnect": False})
                if self.session is None:
                    raise DebugError("no probe found")
                self.session.open()
                break
            except Exception as e:          # DebugError, TransferError, ProbeError (USB gone mid-replug), OSError
                if time.time() - t0 > wait_s:
                    raise
                try:
                    if getattr(self, "session", None) is not None:
                        self.session.close()
                except Exception:
                    pass
                self.session = None
                print(f"  waiting for board: {type(e).__name__}", flush=True)
                time.sleep(0.5)
        print(f"connected after {time.time() - t0:.1f} s", flush=True)
        self.t = self.session.board.target
        self.seq = 0

    def close(self):
        self.session.close()

    # -- raw helpers --
    def r32(self, a): return self.t.read32(a)
    def w32(self, a, v): self.t.write32(a, v)
    def readable(self, a):
        try:
            self.t.read32(a); return True
        except (TransferFaultError, TransferError):
            return False

    def probe(self):
        pts = {"SRAM1_S 0x34064000": SRAM1, "SRAM2_S 0x34100000": SRAM2, "SRAM3_S 0x34200000": 0x34200000,
               "SRAM4_S 0x34270000": SRAM4, "SRAM5_S 0x342E0000": 0x342E0000, "SRAM6_S 0x34350000": 0x34350000,
               "CACHEAXI_S 0x343C0000": 0x343C0000, "FLEXRAM_S 0x34000000": 0x34000000,
               "XSPI2 NOR 0x70000000": XSPI2, "XSPI2 NOR +1MB": XSPI2 + 0x100000,
               "XSPI2 NOR +64MB": XSPI2 + 0x4000000, "XSPI1 PSRAM 0x90000000": XSPI1,
               "DTCM_S 0x30000000": 0x30000000, "ITCM_S 0x10000000": 0x10000000}
        return {k: self.readable(v) for k, v in pts.items()}

    # -- takeover --
    def takeover(self, elf_path: Path, timeout=3.0):
        t = self.t
        t.halt()
        # Feed the IWDG the OOB may have started, so it does not reset us mid-load. KR write of
        # 0xAAAA needs no unlock; the address is the Secure IWDG (we take over in Secure state).
        IWDG_S_KR = 0x56004800
        try:
            self.w32(IWDG_S_KR, 0xAAAA)
        except Exception:
            pass
        cpuid = self.r32(0xE000ED00)
        assert (cpuid & 0xFFF0) == 0xD220, f"not a Cortex-M55: CPUID={cpuid:#x}"
        pre = {"pc": t.read_core_register("pc"), "sp": t.read_core_register("sp"),
               "xpsr": t.read_core_register("xpsr"), "ccr": self.r32(SCB_CCR)}
        # Disable I/D caches from the debugger BEFORE loading: the load goes through the AXI
        # port, and the firmware then invalidates (never cleans) whatever the OOB left behind.
        self.w32(SCB_CCR, pre["ccr"] & ~((1 << 16) | (1 << 17)))
        # Disable the OOB's MPU before the first fetch from SRAM3 (it could be marked XN).
        pre["mpu_ctrl"] = self.r32(0xE000ED94)
        self.w32(0xE000ED94, 0)
        with open(elf_path, "rb") as f:
            elf = ELFFile(f)
            entry = elf.header["e_entry"]
            loaded = 0
            for seg in elf.iter_segments():
                if seg["p_type"] != "PT_LOAD" or seg["p_filesz"] == 0:
                    continue
                data = seg.data()
                t.write_memory_block8(seg["p_paddr"], data)
                back = bytes(t.read_memory_block8(seg["p_paddr"], len(data)))
                assert back == data, f"verify failed at {seg['p_paddr']:#x}"
                loaded += len(data)
            estack = next(s["st_value"] for s in elf.get_section_by_name(".symtab").iter_symbols() if s.name == "_estack")
        t.write_core_register("xpsr", 0x01000000)      # thread mode, Thumb
        t.write_core_register("msp", estack)
        t.write_core_register("psp", estack)
        t.write_core_register("sp", estack)
        t.write_core_register("lr", 0xFFFFFFFF)
        t.write_core_register("pc", entry & ~1)
        t.write_core_register("primask", 1)
        t.write_core_register("control", 0)
        t.resume()
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.r32(MB_ADDR + OFF["magic"]) == MB_MAGIC:
                break
            time.sleep(0.01)
        else:
            st = t.get_state()
            mbst = self.r32(MB_ADDR + OFF["state"])
            info = self.info()
            t.halt()
            raise SystemExit(f"firmware did not come up: core={st} mb_state={STATE.get(mbst, mbst)} "
                             f"pc={t.read_core_register('pc'):#x} CFSR={info['CFSR_LAST']:#x} "
                             f"HFSR={info['HFSR_LAST']:#x} BFAR={info['BFAR_LAST']:#x} fault_pc={info['FAULT_PC']:#x}")
        assert self.r32(MB_ADDR + OFF["version"]) == MB_VERSION
        # Read the fast boot snapshot IMMEDIATELY (watchdog diagnosis), before anything slow.
        boot = [self.r32(MB_ADDR + OFF["boot"] + 4 * i) for i in range(8)]
        self.boot = dict(zip(BOOT, boot))
        self.seq = self.r32(MB_ADDR + OFF["seq"])
        return {"loaded_bytes": loaded, "entry": entry, "estack": estack,
                "pre_takeover": pre, "boot": self.boot}

    def _read_block(self, addr, nwords, retries=3):
        for k in range(retries):
            try:
                return self.t.read_memory_block32(addr, nwords)
            except (TransferFaultError, TransferError):
                if k == retries - 1:
                    return [self.t.read32(addr + 4 * i) for i in range(nwords)]  # word-by-word fallback
                time.sleep(0.02)

    def info(self):
        return dict(zip(INFO, self._read_block(MB_ADDR + OFF["info"], len(INFO))))

    def measure_clock(self, seconds=2.0):
        c0, t0 = self.r32(DWT_CYCCNT), time.perf_counter()
        time.sleep(seconds)
        c1, t1 = self.r32(DWT_CYCCNT), time.perf_counter()
        d = (c1 - c0) & 0xFFFFFFFF
        return d / (t1 - t0)

    def run(self, cmd: str, params: dict, timeout=30.0):
        p = [0] * 16
        for k, v in params.items():
            p[k] = v & 0xFFFFFFFF
        self.t.write_memory_block32(MB_ADDR + OFF["param"], p)
        self.w32(MB_ADDR + OFF["cmd"], CMD[cmd])
        self.seq = (self.seq + 1) & 0xFFFFFFFF
        self.w32(MB_ADDR + OFF["seq"], self.seq)
        t0 = time.time()
        while True:
            st = self.r32(MB_ADDR + OFF["state"])
            if st in (2, 3, 4) and self.r32(MB_ADDR + OFF["ack"]) == self.seq:
                break
            if time.time() - t0 > timeout:
                raise TimeoutError(f"{cmd} timed out (state={STATE.get(st)})")
            time.sleep(0.002)
        if st != 2:
            info = self.info()
            return {"status": STATE[st], "err": self.r32(MB_ADDR + OFF["err"]),
                    "cfsr": info["CFSR_LAST"], "bfar": info["BFAR_LAST"], "fault_pc": info["FAULT_PC"]}
        n = self.r32(MB_ADDR + OFF["n_results"])
        res = self._read_block(MB_ADDR + OFF["results"], n) if n else []
        return {"status": "DONE", "cycles": res, "sink": self.r32(MB_ADDR + OFF["sink"])}


def summarize(cycles):
    if not cycles:
        return {}
    c = sorted(cycles)
    return {"n": len(c), "min": c[0], "median": statistics.median(c), "max": c[-1],
            "mean": statistics.fmean(c), "sd": statistics.pstdev(c) if len(c) > 1 else 0.0}


def decode_info(info):
    d2 = info["XSPI2_DCR2"]; ccr = info["XSPI2_CCR"]; cr = info["XSPI2_CR"]
    cc_i, cc_d = info["CCSIDR_I"], info["CCSIDR_D"]
    def ccsidr(v):   # Armv8-M CCSIDR: LineSize[2:0] (log2 words - 2), Assoc[12:3], NumSets[27:13]
        line = 1 << ((v & 7) + 4); ways = ((v >> 3) & 0x3FF) + 1; sets = ((v >> 13) & 0x7FFF) + 1
        return {"line_bytes": line, "ways": ways, "sets": sets, "size_kb": line * ways * sets / 1024}
    presc = d2 & 0xFF
    return {
        "cpu_hz_hal": info["CPU_HZ_HAL"], "sys_hz_hal": info["SYS_HZ_HAL"],
        "xspi2_kernel_hz_hal": info["XSPI2_KER_HZ_HAL"], "xspi1_kernel_hz_hal": info["XSPI1_KER_HZ_HAL"],
        "xspi2": {"enabled": bool(cr & 1), "fmode": (cr >> 28) & 3, "memory_mapped": ((cr >> 28) & 3) == 3,
                  "prescaler": presc, "if_clock_hz": (info["XSPI2_KER_HZ_HAL"] / (presc + 1)) if info["XSPI2_KER_HZ_HAL"] else None,
                  "dmode_lines": {0: 0, 1: 1, 2: 2, 3: 4, 4: 8}.get((ccr >> 24) & 7), "ddtr": bool(ccr & (1 << 27)),
                  "dqse": bool(ccr & (1 << 29)), "mtyp": (info["XSPI2_DCR1"] >> 24) & 7},
        "icache": ccsidr(cc_i), "dcache": ccsidr(cc_d),
        "ccr_at_entry": {"raw": info["CCR_AT_ENTRY"], "icache_on": bool(info["CCR_AT_ENTRY"] & (1 << 17)),
                         "dcache_on": bool(info["CCR_AT_ENTRY"] & (1 << 16))},
        "mpu_ctrl_at_entry": info["MPU_CTRL_AT_ENTRY"], "mpu_regions": (info["MPU_TYPE"] >> 8) & 0xFF,
        "ltdc_was_on": info["LTDC_WAS_ON"], "fpscr": info["FPSCR"], "build_id": info["BUILD_ID"],
        "cpuid": info["CPUID"],
    }


def cpu_probe(b: Board):
    """Readability as seen by the core itself (the debugger's AXI-AP view can differ:
    RISAF/RIF filtering applies to debug accesses, and the core runs in the Secure state)."""
    pts = {"xspi2_flash": XSPI2, "xspi2_flash_1mb": XSPI2 + 0x100000, "xspi1_psram": XSPI1,
           "flexram": 0x34000000, "sram2": SRAM2, "sram4": SRAM4, "dtcm": 0x30000000, "itcm": 0x10000000}
    res = {}
    for k, a in pts.items():
        r = b.run("PEEK", {1: a}, timeout=5)
        res[k] = {"ok": r["status"] == "DONE", "value": (r.get("cycles") or [None])[0],
                  "cfsr": r.get("cfsr"), "bfar": r.get("bfar")}
    return res


def plan_all(b: Board, iters: int, readable: dict, cpu_view: dict):
    out = []
    flash_ok = cpu_view.get("xspi2_flash_1mb", {}).get("ok", False)
    scratch = SRAM4 if readable.get("SRAM4_S 0x34270000") else SRAM1
    wsram = SRAM2
    # 0. timing overhead
    for cm, mode in CACHE_MODES.items():
        r = b.run("NOP", {0: iters, 3: mode})
        out.append({"exp": "nop", "cache": cm, **r, "stats": summarize(r.get("cycles", []))})
    # 1. fill SRAM2 with 512 KB of int8 data (also serves as the FP32 pool for read-bw)
    b.run("FILL", {1: wsram, 2: 512 * 1024, 4: 0xC0FFEE, 5: 0})
    # 2. read bandwidth: SRAM2 vs XSPI2 flash
    srcs = {"sram2": wsram}
    if flash_ok:
        srcs["xspi2_flash"] = XSPI2 + 0x100000
    for name, src in srcs.items():
        for size in (16 * 1024, 64 * 1024, 128 * 1024, 256 * 1024):
            for width, wcode in RW.items():
                for cm, mode in CACHE_MODES.items():
                    r = b.run("READ_BW", {0: iters, 1: src, 2: size, 3: mode, 4: wcode}, timeout=120)
                    st = summarize(r.get("cycles", []))
                    out.append({"exp": "read_bw", "src": name, "bytes": size, "width": width, "cache": cm,
                                "status": r["status"], "stats": st,
                                "bytes_per_cycle_median": (size / st["median"]) if st else None,
                                "err": r.get("err"), "cycles": r.get("cycles")})
    # 3. INT8 MLP (CMSIS-NN, MVE) and FP32 MLP, weights in SRAM2 vs flash
    for mname, dims in MODELS.items():
        wbytes_s8 = macs(dims); wbytes_f32 = 4 * macs(dims)
        b.run("FILL", {1: wsram, 2: wbytes_s8, 4: 0xBEEF, 5: 0})
        placements = {"sram2": wsram}
        if flash_ok:
            placements["xspi2_flash"] = XSPI2 + 0x100000
        for pname, waddr in placements.items():
            for cm, mode in CACHE_MODES.items():
                r = b.run("MLP_S8", {0: iters, 1: waddr, 2: scratch, 3: mode,
                                     5: dims[0], 6: dims[1], 7: dims[2], 8: dims[3], 9: dims[4]}, timeout=180)
                out.append({"exp": "mlp_s8", "model": mname, "dims": dims, "macs": macs(dims),
                            "weight_bytes": wbytes_s8, "weights": pname, "cache": cm,
                            "status": r["status"], "stats": summarize(r.get("cycles", [])),
                            "err": r.get("err"), "cycles": r.get("cycles")})
        # FP32: fill with finite floats when in SRAM (flash content is arbitrary; FZ/DN set)
        b.run("FILL", {1: wsram, 2: wbytes_f32, 4: 0xF10A7, 5: 1})
        for pname, waddr in placements.items():
            for cm, mode in CACHE_MODES.items():
                r = b.run("MLP_FP32", {0: iters, 1: waddr, 2: scratch, 3: mode,
                                       5: dims[0], 6: dims[1], 7: dims[2], 8: dims[3], 9: dims[4]}, timeout=300)
                out.append({"exp": "mlp_fp32", "model": mname, "dims": dims, "macs": macs(dims),
                            "weight_bytes": wbytes_f32, "weights": pname, "cache": cm,
                            "status": r["status"], "stats": summarize(r.get("cycles", [])),
                            "err": r.get("err"), "cycles": r.get("cycles")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default=str(ROOT / "firmware/n6/build/n6_bench.elf"))
    ap.add_argument("--uid", default=None, help="ST-LINK serial")
    ap.add_argument("--freq", type=int, default=8_000_000)
    ap.add_argument("--iters", type=int, default=100)
    ap.add_argument("--probe", action="store_true", help="only probe memory readability")
    ap.add_argument("--plan", default="all")
    ap.add_argument("--out", default=None)
    ap.add_argument("--wait", type=float, default=0.0, help="retry connecting for this many seconds (board replug)")
    a = ap.parse_args()

    b = Board(a.uid, a.freq, wait_s=a.wait)
    try:
        if a.probe:
            print("readable:", json.dumps(b.probe(), indent=1))
            return
        # Take over FIRST: the OOB firmware's low-power timer is the enemy; every second counts.
        tk = b.takeover(Path(a.elf))
        print(f"firmware up: loaded {tk['loaded_bytes']} B, entry {tk['entry']:#x}", flush=True)
        bt = tk["boot"]
        print(f"watchdog snapshot: IWDG_SR={bt['IWDG_SR']:#x} IWDG_OK={bt['IWDG_OK']} "
              f"WWDG_present={bt['WWDG_PRESENT']} WWDG_CR={bt['WWDG_CR']:#x} WWDG_CFR={bt['WWDG_CFR']:#x} "
              f"RCC_APB1ENR1={bt['RCC_APB1ENR1']:#x} setup_fault={bt['SETUP_FAULT']:#x}", flush=True)
        readable = b.probe()
        print("readable (debugger view, firmware running):", json.dumps(readable, indent=1))
        info_raw = b.info()
        info = decode_info(info_raw)
        clk = [b.measure_clock(2.0) for _ in range(3)]
        info["cpu_hz_measured"] = {"samples": clk, "mean": statistics.fmean(clk)}
        print(json.dumps(info, indent=1))
        cpu_view = cpu_probe(b)
        print("cpu view:", json.dumps(cpu_view, indent=1))
        results = plan_all(b, a.iters, readable, cpu_view) if a.plan == "all" else []
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        report = {"timestamp": datetime.now(timezone.utc).isoformat(), "git": git, "probe_uid": a.uid,
                  "elf": a.elf, "iters": a.iters, "readable_debugger": readable, "readable_cpu": cpu_view,
                  "takeover": tk,
                  "platform": info, "platform_raw": info_raw, "results": results}
        out = Path(a.out) if a.out else ROOT / "results" / f"n6_bench_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out.write_text(json.dumps(report, indent=1))
        print(f"wrote {out}")
    finally:
        b.close()


if __name__ == "__main__":
    main()
