# SM06 bounded full1024 validation preflight

Actual same-row2656 diagnostic `9c8472 -> ba9bdf / exit0` completed all7
stops and final response,clean CPU halt/owned-breakpoint removal. Independent
saved NumPy AND scalar integer review `fddc22 / 0`:
second dense256/256,third128/128,final5/5 raw NPU accumulators exact against
original W times actual captured unsigned inputs. All3 captured inputs equal
original ONNX activation quantization. Final5 logits bitwise equal. Not whole-
model acceptance. No power/latency claim,not all-CPU substitute outputs.

11 saved-data adversarial tests `944087 / 0` reject corrupted inputs,each
NPU raw region,final output,tag,PC,FPmode,cleanup and false acceptance.
Fixed gate2e148b3cb5a67f17ef58a73a1875d75d9b5c9d99b054c2b6c3f14354cc4255b6
binds all retained diagnostic artifacts plus independent checker SHA and
review result. New full launcher rechecks/recomputes gate before hardware
and again before successful publication. Gate permits next validation only.

Full launcher is separate from already-used INIT-only source. Private frozen
SM02 controller/transport/FP/runtime/evaluator are unchanged,SM06 tag/build
fixed. It never uses init-only collector override. All original1024rows and
5logits remain mandatory;atol1e-6/rtol1e-5 unchanged,0argmax discrepancies.
Default is still offline,no USB. Updated54host tests pass before execution.

Next authorized action:one new output `results/n6_sram_validation_20260926_08`,
fresh NPU platform init/reset before payload,180s outer interrupt/10s kill
fallback. No retries/skips,Flash/unlock,PPK or physical supply manipulation.
Failure remains failure. A parity pass is not frequency/NPU timing/energy
qualification and will not update paper energy figures.
