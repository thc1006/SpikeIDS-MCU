"""Single-session SM02 flow; frozen transports, stage and numerical evaluator."""
import struct
from runtime_protocol import decode, mailbox_type, runtime_live


def run_connected(core, firmware, platform, sink, *, nonce, modules):
    o, p, s, v = (modules[n] for n in ('orchestrate','protocol','stage_protocol','validation'))
    load = modules['ram_loader'].load_and_verify
    events, mail_events, completed = [], [], []
    try:
        core.halt()
        sink.json('initial_registers.json',core.entry_snapshot())
        sink.json('platform_load.json',load(core,platform['segments'],
            lambda a,b:sink.raw(f'backup_stage_{a:08x}.bin',b),events))
        core.start_loaded_image(platform['entry'],platform['msp'])
        o.wait_header(core,s.ADDRESS,s.MAGIC,s.SIZE,2)
        initialized=s.challenge(core.read,core.write,nonce)
        sink.raw('platform_mailbox.bin',initialized['raw'])
        core.halt()
        sink.json('platform_live_before_payload.json',s.live_register_check(core.read,initialized))
        sink.json('model_load.json',load(core,firmware['segments'],
            lambda a,b:sink.raw(f'backup_model_{a:08x}.bin',b),events))
        sink.json('platform_live_after_payload.json',s.live_register_check(core.read,initialized))
        core.start_loaded_image(firmware['entry'],firmware['msp'])
        o.wait_header(core,p.ADDRESS,p.MAGIC,512,1)
        core.halt()
        mailbox=mailbox_type(p)(core.read,core.write,events=mail_events)
        raw,w=mailbox.snapshot()
        if w[3:7]!=(1,0,0,0): raise ValueError('Require fresh SM02 WAIT_PLATFORM')
        sink.raw('adapter_wait_platform.bin',raw)
        snap=core.entry_snapshot()
        lo,code=firmware['segments'][0]
        if not lo<=snap['pc']<lo+len(code): raise ValueError('PC outside new executable')
        sink.json('floating_environment.json',core.floating_environment())
        sink.json('platform_live_before_ack.json',s.live_register_check(core.read,initialized))
        token=struct.pack('<I',p.ACK)
        n=core.write(p.ADDRESS+16,token)
        if type(n) is not int or n!=4 or core.read(p.ADDRESS+16,4)!=token:
            raise ValueError('Platform ACK write/readback failed')
        core.resume_from_halt()
        o.wait_header(core,p.ADDRESS,p.MAGIC,512,3)
        core.halt()
        raw,w=mailbox.snapshot()
        if w[3]!=3 or w[5:7]!=(0,0): raise ValueError('Require fresh READY before inference')
        sink.raw('adapter_ready.bin',raw)
        runtime_live(core,lambda observation:sink.json('runtime_live_before_inference.json',observation))
        sink.json('floating_environment_after_init.json',core.floating_environment())
        sink.json('platform_live_after_init.json',s.live_register_check(core.read,initialized))
        core.resume_from_halt()
        def retain(record):
            sink.json(f'row_{len(completed):04d}.json',record)
            completed.append(record['row_id'])
        parity=v.collect(mailbox,firmware['rows'],retain)
        sink.json('PARITY.json',parity)
        if not parity['full_logit_parity_passed']:
            raise ValueError('Full-logit parity failed; original tolerance retained')
        core.halt()
        sink.json('floating_environment_after_validation.json',core.floating_environment())
        runtime_live(core,lambda observation:sink.json('runtime_live_after_validation.json',observation))
        sink.json('platform_live_after_validation.json',s.live_register_check(core.read,initialized))
        return dict(full_logit_parity_passed=True,completed_rows=len(completed),
            actual_process_exit=None,nominal_cpu_npu_hz=initialized['nominal_cpu_npu_hz'],
            frequency_measured=False,npu_execution_independently_verified=False,
            latency_validated=False,energy_measured=False,research_measurement_accepted=False)
    finally:
        error=None
        try: core.halt()
        except BaseException as exc: error=type(exc).__name__+': '+str(exc)
        sink.json('load_events.json',events)
        sink.json('mailbox_events.json',mail_events)
        sink.json('completion_state.json',dict(completed_row_ids=completed,halt_error=error,
            power_was_not_switched=True,npu_quiescence_verified=False))
        if error is not None: raise RuntimeError('Cleanup halt failed: '+error)
        # Preserve the last raw state even for header/init errors before collect.
        sink.raw('final_mailbox.bin',core.read(p.ADDRESS,512))
