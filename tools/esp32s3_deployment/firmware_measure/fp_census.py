"""Subnormal census of the frozen portable-QDQ computation on all 1024 rows.

Why: portable_qdq.c's pq_environment() gate requires gradual underflow
(FLT_MIN*0.5 > 0). Whether the ESP32-S3 (Xtensa LX7) FPU keeps or flushes
subnormals is not stated in any document we could obtain (QEMU's Xtensa FPU
model applies no flush-to-zero; Cadence's ISA summary was not retrievable).
If the silicon flushes, the gate fails closed at boot. This census shows
whether a flushing FPU could change any result on the validation rows: it
instruments every add32/mul32/div32 and the QCFS floorf of an unmodified copy
of the pinned portable_qdq.c and counts subnormal operands and results.

Output: JSON with op counts, subnormal counts and the bitwise parity of the
instrumented run against the QDQ reference (must remain 0 mismatches).
usage: .venv/bin/python fp_census.py --output <fresh json path>
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PQ = REPO / 'tools/board_deployment/portable_qdq'
MODEL_C = REPO / 'results/portable_qdq_native_20260925_01/model_sources/model.c'
PINS = {PQ / 'portable_qdq.c': None, MODEL_C: 'bba723cc7b031815c2aaf848f6893eb87dd91cb05f5580f93df611be489bb1e9'}
FLAGS = ['-std=gnu11', '-O2', '-fno-fast-math', '-ffp-contract=off', '-fexcess-precision=standard']

CHK = '''#include <math.h>
unsigned long long g_ops = 0, g_sub_in = 0, g_sub_out = 0, g_zero_out = 0;
static void chk(float a, float b, float x) {
    g_ops++;
    if (fpclassify(a) == FP_SUBNORMAL || fpclassify(b) == FP_SUBNORMAL) g_sub_in++;
    if (fpclassify(x) == FP_SUBNORMAL) g_sub_out++;
    if (x == 0.0f) g_zero_out++;
}
'''
SUBS = [
    ('static float add32(float a,float b) { volatile float x=a+b; return x; }',
     CHK + 'static float add32(float a,float b) { volatile float x=a+b; chk(a,b,x); return x; }'),
    ('static float mul32(float a,float b) { volatile float x=a*b; return x; }',
     'static float mul32(float a,float b) { volatile float x=a*b; chk(a,b,x); return x; }'),
    ('static float div32(float a,float b) { volatile float x=a/b; return x; }',
     'static float div32(float a,float b) { volatile float x=a/b; chk(a,b,x); return x; }'),
    ('    x=floorf(x);', '    { float y=floorf(x); chk(x,x,y); x=y; }'),
]
MAIN = r'''#include "portable_qdq.h"
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
extern unsigned long long g_ops, g_sub_in, g_sub_out, g_zero_out;
extern const uint32_t rm_inputs[1024 * 41];
extern const uint32_t rm_expected[1024 * 5];
int main(void) {
    unsigned mism = 0, badrc = 0; unsigned long long sub_rows = 0;
    for (int r = 0; r < 1024; ++r) {
        float in[41], out[5];
        memcpy(in, &rm_inputs[r * 41], 164);
        for (int k = 0; k < 41; ++k) if (fpclassify(in[k]) == FP_SUBNORMAL) sub_rows++;
        if (pq_infer(&spikeids_qdq_model, in, 41, out, 5)) badrc++;
        for (int k = 0; k < 5; ++k) { uint32_t w; memcpy(&w, &out[k], 4); if (w != rm_expected[r * 5 + k]) mism++; }
    }
    printf("{\"rows\": 1024, \"rc_fail\": %u, \"mismatched_words\": %u, \"fp_ops\": %llu, "
           "\"subnormal_operands\": %llu, \"subnormal_results\": %llu, \"exact_zero_results\": %llu, "
           "\"subnormal_input_features\": %llu}\n", badrc, mism, g_ops, g_sub_in, g_sub_out, g_zero_out, sub_rows);
    return 0;
}
'''


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args(argv)
    if os.path.lexists(a.output):
        raise SystemExit('refusing to overwrite --output')
    for p, want in PINS.items():
        if want and sha(p) != want:
            raise SystemExit(f'pin mismatch {p}')
    import importlib.util
    spec = importlib.util.spec_from_file_location('rm01_build', REPO / 'tools/ra4e1_deployment/firmware_measure/build.py')
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    text, vec = b.vectors_c(b.BUNDLE / 'validation_vectors.npz')
    src = (PQ / 'portable_qdq.c').read_text()
    for old, new in SUBS:
        if src.count(old) != 1:
            raise SystemExit(f'instrumentation anchor not found exactly once: {old[:50]!r}')
        src = src.replace(old, new)
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'pq_instr.c').write_text(src)
        (t / 'main.c').write_text(MAIN)
        (t / 'vec.c').write_text(text.replace('#include "rm01.h"', '#include <stdint.h>', 1))
        exe = t / 'census'
        subprocess.run(['cc', *FLAGS, '-I', str(PQ), str(t / 'pq_instr.c'), str(t / 'main.c'), str(t / 'vec.c'),
                        str(MODEL_C), '-lm', '-o', str(exe)], check=True)
        res = json.loads(subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout)
    res.update(instrumented=['add32', 'mul32', 'div32', 'QCFS floorf'],
               not_instrumented='int64->float conversions of INT8/INT32 codes (cannot yield subnormals) '
                                'and pq_quantize floorf of |x/scale| >= 0 (checked via div32/add32)',
               host_compiler=subprocess.run(['cc', '--version'], capture_output=True, text=True).stdout.splitlines()[0],
               flags=FLAGS, sources_sha256={str(PQ / 'portable_qdq.c'): sha(PQ / 'portable_qdq.c'),
                                            str(MODEL_C): sha(MODEL_C), 'fp_census.py': sha(Path(__file__))},
               vectors=vec)
    a.output.write_text(json.dumps(res, indent=1) + '\n')
    print(json.dumps({k: res[k] for k in ('rows', 'mismatched_words', 'fp_ops', 'subnormal_operands',
                                          'subnormal_results', 'subnormal_input_features')}))
    return 0 if res['mismatched_words'] == 0 and res['rc_fail'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
