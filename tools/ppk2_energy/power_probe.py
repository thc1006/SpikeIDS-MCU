"""One bounded Ampere-mode engineering power pulse, never firmware/energy acceptance.

USB nominal 5 V is an explicit assumption, not a VIN measurement. Software
cutoff/cleanup cannot protect against host failure, wiring faults or transients.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import struct
import sys
import termios
import time

from analyze import Decoder

PPK_SERIAL = "F4728E9B55E0"
ST_SERIAL = "004000183234510E37333934"
HEADLESS = Path("/home/thc1006/.local/opt/ppk2-headless")


def command(port, value, state, name):
    row = {"name": name, "hex": value.hex(), "at_monotonic": time.monotonic(),
           "write_completed": False}
    state.setdefault("commands", []).append(row)
    if port.write(value) != len(value):
        raise OSError("Incomplete " + name + " write")
    row["write_completed"] = True


def reference(probe):
    raw = bytes(probe.transfer([0xf7], readSize=8))
    if len(raw) != 8:
        raise ValueError("Incomplete target-reference reply")
    a0, a1 = struct.unpack("<II", raw)
    if not a0:
        raise ValueError("Invalid target-reference denominator")
    return {"at_monotonic": time.monotonic(), "raw_hex": raw.hex(),
            "estimated_v": 2 * a1 * 1.2 / a0, "is_vin_measurement": False}


def pulse(port, probe, raw_file, metadata, state, *, seconds=3.0):
    if metadata.get("mode") != "1":
        raise ValueError("Not verified Ampere mode; refusing ON")
    if not 0.1 <= seconds <= 3.0:
        raise ValueError("Pulse must be 0.1..3 seconds")
    decoder = Decoder(metadata, 5.0, "nordic-gui-4.4.1", "none")
    state.update(samples=0, minimum_uA=None, maximum_uA=None,
                 current_sum_uA=0.0, references=[], cleanup_errors=[])
    pending = b""
    previous = None
    last_data = time.monotonic()
    try:
        command(port, b"\x0c\x00", state, "initial_output_off")
        time.sleep(.15)
        state["references"].append({"phase": "before", **reference(probe)})
        if port.in_waiting:
            raise RuntimeError("Unexpected pending stream before START")
        command(port, b"\x06", state, "sampling_start")
        time.sleep(.05)  # separate USB protocol transactions
        started = time.monotonic()
        command(port, b"\x0c\x01", state, "output_on")
        next_reference = started + .3
        while time.monotonic() - started < seconds:
            chunk = port.read(4096)
            if chunk:
                last_data = time.monotonic()
                if raw_file.write(chunk) != len(chunk):
                    raise OSError("Short raw capture write")
                state["raw_bytes_written"] = state.get("raw_bytes_written", 0) + len(chunk)
                if state["raw_bytes_written"] > 2_000_000:
                    raise RuntimeError("Capture byte limit")
                joined = pending + chunk
                aligned = len(joined) // 4 * 4
                pending = joined[aligned:]
                for (word,) in struct.iter_unpack("<I", joined[:aligned]):
                    adc, r, counter = word & 16383, (word >> 14) & 7, (word >> 18) & 63
                    if previous is not None and counter != (previous + 1) % 64:
                        raise RuntimeError("Sample counter discontinuity")
                    previous = counter
                    ua = decoder.current_ua(adc, r)
                    state["samples"] += 1
                    state["current_sum_uA"] += ua
                    state["minimum_uA"] = ua if state["minimum_uA"] is None else min(ua, state["minimum_uA"])
                    state["maximum_uA"] = ua if state["maximum_uA"] is None else max(ua, state["maximum_uA"])
                    # Deliberately below the 1 A measurement rating; host-side
                    # diagnostic stop only, NOT a hardware current limiter.
                    if adc == 16383 or ua > 700_000 or ua < -50_000:
                        raise RuntimeError("Current/ADC diagnostic stop threshold")
            if time.monotonic() - last_data > .5:
                raise TimeoutError("No recent PPK2 samples")
            if time.monotonic() >= next_reference:
                value = reference(probe)
                state["references"].append({"phase": "during", **value})
                if not 2.7 <= value["estimated_v"] <= 3.6:
                    raise RuntimeError("Target reference outside 2.7..3.6 V after startup")
                next_reference = time.monotonic() + .5
        state["pulse_loop_completed"] = True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        # OFF before STOP, and attempt both even if one fails. Never retry ON.
        for name, value in (("final_output_off", b"\x0c\x00"),
                            ("sampling_stop", b"\x07")):
            try:
                command(port, value, state, name)
                time.sleep(.05)
            except BaseException as exc:
                state["cleanup_errors"].append(f"{name}: {type(exc).__name__}: {exc}")
        state["unprocessed_trailing_bytes"] = len(pending)
    if pending:
        raise RuntimeError("Partial final sample; raw retained, probe not accepted")


def interrupted(signum, frame):
    # One signal starts cleanup; leave a second signal available to the caller.
    signal.setitimer(signal.ITIMER_REAL, 0)
    raise InterruptedError(f"Signal {signum}; stopping power probe")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-three-second-power-test", action="store_true", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=False, exist_ok=False)
    sys.path.insert(0, str(HEADLESS))
    import serial
    from ppk2_info import devices, query_metadata
    from pyocd.probe.stlink.usb import STLinkUSBInterface
    state = {"schema": "ppk2-n6-power-probe-v1", "utc": datetime.now(timezone.utc).isoformat(),
             "nominal_correction_voltage_v": 5.0, "voltage_basis": "unmeasured_USB_nominal_assumption",
             "research_measurement_accepted": False, "firmware_changed": False,
             "wiring_basis": "user_reported_JP2_series_connection", "commands": [],
             "power_probe_completed": False,
             "input_voltage_measured": False, "electrical_output_off_verified": False,
             "pulse_target_seconds": 3.0, "whole_pulse_watchdog_seconds": 6.0,
             "software_cleanup_is_not_hardware_protection": True}
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(sig, interrupted)
    error = None
    probe = None
    try:
        matched = [p for p in devices() if p["serial"] == PPK_SERIAL]
        probes = [p for p in STLinkUSBInterface.get_all_connected_devices() if p.serial_number == ST_SERIAL]
        if len(matched) != 1 or len(probes) != 1:
            raise RuntimeError("Exact PPK2 and ST-LINK pair not uniquely present")
        state.update(ppk=matched[0], stlink_serial=ST_SERIAL)
        probe = probes[0]
        probe.open()  # low-level USB only, no debug-mode entry/reset/flash
        with serial.Serial(matched[0]["port"], baudrate=115200, timeout=.02,
                           write_timeout=.3, exclusive=True) as port:
            fcntl.ioctl(port.fileno(), termios.TIOCEXCL)
            metadata_raw, metadata = query_metadata(port)
            state.update(raw_metadata=metadata_raw.decode("ascii"), metadata_fields=metadata)
            tail = port.read(256)
            if any(b not in b"\r\n\t " for b in tail):
                raise RuntimeError("Unexpected metadata tail")
            with (args.output / "samples.u32le").open("xb") as raw:
                signal.setitimer(signal.ITIMER_REAL, 6.0)
                try:
                    pulse(port, probe, raw, metadata, state)
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
            time.sleep(.2)
            state["references"].append({"phase": "after", **reference(probe)})
            if state["cleanup_errors"]:
                raise RuntimeError("Power cleanup write failure; physical state uncertain")
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
        state["source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        with (args.output / "report.json").open("x") as out:
            json.dump(state, out, indent=2, allow_nan=False)
            out.write("\n")
        print(json.dumps(state, indent=2, allow_nan=False))
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
