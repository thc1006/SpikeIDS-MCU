"""Finite whole-engine controls. Shared opaque fake target, real host functions.

No target API/USB is called; test_orchestrate.Core simulates mailbox and MMIO.
The actual loader, stage protocol, mailbox protocol, validation and orchestrator
are exercised. These tests are not independent hardware/init emulation.
"""
import struct

import pytest
from orchestrate import run_connected
from test_orchestrate import Core, Sink, payloads
from protocol import ADDRESS


def fixed_rows():
    firmware, platform = payloads()
    ref = struct.pack('<5f', 1, 2, 3, 4, 5)
    firmware['rows'] = tuple((100000 + i * 7,
        struct.pack('<41f', *(float(i + j) for j in range(41))), ref) for i in range(1024))
    return firmware, platform


def test_complete_1024_distinct_rows_and_all_five_outputs():
    firmware, platform = fixed_rows(); core = Core(); sink = Sink()
    answer = run_connected(core, firmware, platform, sink, nonce=0x12345678)
    assert answer['completed_rows'] == 1024 and answer['actual_process_exit'] is None
    assert not answer['npu_execution_independently_verified'] and not answer['energy_measured']
    for i, (row_id, inputs, reference) in enumerate(firmware['rows']):
        row = sink.files[f'row_{i:04d}.json']
        assert row['row_id'] == row_id and row['sequence'] == i + 1
        assert row['input_hex'] == inputs.hex() and row['output_hex'] == reference.hex()
    assert len([a for a, _ in core.writes if a == ADDRESS + 16]) == 1
    assert not core.running and sink.files['completion_state.json']['halt_error'] is None


def test_ack_readback_failure_no_inference_or_retry():
    class WrongAck(Core):
        ack_written = False
        def write(self, a, raw):
            result = super().write(a, raw)
            if a == ADDRESS + 16:self.ack_written = True
            return result
        def read(self, a, n):
            if self.ack_written and (a, n) == (ADDRESS + 16, 4):return bytes(4)
            return super().read(a, n)
    core = WrongAck(); sink = Sink()
    with pytest.raises(ValueError, match='acknowledgement write/readback'):
        run_connected(core, *fixed_rows(), sink, nonce=55)
    assert len([a for a, _ in core.writes if a == ADDRESS + 16]) == 1
    assert not any(a == ADDRESS + 20 for a, _ in core.writes)
    assert not core.running and sink.files['completion_state.json']['completed_row_ids'] == []


def test_last_row_fifth_logit_mismatch_preserves_complete_failure():
    class LastLogit(Core):
        def write(self, a, raw):
            result = super().write(a, raw)
            if a == ADDRESS + 20 and struct.unpack('<I', raw)[0] == 1024:
                self.put(ADDRESS + 336, struct.pack('<f', -5.0))
            return result
    core = LastLogit(); sink = Sink()
    with pytest.raises(ValueError, match='Full-logit parity failed'):
        run_connected(core, *fixed_rows(), sink, nonce=56)
    parity = sink.files['PARITY.json']
    assert not parity['full_logit_parity_passed'] and len(parity['failed_logit_values']) == 1
    assert (parity['failed_logit_values'][0]['index'], parity['failed_logit_values'][0]['column']) == (1023, 4)
    assert len([n for n in sink.files if n.startswith('row_')]) == 1024
    assert len(sink.files['completion_state.json']['completed_row_ids']) == 1024
    assert not core.running


def test_post_validation_mode_failure_cannot_return_success():
    class LateMode(Core):
        checks = 0
        def floating_environment(self):
            self.checks += 1
            if self.checks == 2:raise ValueError('post-validation inherited mode mismatch')
            return super().floating_environment()
    core = LateMode(); sink = Sink()
    with pytest.raises(ValueError, match='post-validation'):
        run_connected(core, *fixed_rows(), sink, nonce=57)
    assert sink.files['PARITY.json']['full_logit_parity_passed']
    assert len(sink.files['completion_state.json']['completed_row_ids']) == 1024
    assert not core.running


def test_cleanup_halt_failure_never_returns_a_successful_run():
    class FinalHalt(Core):
        def halt(self):
            if self.halts == 4:raise OSError('synthetic final halt unavailable')
            return super().halt()
    core = FinalHalt(); sink = Sink()
    with pytest.raises(RuntimeError, match='Cleanup halt failed'):
        run_connected(core, *fixed_rows(), sink, nonce=58)
    assert sink.files['PARITY.json']['full_logit_parity_passed']
    assert sink.files['completion_state.json']['halt_error'].startswith('OSError:')
    assert sink.files['completion_state.json']['npu_quiescence_verified'] is False
