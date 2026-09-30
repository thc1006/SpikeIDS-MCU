# SM05 accumulator-preservation candidate — NOT DEPLOYED OR ACCEPTED

Derived only from original ONNX22dc7979... and original generated C8b7a8703...
and SM04 source. No checkpoint change, no new training, no fitted constants.
Current files are an offline candidate,not authority to run hardware or power.

SM04 run05 still fails297/5120 output values on81rows. First failed row2656
trace shows second NPU dense differs by1 on2channels,one crosses a QCFS step.
First layer and first QCFS are exactly correct. Strict tolerance stays fixed.

Hypothesis:retain signed24 NPU dot products instead of intermediate signed16
right-shift and approximate affine requantization. The last Conv pipe's
output becomes3bytes,shift0,rounding disabled,saturation retained; input,
weights,first accumulation pipe,clocks/security remain unchanged. Remove
the associated ARITH node and route final Conv directly to the same output
stream engine. Write atactivation+8192 (max768+64B prefetch inside16KiB pool).
Then a separate CPU SW epoch applies original FP32 scales,bias,and nearest-
even quantization to the old output slot. NPU—not CPU—does all three dots.

Full-domain mathematical bound per output:255*sum(abs(original signed8
weights))<2^23. Input zeros are all-128 and weight zeros all0,so upstream
unsigned offset streams are the intended exact integer input. This bound
does not prove hardware packing,routing or accumulators are correct.

`prepare.py` derives fields only when original values match exact expectations;
emits source JSON to stdout and never edits originals/accesses USB. Source
comments may still describe original intermediate names/ranges; executable
descriptors—not those inherited comments—define candidate layout. Need
independent field-level diff review,compiled C controls,ARM build and actual
raw-NPU-vs-integer-dot checks before any full validation or acceptance.

Do not call this pure-NPU inference. First dense+QCFS+requantization use CPU.
All power/latency and downstream research claims remain unaccepted.
