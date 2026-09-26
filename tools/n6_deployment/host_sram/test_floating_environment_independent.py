"""Read-only FP entry checks with literal register providers; no real pyOCD I/O."""
import pytest
from test_host_io_independent import backend, fake_target


def configured(fake_target):
    t = fake_target()
    t.registers['fpscr'] = 0
    t.ppb.update({0xE000ED88:0x00F00000, 0xE000EF34:0, 0xE000EF3C:0})
    return t


def test_default_mode_and_sticky_status_are_read_only(fake_target):
    t = configured(fake_target)
    t.registers['fpscr'] = 0xF800009F  # NZCV/QC plus cumulative exception flags, not mode bits.
    t.ppb[0xE000EF34] = 0xC0000000  # ASPEN/LSPEN may exist while no lazy context is active.
    result = backend.Core(t).floating_environment()
    assert result['fpscr'] == 0xF800009F and result['fpdscr'] == 0
    assert result['cpacr'] == 0x00F00000 and result['fpccr'] == 0xC0000000
    assert not t.writes and not t.resumed


@pytest.mark.parametrize('register', ['fpscr', 'fpdscr'])
@pytest.mark.parametrize('bit', [19, 22, 23, 24, 25, 26])
def test_each_arithmetic_control_is_rejected_without_repair(fake_target, register, bit):
    t = configured(fake_target)
    if register == 'fpscr':t.registers['fpscr'] = 1 << bit
    else:t.ppb[0xE000EF3C] = 1 << bit
    with pytest.raises(RuntimeError, match='Nondefault FP'):
        backend.Core(t).floating_environment()
    assert not t.writes and not t.resumed


def test_missing_access_or_active_lazy_context_never_changes_target(fake_target):
    for address, value in ((0xE000ED88,0x00700000), (0xE000EF34,1)):
        t = configured(fake_target); t.ppb[address] = value
        with pytest.raises(RuntimeError):backend.Core(t).floating_environment()
        assert not t.writes and not t.resumed


def test_context_gate_runs_before_floating_register_reads(fake_target):
    t = fake_target();t.halted = False  # No FP registers exist in this provider.
    with pytest.raises(RuntimeError, match='already be halted'):
        backend.Core(t).floating_environment()
    assert not t.writes and not t.resumed
