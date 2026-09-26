"""One ordered ESP wire session; importing this module never opens hardware.

Read/write callbacks receive the remaining exchange deadline in seconds. The
live wrapper opens only an explicit path AND unique USB serial/VID/PID match.
No request retry, flush/reset command, boot-mode toggle or physical SKU guess.
Ten seconds and 4096 noise bytes are host engineering bounds, not power limits.

pySerial Serial(None) permits DTR/RTS=False before open, but its documentation
warns OS/drivers may glitch these lines. POSIX open also clears its input buffer:
only bytes returned after open are retained, not a pre-open boot-log archive.
An outer process deadline is still required for blocking driver/open/close calls.
https://pyserial.readthedocs.io/en/latest/pyserial_api.html
"""
from contextlib import contextmanager
import math
from pathlib import Path
import struct
import time

from protocol import hello_query, decode_hello, decode_response, request, HELLO, require

ESP_VID = 0x303A
ESP_PID = 0x1001


def checked_requests(requests):
    """Validate all immutable inputs before any enumeration/open or wire write."""
    require(type(requests) is tuple and len(requests) == 1024, 'Exactly 1024 encoded requests required')
    row_ids = []
    for sequence, raw in enumerate(requests, 1):
        require(type(raw) is bytes and len(raw) == 232, 'Request must contain all 232 bytes')
        row_id = struct.unpack_from('<Q', raw, 16)[0]
        require(raw == request(sequence, row_id, raw[64:228]), 'Noncanonical request/model/CRC/order')
        row_ids.append(row_id)
    require(len(set(row_ids)) == 1024, 'Duplicate original row ID')
    return requests


class SerialExchange:
    """Callable transport for protocol.Session(exchange, board_id=2).

    retain(event) must durably preserve its JSON-safe record or raise. Requests
    are retained before writing; each returned read chunk precedes validation,
    so partial, late, bad-CRC and wrong-identity bytes remain available. No sink
    can guarantee evidence after its own storage failure. Any exchange failure
    permanently poisons this instance, including ambiguous partial writes.
    """
    def __init__(self, read, write, retain, requests, *, timeout_s=10.0,
                 max_hello_noise=4096, clock=time.monotonic):
        self._requests = checked_requests(requests)
        require(all(callable(x) for x in (read, write, retain, clock)), 'Callbacks required')
        require(type(timeout_s) in (int, float) and math.isfinite(timeout_s) and
                0 < timeout_s <= 30, 'Finite exchange timeout in (0,30] required')
        require(type(max_hello_noise) is int and 0 <= max_hello_noise <= 4096,
                'HELLO noise bound must be an integer in [0,4096]')
        self.read = read; self.write = write; self.retain = retain; self.clock = clock
        self.timeout_s = float(timeout_s); self.max_hello_noise = max_hello_noise
        self.poisoned = False; self.next = 0

    def __call__(self, raw, response_bytes):
        require(not self.poisoned, 'Poisoned transport; no retry')
        try:
            require(type(raw) is bytes and type(response_bytes) is int, 'Exact byte request/length required')
            require(self.next <= 1024, 'Original run is already complete')
            hello = self.next == 0
            expected = hello_query() if hello else self._requests[self.next - 1]
            require(raw == expected and response_bytes == (160 if hello else 88),
                    'Only HELLO then the fixed ordered requests are allowed')
            start = self.clock(); deadline = start + self.timeout_s
            def remaining():
                left = deadline - self.clock()
                if not math.isfinite(left) or left <= 0:raise TimeoutError('Exchange deadline exceeded')
                return min(self.timeout_s, left)  # binary64 subtraction must not enlarge the configured bound
            self.retain({'event':'request', 'exchange':self.next, 'raw_hex':raw.hex(),
                         'expected_response_bytes':response_bytes})
            count = self.write(raw, remaining())  # exactly one application write, never resend
            self.retain({'event':'write_return', 'exchange':self.next,
                         'bytes_written':count if type(count) is int else None,
                         'return_type':type(count).__name__})
            remaining()
            require(type(count) is int and count == len(raw), 'Ambiguous/partial write; no retry')
            read_calls = 0
            def take(count):
                nonlocal read_calls
                read_calls += 1
                require(read_calls <= 10000, 'Read call budget exceeded')
                chunk = self.read(count, remaining())
                require(type(chunk) is bytes, 'Reader must return bytes')
                self.retain({'event':'read', 'exchange':self.next, 'requested_bytes':count,
                             'raw_hex':chunk.hex()})
                remaining()
                require(0 < len(chunk) <= count, 'Empty or oversized read; no retry')
                return chunk
            def exact(count):
                result = bytearray()
                while len(result) < count:result.extend(take(count - len(result)))
                return bytes(result)
            noise = bytearray()
            if hello:
                prefix = bytearray(exact(4)); magic = struct.pack('<I', HELLO)
                while prefix != magic:
                    noise.append(prefix[0]); del prefix[0]
                    require(len(noise) <= self.max_hello_noise, 'HELLO prefix noise bound exceeded')
                    prefix.extend(take(1))
                reply = bytes(prefix) + exact(156)
            else:
                reply = exact(88)  # no resynchronization or discarded noise on inference replies
            self.retain({'event':'frame', 'exchange':self.next, 'response_hex':reply.hex(),
                         'hello_prefix_noise_hex':bytes(noise).hex()})
            if hello:decode_hello(reply, 2)
            else:decode_response(reply, self.next, struct.unpack_from('<Q', raw, 16)[0])
            remaining()
            self.next += 1
            return reply
        except BaseException:
            self.poisoned = True
            raise


def _selected(port, expected_serial, enumerate_ports):
    canonical = str(Path(port).resolve(strict=True))
    matches = [p for p in enumerate_ports() if p.vid == ESP_VID and p.pid == ESP_PID
               and p.serial_number == expected_serial]
    require(len(matches) == 1, 'Expected exactly one selected ESP USB serial/VID/PID')
    require(str(Path(matches[0].device).resolve(strict=True)) == canonical,
            'Explicit port does not match the selected USB identity')
    return {'requested_port':port, 'canonical_port':canonical, 'usb_serial':expected_serial,
            'vid':ESP_VID, 'pid':ESP_PID}


def _exclusive(serial_port):
    import fcntl
    import termios
    fcntl.ioctl(serial_port.fileno(), termios.TIOCEXCL)


@contextmanager
def open_exact_esp(port, expected_serial, requests, retain, *, timeout_s=10.0,
                   max_hello_noise=4096, serial_factory=None, enumerate_ports=None,
                   claim_exclusive=None, clock=time.monotonic):
    """Explicit Linux live entry; injection hooks exist only for offline tests.

    /dev/serial/by-id paths may resolve to the explicitly matched canonical tty.
    Device metadata is checked before and after opening; this is not a physical
    SKU/firmware attestation or proof of no already-open privileged owner.
    pySerial's advisory exclusive lock plus TIOCEXCL prevent ordinary competing
    opens, not privileged interference. Closing may also have OS line effects.
    """
    require(type(port) is str and port and '\0' not in port and Path(port).is_absolute(),
            'Explicit absolute serial path required')
    require(type(expected_serial) is str and expected_serial and
            expected_serial == expected_serial.strip() and '\0' not in expected_serial,
            'Explicit nonempty exact USB serial required')
    device = None
    def read(count, remaining):
        device.timeout = remaining
        return device.read(count)
    def write(raw, remaining):
        device.write_timeout = remaining
        return device.write(raw)
    transport = SerialExchange(read, write, retain, requests, timeout_s=timeout_s,
        max_hello_noise=max_hello_noise, clock=clock)  # all input validation BEFORE enumeration/import
    if serial_factory is None:
        import serial
        serial_factory = serial.Serial
    if enumerate_ports is None:
        from serial.tools.list_ports import comports
        enumerate_ports = comports
    if claim_exclusive is None:claim_exclusive = _exclusive
    selected = _selected(port, expected_serial, enumerate_ports)
    retain({'event':'selected_device_before_open', **selected, 'dtr_requested':False,
            'rts_requested':False, 'os_open_line_glitch_possible':True,
            'library_open_discards_preopen_input':True, 'physical_sku_verified':False})
    try:
        device = serial_factory(port=None, baudrate=115200, bytesize=8, parity='N', stopbits=1,
            timeout=timeout_s, write_timeout=timeout_s, xonxoff=False, rtscts=False,
            dsrdtr=False, exclusive=True)
        device.dtr = False; device.rts = False
        device.port = selected['canonical_port']
        device.open()
        claim_exclusive(device)
        require(_selected(port, expected_serial, enumerate_ports) == selected,
                'USB identity/path changed during open')
        retain({'event':'selected_device_after_open', **selected, 'tioc_exclusive_completed':True})
        yield transport
    finally:
        transport.poisoned = True
        if device is not None:
            device.close()  # always attempted, including open/config/identity or consumer failure
            retain({'event':'port_close_returned', 'electrical_state_verified':False})
