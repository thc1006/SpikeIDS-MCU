# SM06 explicit SM05 routing repair — not accepted

SM05 actual first diagnostic failed waiting for third dense hardware output.
The prototype wrongly routed STRENG5 from CONVACC1 although that layer uses
CONVACC2/3. This was OUR adapter assumption,not a vendor/model defect. Old
structural tests duplicated that wrong assumed ID and failed to expose it.
All old code/build/failed evidence remains unchanged,not silently repaired.

Only two generated routing records (epoch31 start/end) change source1->3,
derived from actual original ARITH-input topology. New firmware tagSM06.
All original weights,bias,quantization,input/clock/security/runtime/schedule/
signed24 arithmetic remain byte-identical. New topology tests must reject
SM05,detect all wrong producer IDs and check that configured/enabled producer
matches the original path. Keep7HW+35SW;NPU dots,CPU requantization.

SM05 first actual signed24 NPU layer returned256/256 exact integer dot
products (range-438393..509420) before the next-layer timeout. That limited
result is not whole-model acceptance. CPU halted and all owned HWbreakpoints
removed. Platform initialization resets NPU before any new RAM payload.
No PPK/Flash/unlock or numerical-policy change is authorized by this file.
