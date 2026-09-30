"""SM05 first diagnostic from fresh initialized READY, never parity acceptance.

No firmware recompilation, software breakpoint, Flash/PPK or tolerance change.
The initialized candidate is tested once; no formal result is accepted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import run as launcher
import runtime_protocol as rp

HERE=Path(__file__).resolve().parent
POINTS=(('before_quantize',0x34065010),('after_quantize',0x34064d74),
        ('after_hw_subtract',0x34064a9c),('after_dequantize',0x34065e08),
        ('after_first_dense',0x34065dc4))
ADDRESS=0x340f8000


def require(value,message):
    if not value:raise RuntimeError(message)


def observe(core,firmware,sink,decode,hw_type,expected_previous,*,clock=time.monotonic,sleep=time.sleep):
    owned=[];events=[]
    try:
        require(core.core.is_halted(),'Refuse unexpectedly running target')
        initial=core.entry_snapshot();sink.json('initial_registers.json',initial)
        require(initial['primask']==1,'IRQs unmasked')
        sink.json('floating_environment.json',core.floating_environment())
        prior=core.read(ADDRESS,512);sink.raw('previous_mailbox.bin',prior)
        w=decode(prior)
        require(prior==expected_previous and w[3]==3 and w[5]==w[6]==0,
                'Not exact initialized SM05 target')
        # Verify live executable and complete fixed weights reservation. Mutable
        # context/activations are intentionally not compared with their zero load.
        for index in (0,-2):
            address,payload=firmware['segments'][index]
            for offset in range(0,len(payload),4096):
                require(core.read(address+offset,min(4096,len(payload)-offset))==payload[offset:offset+4096],
                        'Live executable/weights differ from fixed new build')
        sink.json('live_payload_verified.json',dict(executable_and_weights_match=True))
        for _,address in POINTS:
            require(core.core.get_breakpoint_type(address) is None,'Existing breakpoint at diagnostic site')
        def install(address):
            events.append(dict(op='set_hw_breakpoint',address=address))
            owned.append(address)  # ambiguous installation must still get cleanup
            require(core.core.set_breakpoint(address,hw_type) is True,'Hardware breakpoint unavailable')
            core.core.flush()
            require(core.core.get_breakpoint_type(address)==hw_type,'No hardware breakpoint confirmation')
        def remove(address):
            core.core.remove_breakpoint(address);core.core.flush()
            require(core.core.get_breakpoint_type(address) is None,'Breakpoint removal not confirmed')
            owned.remove(address);events.append(dict(op='removed_hw_breakpoint',address=address))
        install(POINTS[0][1])
        row_id,inputs,reference=firmware['rows'][0]
        def write(address,payload):
            events.append(dict(op='mailbox_write',address=address,hex=payload.hex()))
            n=core.write(address,payload)
            require(type(n) is int and n==len(payload) and core.read(address,len(payload))==payload,'Ambiguous staging/commit; no retry')
        write(ADDRESS+28,struct.pack('<3I',1,row_id,41));write(ADDRESS+128,inputs)
        staged=core.read(ADDRESS,512);expected=bytearray(prior)
        expected[28:40]=struct.pack('<3I',1,row_id,41);expected[128:292]=inputs
        require(staged==bytes(expected),'Unexpected mailbox change before diagnostic commit')
        sink.raw('staged_mailbox.bin',staged)
        write(ADDRESS+20,struct.pack('<I',1))
        for index,(name,address) in enumerate(POINTS):
            if index:install(address)
            core.resume_from_halt();deadline=clock()+5
            while not core.core.is_halted():
                require(clock()<deadline,'Breakpoint deadline');sleep(0.001)
            require(clock()<deadline,'Breakpoint reply crossed deadline')
            context=core.entry_snapshot();sink.json(name+'_context.json',context)
            require(context['pc']==address and context['primask']==1,'Unexpected stop/IRQ state')
            raw=core.read(ADDRESS,512);sink.raw(name+'_mailbox.bin',raw)
            words=decode(raw)
            require(words[3]==4 and words[5:7]==(1,0) and words[8]==row_id
                    and raw[128:292]==inputs,'Diagnostic request changed')
            activation=b''.join(core.read(0x34240000+o,4096) for o in range(0,0x4000,4096))
            require(len(activation)==0x4000,'Short activation capture')
            sink.raw(name+'_activation.bin',activation)
            sink.json(name+'_fp.json',core.floating_environment())
            remove(address)
        core.resume_from_halt();deadline=clock()+5
        while True:
            raw=core.read(ADDRESS,512)
            require(clock()<deadline,'Diagnostic final completion deadline')
            w=decode(raw)
            require(w[3] not in (6,7),'Diagnostic firmware fault')
            if w[3]==5 and w[6]==1:break
            sleep(0.001)
        core.halt();final=core.read(ADDRESS,512);sink.raw('final_mailbox.bin',final)
        require(final==raw and w[5]==1 and w[19]==row_id and final[128:292]==inputs,'Wrong final diagnostic response')
        require(w[11:19]==(0,)*8 and w[10]==5,'Diagnostic API failure')
        return dict(diagnostic_completed=True,original_row_id=row_id,sequence=1,
            output_hex=final[320:340].hex(),reference_hex=reference.hex(),
            power_measured=False,latency_validated=False,research_measurement_accepted=False)
    finally:
        errors=[]
        try:core.halt()
        except BaseException as exc:errors.append('halt: '+str(exc))
        for address in list(owned):
            try:
                core.core.remove_breakpoint(address);core.core.flush()
                require(core.core.get_breakpoint_type(address) is None,'Removal not observed')
            except BaseException as exc:errors.append('breakpoint: '+str(exc))
        sink.json('events.json',events)
        sink.json('cleanup.json',dict(errors=errors,independent_npu_quiescence_verified=False))
        require(not errors,'Diagnostic cleanup failed')
