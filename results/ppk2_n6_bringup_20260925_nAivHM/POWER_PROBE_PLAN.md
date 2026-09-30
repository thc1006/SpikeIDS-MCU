# Bounded power-probe decision (2026-09-25)

The user reconfirmed the two boards and leads are connected and explicitly
requested starting the test. Root rechecked both exact USB serials online and
no open owners with fuser. No source-mode or voltage-change operation is planned.

The earlier categorical requirement to obtain a multimeter before any initial
function test was overly restrictive: Nordic documents external USB as a DUT
source in Ampere mode. This does NOT establish actual VIN, waive the 0.8–5.0 V
input rating, or certify the user-reported physical wiring. The limited test
uses the reported nominal 5 V USB source as an explicit assumption and cannot
produce accepted power/energy research results.

Root inspected the installed low-level pyOCD STLinkUSBInterface, the existing
headless metadata reader, and official Nordic Power Profiler v4.4.1 constants,
abstractDevice and serialDevice commands. Only ST-LINK command f7 is planned;
no debug entry/reset/flash. PPK2 commands are metadata19, OFF0c00, START06,
ON0c01, OFF0c00, STOP07. No mode or regulator writes.

The new power_probe.py requires exact serials and Ampere mode=1; acquires an
exclusive serial port; sends initial OFF; targets a 3-second pulse; attempts
OFF then STOP independently in finally. A 6-second overall software alarm is
not a real-time guarantee or hardware protection. Error stops include missing
data, malformed/counter-discontinuous frames, ADC saturation, unfiltered
corrected current above700mA or below-50mA, and target-reference voltage outside
2.7–3.6V after startup. These are engineering checks, not a calibrated
overcurrent limiter. SIGKILL, host failure, USB loss, and physical transients
remain outside software guarantees. OFF writes are not electrical readback.

Raw bytes, metadata, attempted/completed commands, target-reference replies and
errors must remain saved even if the test fails. No retry of ON is automatic.
Legacy factory/application code may boot; its identity is not yet verified.
None of these samples should be called v5 model inference energy.

Official sources:
- https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/measure_current_ampere_meter.html
- https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_power_supply_specs.html
- https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_max_dut_current.html
- https://github.com/NordicSemiconductor/pc-nrfconnect-ppk/tree/v4.4.1/src

This note supersedes only the blanket pre-test multimeter hold in STATUS.md;
it does not promote any prior hardware/research acceptance flags.
