"""Same fixed pulse policy as power_probe.py, retain STOP-buffered bytes on error.

No higher thresholds, no additional ON, no retries, no firmware writes.
Nominal5V is not a measured voltage; this is not research acceptance.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import sys
import termios
import time

import power_probe as original

ORIGINAL_SHA = "c74d945e81dce5f5647d3795e4f70bdcf0ebae3ccf27cca37daf6d3a00ef4e8f"


def drain_stopped(port, sink, state, *, clock=time.monotonic):
    """Only reads already-stopped stream. No hardware control writes at all."""
    completed = {r["name"] for r in state.get("commands", []) if r["write_completed"]}
    if not {"final_output_off", "sampling_stop"}.issubset(completed):
        raise RuntimeError("Cannot drain without completed OFF and STOP writes")
    start = clock()
    total = 0
    previous_timeout = port.timeout
    state["post_stop_drain"] = {"bytes": 0, "empty_read_observed": False}
    try:
        while (remaining := .5 - (clock() - start)) > 0:
            port.timeout = min(.02, remaining)
            chunk = port.read(16384)
            if not chunk:
                state["post_stop_drain"]["empty_read_observed"] = True
                state["post_stop_drain"]["elapsed_seconds"] = clock() - start
                return
            if total + len(chunk) > 1_048_576:
                raise RuntimeError("Stopped-stream drain exceeds byte cap")
            if sink.write(chunk) != len(chunk):
                raise OSError("Short stopped-stream raw write")
            total += len(chunk)
            state["post_stop_drain"]["bytes"] = total
        raise TimeoutError("Stopped stream still supplying data at drain deadline")
    finally:
        port.timeout = previous_timeout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-same-policy-power-test", action="store_true", required=True)
    args = parser.parse_args()
    original_path = Path(original.__file__)
    if hashlib.sha256(original_path.read_bytes()).hexdigest() != ORIGINAL_SHA:
        raise ValueError("Held pulse policy changed; no device access")
    args.output.mkdir(parents=False, exist_ok=False)
    sys.path.insert(0, str(original.HEADLESS))
    import serial
    from ppk2_info import devices, query_metadata
    from pyocd.probe.stlink.usb import STLinkUSBInterface
    state = {"schema": "ppk2-n6-power-probe-capture-v2", "utc": datetime.now(timezone.utc).isoformat(),
             "original_pulse_source_sha256": ORIGINAL_SHA,
             "nominal_correction_voltage_v": 5.0, "voltage_basis": "unmeasured_USB_nominal_assumption",
             "research_measurement_accepted": False, "firmware_changed": False,
             "wiring_basis": "user_reported_JP2_series_connection", "commands": [],
             "power_probe_completed": False, "input_voltage_measured": False,
             "electrical_output_off_verified": False, "pulse_target_seconds": 3.0,
             "whole_pulse_watchdog_seconds": 6.0,
             "software_cleanup_is_not_hardware_protection": True}
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(sig, original.interrupted)
    error = None
    probe = None
    try:
        matched = [p for p in devices() if p["serial"] == original.PPK_SERIAL]
        probes = [p for p in STLinkUSBInterface.get_all_connected_devices()
                  if p.serial_number == original.ST_SERIAL]
        if len(matched) != 1 or len(probes) != 1:
            raise RuntimeError("Exact PPK2 and ST-LINK pair not uniquely present")
        state.update(ppk=matched[0], stlink_serial=original.ST_SERIAL)
        probe = probes[0]
        probe.open()
        with serial.Serial(matched[0]["port"], baudrate=115200, timeout=.02,
                           write_timeout=.3, exclusive=True) as port:
            fcntl.ioctl(port.fileno(), termios.TIOCEXCL)
            metadata_raw, metadata = query_metadata(port)
            state.update(raw_metadata=metadata_raw.decode("ascii"), metadata_fields=metadata)
            if any(b not in b"\r\n\t " for b in port.read(256)):
                raise RuntimeError("Unexpected metadata tail")
            with (args.output / "samples.u32le").open("xb") as raw:
                signal.setitimer(signal.ITIMER_REAL, 6.0)
                try:
                    original.pulse(port, probe, raw, metadata, state)
                except BaseException as exc:
                    error = exc
                    state["pulse_error"] = f"{type(exc).__name__}: {exc}"
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                try:
                    drain_stopped(port, raw, state)
                except BaseException as exc:
                    state["drain_error"] = f"{type(exc).__name__}: {exc}"
                    error = error or exc
            try:
                state.setdefault("references", []).append({"phase": "after",
                                                           **original.reference(probe)})
            except BaseException as exc:
                state["post_reference_error"] = str(exc)
                error = error or exc
            if state.get("cleanup_errors"):
                error = error or RuntimeError("Cleanup failed; electrical state uncertain")
            if error:
                raise error
            state["power_probe_completed"] = True
    except BaseException as exc:
        error = exc
        state["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if probe is not None and probe.is_open:
            try:
                probe.close()
            except BaseException as exc:
                state["probe_close_error"] = str(exc)
                error = error or exc
        path = args.output / "samples.u32le"
        if path.exists():
            with path.open("rb") as handle:
                state["raw_sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
            state["raw_size_bytes"] = path.stat().st_size
            state["raw_frame_aligned"] = state["raw_size_bytes"] % 4 == 0
            if not state["raw_frame_aligned"]:
                state["raw_error"] = "Partial final sample retained"
                error = error or RuntimeError(state["raw_error"])
        if error:
            state["power_probe_completed"] = False
        state["source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        with (args.output / "report.json").open("x") as out:
            json.dump(state, out, indent=2, allow_nan=False)
            out.write("\n")
        print(json.dumps(state, indent=2, allow_nan=False))
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
