# Fresh LD3 report after USB2 observation 01

After being asked specifically about LD3 following the USB2-port short test,
the user answered `紅色常亮`, then reiterated `紅色長亮`. These are confirmations
of the same post-fifth-capture condition, not two separate new experiments.
The observation is user-reported, not photographed or synchronized to raw
samples. It supersedes the earlier pending-LED status; the original acquisition
report, exit receipt and review remain historical and unchanged.

## Evidence and bounded conclusion

- Fifth acquisition: `usb2_fixed_am_observation_01`, external `3a3986 / 0`.
- Report SHA-256: `63c604f007c01f7a2f535d6046e42b03d32173a49bf6cdf8e26e11c544205f06`.
- Raw SHA-256: `f3a8c4656fcd92c9ac0a0c6ee9d783ca92af95d8c7c583035d03c5825f9eda97`.
- Original external receipt SHA-256:
  `879d4a29d427b2b881410d8e5e5630b137f9d56c4b897a63fa6dac091d8927b1`.
- Rechecked these hashes in `f33564 / 0` before recording this follow-up.
- Prior saved review: nonzero ranges for nominal 1.02 ms, near-zero final
  two seconds, no early software OFF. New red LD3 supports protection shutdown
  on the ST-LINK supply path, rather than acceptance of sustained board power.

ST's [TN1235 section 7](https://www.st.com.cn/resource/en/technical_note/tn1235-overview-of-stlink-derivatives-stmicroelectronics.pdf)
defines steady-red PWR_STATUS for STLINK-V3EC as overcurrent detected and
automatic target-power switch-off. It says to investigate the cause or use
a more capable USB port. [UM3300 section 7.4.2](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf)
describes the CN6/JP2 1–2 path and its 550 mA/1.66 A/3.2 A current-limit options.
This does NOT mean our actual trip current has been measured or that a
particular limit is electronically read back by these tests.

Review explicitly rejects the following unwarranted conclusions:

- red LD3 alone proves a 1 A load, exact trip time or board damage;
- all USB2 sockets are unsuitable, or USB3 would certainly fix it;
- the USB reconnect after cleanup caused the earlier near-zero interval;
- exit 0 is model/energy acceptance;
- the new report proves a unique initiating cause (inrush, wiring, source,
  load or another fault have not been isolated);
- software may disable protection, repeat the same ON indefinitely, or
  silently switch JP2 selection against the user's retained-wiring constraint.

## Actions and next boundary

No sixth ON, serial session, debug/flash operation or firmware change was
performed for this follow-up. A read-only process check (`ed1c36 / 0`) found
no matching acquisition/programmer process apart from the check itself.
No background job is waiting to turn the output back on. This is not physical
OFF verification; the fifth collector's final OFF/STOP writes remain the
last executed meter commands in this sequence.

Respect the user's unchanged-pin constraint: do not move JP2 or leads and
do not represent the proposed CN18/JP2 3–4 supply as already connected.
Request removing both STM32 USB sources for investigation while leaving
the PPK2 USBs and JP2/Dupont leads untouched. This is a requested next physical
step, NOT recorded as completed. Do not simply reconnect and repeat.

Retaining JP2 1–2 retains CN6 as the selected upstream supply. A different
host supply would need suitable power advertisement **and** data for the
onboard debugger; USB socket generation alone is not qualification. A charger
at CN6 also removes the present PC-to-ST-LINK data link, so it is not a complete
automatic deployment solution. A charger at CN18 with JP2 selection unchanged
is not established as replacing the measured supply. Any stronger-source
proposal must still respect the PPK2 limits; no replacement is accepted here.

Next hardware phase requires investigating the existing path or agreeing an
appropriate supply-path change, not declaring a pure-software repair proven.
Original trained model, SRAM builds, numerical tolerance and negative results
are retained. No formal three-board power result is produced by this follow-up.
