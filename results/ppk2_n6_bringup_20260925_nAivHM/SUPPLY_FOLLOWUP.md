# Supplemental official supply clarification

No physical supply measurement or output-ON command was added by this followup.

Root searched the specific possibility that 5.0 V was merely a nominal
designation and USB-range 5.2–5.4 V might be supported. Nordic support explicitly
does not recommend that higher voltage and does not guarantee measurements
outside the maximum. It is not valid to silently substitute the separate
micro-USB 5.5 V allowance for the measurement VIN rating.

- https://devzone.nordicsemi.com/f/nordic-q-a/93492/power-profiler-kit-ii-source-voltage-vcc-higher-than-recommended
- https://devzone.nordicsemi.com/f/nordic-q-a/112035/what-is-the-maximum-admissible-voltage-in-ppk2-ampere-meter-mode

No output-ON command does **not** establish that VIN is electrically isolated:
the reported USB→JP2-1→VIN connection can already apply external voltage to the
measurement input. Thus the power hold in this phase must not be interpreted as
an all-pins-deenergized safety certificate. Physical verification of that input
is still needed before declaring the present connection within specification.

Nordic also states that this is not a bidirectional current meter. Retaining
small negative corrected arithmetic values is necessary to avoid bias from
clipping offset/noise or idle subtraction; it is **not** a claim that PPK2 can
measure a real reverse-current workload.

- https://devzone.nordicsemi.com/f/nordic-q-a/128687/ppk2-works-in-desktop-app-but-reports-no-data-using-python-api-on-linux/569012

No workaround using unknown voltage, larger-current USB sources, improvised
series components, or assumed current limits was implemented.
