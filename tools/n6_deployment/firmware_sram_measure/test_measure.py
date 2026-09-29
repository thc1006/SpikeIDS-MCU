"""Static equivalence checks: SM07M main() == SM06 main() + documented hooks."""
from pathlib import Path
import re
import sys
import unittest

HERE = Path(__file__).resolve().parent
BASE_MAIN = HERE.parent / 'firmware_sram/main.c'
sys.path.insert(0, str(HERE.parent / 'host_sram_measure'))


def body(path, start='int main(void)'):
    text = Path(path).read_text()
    text = text[text.index(start):]
    lines = [l.strip() for l in text.splitlines()]
    return [l for l in lines if l]


class EquivalenceTest(unittest.TestCase):
    def test_main_is_sm06_main_plus_hooks(self):
        base = [l.replace('stai_nsl_qcfs_seed0_init(network)', 'initialize_runtime_then_model(network)')
                for l in body(BASE_MAIN)]
        mine = body(HERE / 'main.c')
        hooks = {'measure_publish();', 'uint32_t measure_seen = 0;',
                 'measure_poll(network, in[0], out[0], &measure_seen);'}
        self.assertEqual([l for l in mine if l not in hooks], base)
        self.assertEqual(sum(l in hooks for l in mine), 3)

    def test_qcompat_macro_is_what_main_calls(self):
        qcompat = (HERE.parent / 'firmware_sram_qcompat/main.c').read_text()
        self.assertIn('#define stai_nsl_qcfs_seed0_init initialize_runtime_then_model', qcompat)
        chain = [HERE.parent / p for p in ('firmware_sram_accum24_route/main.c',
                                            'firmware_sram_accum24/main.c',
                                            'firmware_sram_firstfloat/main.c')]
        for f, nxt in zip(chain, ('../firmware_sram_accum24/main.c', '../firmware_sram_firstfloat/main.c',
                                  '../firmware_sram_qcompat/main.c')):
            self.assertIn(f'#include "{nxt}"', f.read_text())

    def test_batch_row_matches_infer_statements(self):
        src = (HERE / 'main.c').read_text()
        fn = src[src.index('static void infer_row'):src.index('static int rows_finite')]
        for stmt in ('stai_nsl_qcfs_seed0_run(network, STAI_MODE_SYNC)', 'checked(4, rc);',
                     'checked(5, stai_nsl_qcfs_seed0_get_error(network));', 'memcpy(dst, out0, 20);',
                     'memcpy(in0, &g_rows_in[row * 41], 164);'):
            self.assertIn(stmt, fn)

    def test_host_offsets_match_header(self):
        import measure
        h = (HERE / 'measure.h').read_text()
        self.assertIn('_Static_assert(offsetof(s7_measure_t, n_rows) == 0x30', h)
        self.assertIn('_Static_assert(offsetof(s7_measure_t, window) == 0x70', h)
        fields = re.search(r'uint32_t n_rows, bench_reps, overhead_reps, cycles;.*?'
                           r'uint32_t idle_cycles, pulse_cycles, pulse_count, max_windows;', h, re.S)
        self.assertIsNotNone(fields)
        self.assertEqual(measure.PARAM_FIELDS, ('n_rows', 'bench_reps', 'overhead_reps', 'cycles',
                                                'idle_cycles', 'pulse_cycles', 'pulse_count'))
        self.assertIn('#define S7_MAGIC UINT32_C(0x4D374D53)', h)
        self.assertEqual(measure.S7_MAGIC, 0x4D374D53)
        self.assertIn('S6_DEPLOYMENT_TAG UINT32_C(0x534d3037)', (HERE / 'mailbox.h').read_text())
        self.assertEqual(measure.TAG, 0x534D3037)


if __name__ == '__main__':
    unittest.main()
