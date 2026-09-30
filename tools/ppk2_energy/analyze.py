"""Offline PPK2 decoding and GPIO-window integration; never opens hardware.

Formula/filter reference: Nordic pc-nrfconnect-ppk v4.4.1, serialDevice.ts.
This is an engineering analyzer, NOT an instrument-calibration certificate or
a board/model acceptance gate. Metadata VDD is never used as measured voltage.
"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import struct
import sys


DT_S = 10e-6  # Nordic nominal sampling interval, not host receipt timestamps.
POLICIES = ("metadata-exact", "nordic-gui-4.4.1")
FILTERS = ("none", "nordic-4.4.1")
DEFAULTS = {"R": [1031.64, 101.65, 10.15, .94, .043],
            "GS": [1.] * 5, "GI": [1.] * 5, "O": [0.] * 5,
            "S": [0.] * 5, "I": [0.] * 5, "UG": [1.] * 5}


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{name}: expected finite numeric value")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name}: nonfinite value")
    return number


def integer(value, name, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name}: invalid integer")
    return value


def voltage(value):
    result = finite(value, "voltage")
    if not .8 <= result <= 5.0:
        raise ValueError("voltage must be 0.8..5.0 V; this does not verify physical VIN")
    return result


def coefficients(metadata, policy):
    if policy not in POLICIES or not isinstance(metadata, dict):
        raise ValueError("Invalid coefficient policy or metadata")
    folded = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or key.upper() in folded:
            raise ValueError("Duplicate/case-colliding metadata key")
        folded[key.upper()] = value
    effective, substitutions = {}, {}
    for group, defaults in DEFAULTS.items():
        effective[group] = []
        for index, fallback in enumerate(defaults):
            key = f"{group}{index}"
            if key not in folded:
                raise ValueError(f"Missing device coefficient {key}; refusing generic fallback")
            raw = finite(folded[key], key)
            # Mirror the GUI's JavaScript `value || default` ONLY when explicit.
            val = fallback if policy == "nordic-gui-4.4.1" and raw == 0 else raw
            if val != raw:
                substitutions[key] = {"raw": raw, "effective": val}
            if group in ("R", "UG") and val <= 0:
                raise ValueError(f"{key} must be positive")
            effective[group].append(val)
    return effective, substitutions


class Decoder:
    def __init__(self, metadata, correction_voltage_v, policy, spike_filter):
        self.coef, self.substitutions = coefficients(metadata, policy)
        self.volts = voltage(correction_voltage_v)
        if spike_filter not in FILTERS:
            raise ValueError("Invalid filter")
        self.filter = spike_filter
        self.avg = self.avg4 = self.previous_range = None
        self.remaining = self.consecutive = 0

    def current_ua(self, adc14, range_code):
        integer(adc14, "ADC", maximum=16383)
        integer(range_code, "range", maximum=4)
        c, r = self.coef, range_code
        scaled = (adc14 * 4 - c["O"][r]) * ((1.8 / 163840) / c["R"][r])
        amps = c["UG"][r] * (scaled * (c["GS"][r] * scaled + c["GI"][r])
                              + (c["S"][r] * self.volts + c["I"][r]))
        if not math.isfinite(amps):
            raise ValueError("Nonfinite corrected current")
        if self.filter == "nordic-4.4.1":
            old, old4 = self.avg, self.avg4
            self.avg = amps if old is None else .18 * amps + (1.0 - .18) * old
            self.avg4 = amps if old4 is None else .06 * amps + (1.0 - .06) * old4
            if self.previous_range is None:
                self.previous_range = r
            if self.previous_range != r or self.remaining > 0:
                if self.previous_range != r:
                    self.consecutive, self.remaining = 0, 3
                else:
                    self.consecutive += 1
                if r == 4:
                    if self.consecutive < 2:
                        self.avg, self.avg4 = old, old4
                    amps = self.avg4
                else:
                    amps = self.avg
                self.remaining -= 1
            self.previous_range = r
        answer = amps * 1e6
        if not math.isfinite(answer):
            raise ValueError("Nonfinite output current")
        return answer  # Negative samples are deliberately NOT clamped to zero.


class Sum:
    """Compensated running sum with bounded memory."""
    def __init__(self):
        self.total = self.correction = 0.

    def add(self, value):
        adjusted = value - self.correction
        new = self.total + adjusted
        if not math.isfinite(new):
            raise ValueError("Nonfinite accumulation")
        self.correction = (new - self.total) - adjusted
        self.total = new


def analyze_stream(raw, decoder, *, channel, baseline, min_samples,
                   inferences, expected_windows, energy_voltage_v, writer=None):
    integer(channel, "GPIO channel", maximum=7)
    integer(min_samples, "minimum window samples", minimum=1)
    integer(inferences, "inferences per HIGH window", minimum=1)
    integer(expected_windows, "expected complete windows", minimum=1, maximum=100000)
    energy_v = None if energy_voltage_v is None else voltage(energy_voltage_v)
    if baseline is not None:
        if len(baseline) != 2:
            raise ValueError("Baseline requires [start, stop)")
        integer(baseline[0], "baseline start")
        integer(baseline[1], "baseline stop", minimum=baseline[0] + 1)
    digest, all_sum, base_sum = hashlib.sha256(), Sum(), Sum()
    sample_count = base_count = saturated = transitions = 0
    lo = hi = None
    previous_counter = previous_range = previous_high = None
    ranges = [0] * 5
    windows, problems = [], []
    start = None
    window_sum = Sum()
    start_truncated = False
    remainder = b""
    if writer:
        writer.writerow(["sample_index", "nominal_time_s", "counter_mod64", "range",
                         "adc14", "digital_u8", "corrected_current_uA"])
    while chunk := raw.read(4 * 65536):
        digest.update(chunk)
        joined = remainder + chunk
        aligned = len(joined) // 4 * 4
        remainder = joined[aligned:]
        for (word,) in struct.iter_unpack("<I", joined[:aligned]):
            adc, r = word & 16383, (word >> 14) & 7
            counter, bits = (word >> 18) & 63, (word >> 24) & 255
            if previous_counter is not None and counter != (previous_counter + 1) % 64:
                raise ValueError(f"Counter discontinuity at sample {sample_count}; no interpolation")
            ua = decoder.current_ua(adc, r)
            high = bool(bits & (1 << channel))
            ranges[r] += 1
            saturated += adc == 16383
            transitions += previous_range is not None and r != previous_range
            previous_counter, previous_range = counter, r
            all_sum.add(ua)
            lo = ua if lo is None else min(lo, ua)
            hi = ua if hi is None else max(hi, ua)
            if baseline is not None and baseline[0] <= sample_count < baseline[1]:
                if high:
                    raise ValueError("Declared idle baseline overlaps GPIO HIGH")
                base_sum.add(ua)
                base_count += 1
            if high and not previous_high:
                start, window_sum = sample_count, Sum()
                start_truncated = previous_high is None
            if high:
                window_sum.add(ua)
            elif previous_high:
                count = sample_count - start
                row = {"start_sample": start, "stop_sample_exclusive": sample_count,
                       "samples": count, "duration_s": count * DT_S,
                       "current_sum_uA_samples": window_sum.total,
                       "start_edge_observed": not start_truncated,
                       "minimum_samples_met": count >= min_samples}
                windows.append(row)
                if len(windows) > 100000:
                    raise ValueError("Too many windows for bounded analysis")
                if start_truncated or count < min_samples:
                    problems.append(f"Incomplete or undersampled HIGH window at {start}")
            if writer:
                writer.writerow([sample_count, sample_count * DT_S, counter, r, adc, bits, ua])
            previous_high = high
            sample_count += 1
    if remainder:
        raise ValueError("Partial raw frame: refusing time/energy reconstruction")
    if not sample_count:
        raise ValueError("Empty capture")
    if previous_high:
        problems.append("Capture ends HIGH: trailing window is truncated and not integrated")
    if len(windows) != expected_windows:
        problems.append(f"Expected {expected_windows} complete windows, found {len(windows)}")
    if saturated:
        problems.append(f"ADC upper-rail samples: {saturated}; possible clipping")
    if baseline is None:
        problems.append("No explicit idle baseline; incremental energy unavailable")
    elif base_count != baseline[1] - baseline[0]:
        raise ValueError("Baseline interval extends beyond capture")
    base_ua = base_sum.total / base_count if base_count else None
    for row in windows:
        if not row["start_edge_observed"] or not row["minimum_samples_met"]:
            row["energy_estimate_uJ"] = None
            continue
        charge = row["current_sum_uA_samples"] * DT_S
        net_charge = None if base_ua is None else charge - base_ua * row["duration_s"]
        gross = None if energy_v is None else charge * energy_v
        net = None if net_charge is None or energy_v is None else net_charge * energy_v
        if any(not math.isfinite(v) for v in (charge, net_charge, gross, net) if v is not None):
            raise ValueError("Nonfinite charge/energy")
        row.update(energy_estimate_uJ=gross, incremental_energy_estimate_uJ=net,
                   charge_estimate_uC=charge, incremental_charge_estimate_uC=net_charge,
                   declared_inferences=inferences,
                   gross_uJ_per_declared_inference=None if gross is None else gross / inferences,
                   incremental_uJ_per_declared_inference=None if net is None else net / inferences)
    return {"samples": sample_count, "raw_sha256": digest.hexdigest(),
            "nominal_duration_s": sample_count * DT_S,
            "range_histogram": ranges, "range_transitions": transitions,
            "upper_rail_adc_samples": saturated, "minimum_current_uA": lo,
            "maximum_current_uA": hi, "mean_current_uA": all_sum.total / sample_count,
            "baseline_interval": baseline, "baseline_samples": base_count,
            "baseline_mean_current_uA": base_ua, "windows": windows,
            "window_checks_passed": not problems, "problems": problems}


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key {key}")
        result[key] = value
    return result


def metadata_text(text):
    if not isinstance(text, str):
        raise ValueError("Missing original metadata text")
    lines = text.strip().splitlines()
    if not lines or lines[-1].strip() != "END":
        raise ValueError("Incomplete original metadata")
    fields = []
    for line in lines[:-1]:
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise ValueError("Malformed original metadata")
        fields.append((key.strip(), value.strip()))
    return strict_pairs(fields)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True, help="Existing transport capture directory")
    parser.add_argument("--capture-report-sha256", required=True,
                        help="Previously recorded whole-file SHA256; not an authenticity attestation")
    parser.add_argument("--output", type=Path, required=True, help="NEW output directory; never reused")
    parser.add_argument("--correction-voltage-v", type=float, required=True,
                        help="Explicit current-calibration voltage; NEVER auto-read metadata VDD")
    parser.add_argument("--correction-voltage-basis", required=True,
                        choices=("nominal-assumption", "external-measurement", "gui-setting-replay", "synthetic"))
    parser.add_argument("--energy-voltage-v", type=float,
                        help="Optional explicit constant voltage; omit to leave energy null")
    parser.add_argument("--energy-voltage-basis", choices=("nominal-assumption", "external-measurement", "synthetic"))
    parser.add_argument("--coefficient-policy", choices=POLICIES, required=True)
    parser.add_argument("--spike-filter", choices=FILTERS, required=True)
    parser.add_argument("--channel", type=int, required=True)
    parser.add_argument("--baseline", type=int, nargs=2, metavar=("START", "STOP"))
    parser.add_argument("--min-window-samples", type=int, default=100,
                        help="Engineering minimum, not an accuracy certificate; default 1 ms")
    parser.add_argument("--inferences-per-window", type=int, required=True)
    parser.add_argument("--expected-windows", type=int, required=True)
    parser.add_argument("--save-current-csv", action="store_true")
    args = parser.parse_args(argv)
    voltage(args.correction_voltage_v)
    if (args.energy_voltage_v is None) != (args.energy_voltage_basis is None):
        parser.error("Energy voltage and its basis must be supplied together")
    if args.energy_voltage_v is not None:
        voltage(args.energy_voltage_v)
    if (len(args.capture_report_sha256) != 64
            or any(c not in "0123456789abcdef" for c in args.capture_report_sha256)):
        parser.error("Expected lowercase 64-character report SHA256")
    capture_path, output_path = args.capture.resolve(), args.output.resolve()
    if (output_path == capture_path or output_path.is_relative_to(capture_path)
            or capture_path.is_relative_to(output_path)):
        parser.error("Output must not overlap the original capture directory")
    args.output.mkdir(parents=True, exist_ok=False)
    source_bytes = Path(__file__).read_bytes()
    result = {"schema": "ppk2-offline-engineering-v1", "research_measurement_accepted": False,
              "physical_voltage_verified_by_this_tool": False,
              "logic_reference_and_wiring_verified": False,
              "calibration_accuracy_verified": False, "sample_clock_accuracy_verified": False,
              "board_model_and_inference_count_verified": False,
              "analysis_completed": False, "analysis_checks_passed": False,
              "parameters": {key: str(val) if isinstance(val, Path) else val for key, val in vars(args).items()},
              "analyzer_sha256": hashlib.sha256(source_bytes).hexdigest(),
              "conversion_reference": {
                  "url": "https://github.com/NordicSemiconductor/pc-nrfconnect-ppk/blob/4cbb4c41c420ddb8125638fffc6d72f6b21c5aaa/src/device/serialDevice.ts",
                  "version": "4.4.1", "source_sha256": "37bda3ca2fb927ec67aa0d981773ec09371a2a799138397f2da6b362bd1ae926",
                  "scope": "Arithmetic and optional spike filter, not full GUI initialization or hardware writes"},
              "limitations": ["Only observed modulo-64 counter gaps detected; whole 64-sample losses can be invisible",
                              "GPIO sampled at nominal 10 us; analog bandwidth/filter/boundary uncertainty not certified",
                              "Constant supplied voltage is not a synchronous voltage measurement",
                              "Low GPIO is not proof of matched idle workload; baseline choice is externally declared",
                              "Per-inference divisor is declared, not checked against firmware execution",
                              "Hashes identify read-time bytes against a caller-provided pin, not immutable archival storage"]}
    code = 1
    try:
        report_bytes = (args.capture / "report.json").read_bytes()
        if hashlib.sha256(report_bytes).hexdigest() != args.capture_report_sha256:
            raise ValueError("Capture report differs from caller-supplied SHA256 pin")
        captured = json.loads(report_bytes, object_pairs_hook=strict_pairs)
        if captured.get("schema") != "ppk2-transport-diagnostic-v1" or captured.get("transport_check_passed") is not True:
            raise ValueError("Expected a completed, passing transport diagnostic capture")
        fields = captured["metadata_fields"]
        if fields != metadata_text(captured.get("raw_metadata")):
            raise ValueError("Parsed metadata differs from original device response")
        decoder = Decoder(fields, args.correction_voltage_v, args.coefficient_policy, args.spike_filter)
        result.update(capture_report_sha256=hashlib.sha256(report_bytes).hexdigest(),
                      device=captured["device"], original_metadata=fields,
                      effective_coefficients=decoder.coef, zero_value_substitutions=decoder.substitutions,
                      metadata_vdd_used_as_voltage=False)
        csv_file = None
        try:
            if args.save_current_csv:
                csv_file = (args.output / "current.csv").open("x", newline="")
            with (args.capture / "samples.u32le").open("rb") as raw:
                analysis = analyze_stream(raw, decoder, channel=args.channel, baseline=args.baseline,
                                          min_samples=args.min_window_samples, inferences=args.inferences_per_window,
                                          expected_windows=args.expected_windows, energy_voltage_v=args.energy_voltage_v,
                                          writer=csv.writer(csv_file) if csv_file else None)
        finally:
            if csv_file:
                csv_file.close()
        result["analysis"] = analysis
        expected = captured["analysis"]
        if (analysis["raw_sha256"] != expected["sha256"] or analysis["samples"] != expected["samples"]
                or analysis["samples"] * 4 != expected["raw_bytes"]):
            raise ValueError("Raw payload identity/count differs from original capture report")
        if (args.capture / "report.json").read_bytes() != report_bytes:
            raise ValueError("Capture report changed during analysis")
        if Path(__file__).read_bytes() != source_bytes:
            raise ValueError("Analyzer source changed during analysis")
        result.update(analysis_completed=True, analysis_checks_passed=analysis["window_checks_passed"])
        code = 0 if result["analysis_checks_passed"] else 2
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    with (args.output / "analysis.json").open("x") as out:
        json.dump(result, out, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({"report": str(args.output / "analysis.json"), "exit_code": code,
                      "analysis_completed": result["analysis_completed"],
                      "analysis_checks_passed": result["analysis_checks_passed"],
                      "research_measurement_accepted": False, "error": result.get("error")}))
    return code


if __name__ == "__main__":
    sys.exit(main())
