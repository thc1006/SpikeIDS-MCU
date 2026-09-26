"""Read exactly three ST-LINK voltage replies; no target debug or PPK command.

The USB interface is claimed/opened, and pending endpoint input is flushed by
pyOCD's low-level USB class. The higher-level STLink.open/close (enter_idle)
and all target connection methods are deliberately not called. Voltage is a
probe indication, not calibrated VIN, power-path identity or boot evidence.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys
import time

SERIAL = '004000183234510E37333934'


def voltage_reply(raw):
    if type(raw) is not bytes or len(raw) != 8:
        raise ValueError('Expected exact eight-byte probe voltage reply')
    a0, a1 = struct.unpack('<2I', raw)
    return {'raw_hex': raw.hex(), 'adc_reference': a0, 'adc_target': a1,
            'reported_volts': 2 * a1 * 1.2 / a0 if a0 else None}


def main():
    if len(sys.argv) != 1 or sys.flags.optimize:
        raise ValueError('No arguments or optimized execution')
    from pyocd.probe.stlink import usb, constants, stlink
    files = [Path(__file__).resolve()] + [Path(m.__file__).resolve() for m in (usb, constants, stlink)]
    pins = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    if constants.Commands.GET_TARGET_VOLTAGE != 0xf7:
        raise ValueError('Unexpected installed command constant')
    devices = [d for d in usb.STLinkUSBInterface.get_all_connected_devices() if d.serial_number == SERIAL]
    if len(devices) != 1:
        raise ValueError('Expected unique exact ST-LINK serial')
    device = devices[0]
    result = {'serial': SERIAL, 'source_sha256': pins, 'samples': [], 'close_completed': False,
              'open_completed': False, 'close_attempted': False,
              'short_reply_raw_retained_by_library': False,
              'target_debug_entered': False, 'target_reset_requested': False,
              'ppk_accessed': False, 'target_power_switched': False,
              'calibrated_voltage_claimed': False, 'model_executed': False}
    try:
        device.open()
        result['open_completed'] = True
        for _ in range(3):
            before = time.monotonic_ns()
            raw = bytes(device.transfer([0xf7], readSize=8, timeout=1000))
            sample = voltage_reply(raw)
            sample.update(monotonic_before_ns=before, monotonic_after_ns=time.monotonic_ns())
            result['samples'].append(sample)
    except BaseException as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        try:
            if device.is_open:
                result['close_attempted'] = True
                device.close()
                result['close_completed'] = True
        except BaseException as exc:
            result['close_error'] = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            try:
                result['source_bookend_passed'] = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
                                                      for p, h in pins.items())
            except BaseException as exc:
                result['source_bookend_passed'] = False
                result['source_bookend_error'] = type(exc).__name__ + ': ' + str(exc)
            print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
    if not result['source_bookend_passed']:
        raise RuntimeError('Source changed during voltage observation')


if __name__ == '__main__':
    main()
