# Separate second pulse: same cutoff, improved stopped-stream retention

The first pulse remains an interrupted diagnostic. The user requested actual
tests and investigation of the1A claim. This second diagnostic is another
brief energization, not recovery of the first pulse's lost buffer and not
authorization to label the board normal or take research energy results.

Root reviewed the new wrapper `tools/ppk2_energy/power_probe_capture_v2.py`:
- It imports the unchanged original `pulse` function and requires sourceSHA
  c74d945e81dce5f5647d3795e4f70bdcf0ebae3ccf27cca37daf6d3a00ef4e8f.
- All original current/ADC/no-data/reference/3second target/6second watchdog
  conditions remain unchanged. No extra ON, raised threshold or filter change.
- After original pulse OFF and STOP writes, bounded read-only drain records
  bytes still buffered. It verifies both writes completed, uses0.5s/1MiB caps,
  adjusts serial read timeout to remaining time and restores it afterward.
- Original pulse/cleanup failures remain nonzero even if drain/f7 succeeds.
- Post-OFF ST-LINKf7 is attempted on the failure path as well; no debug entry,
  reset, firmware, mode or voltage command is added. No electrical-off claim.
- Full raw alignment is checked; partial bytes retained and reported invalid.

Independent reviewer agreed this is a bounded acquisition-improvement design,
not a safety certificate. Focused mocked drain tests and final source check
are required before execution. Actual USB nominal voltage remains unmeasured,
and the same externally powered Ampere arrangement/user-reported wiring is
retained. No automatic retry loop is configured.
