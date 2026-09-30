# Additive build v2: bounded ESP policy correction

Source [build_candidate_v2.py](build_candidate_v2.py) SHA
`4af738272558c3b38143f2780f58a57655ce9697573d576340c5f25353b26071`;
[test source](test_build_candidate_v2.py) SHA
`24bec4abf81a3d806187479ea6a72fe0f15c4299910ef254ddb531afc752e2d1`.
Actual `42d2eb / 0`: **22 tests passed**, 0.052 s. Source/test SHA bookend in
`c3efd7` matches. Tests read the preserved ESP02 ELF and compile commands;
counterexamples mutate only in-memory metadata/ELF copies, not old artifacts.

Changes are explicit in the copied v2, not an import-time override of the old
builder. Original `build_candidate.py` remains SHA `786df9cc…`; RA01 and failed
ESP01/02 records remain unchanged.

- Allow **exactly** the three observed global undefined names, each tied to an
  anchored SDK CMake `-u` statement from the correct component. Reject any extra,
  missing, weak-typed or actually referenced name. Inspect all `.a` files under
  the fresh build, including bootloader archives, and retain the tool output.
- Reject all nonempty ELF relocation sections. Additional RTC PT_LOAD must be
  exactly address/physical `0x600fffe8`, file size zero, memory size 24, flags RW;
  its one `.rtc_reserved` section must be NOBITS, WA, 24 B, alignment 8. This is
  not permission for arbitrary RTC payloads or executable sections.
- Split complete compile commands with `shlex`, bind the three exact source
  paths, require real C11/O2/no-fast-math/no-contract/excess-precision tokens,
  and reject conflicting later settings, response files and substring fakes.
- Require both primary and secondary consoles NONE and retain PSRAM-disabled,
  candidate-4-MB configuration checks. Existing strict numerical C is unchanged.

Parent independently read the narrow v2 delta before fresh ESP03 was launched.
This corrects the offline checker; it does not rerun model inference, certify
SDK-wide dependency closure, resolve physical module identity, or establish
hardware/target arithmetic acceptance.
