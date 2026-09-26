"""Full fake-transport orchestration. No USB, compiler, ONNX or target code."""
import struct
import unittest
from orchestrate import run_connected,wait_header
from test_stage_protocol import ready as stage_ready
from test_protocol import ready as model_ready
from protocol import ADDRESS,ACK
import stage_protocol as s


class Sink:
    def __init__(self):self.files={}
    def raw(self,name,payload):
        if name in self.files:raise FileExistsError(name)
        self.files[name]=payload
    def json(self,name,value):self.raw(name,value)


class Core:
    def __init__(self):
        self.memory={};self.starts=[];self.halts=0;self.writes=[];self.fp_error=False
        self.running=False
    def halt(self):self.halts+=1;self.running=False
    def entry_snapshot(self):
        if self.running:raise ValueError('not halted')
        return {'secure':True,'cache':0}
    def floating_environment(self):
        if self.fp_error:raise ValueError('inherited nondefault FPSCR')
        return {'fpscr':0}
    def read(self,a,n):return bytes(self.memory.get(a+i,0) for i in range(n))
    def put(self,a,raw):self.memory.update({a+i:v for i,v in enumerate(raw)})
    def write(self,a,raw):
        self.writes.append((a,raw));self.put(a,raw)
        if a==s.ADDRESS+24:
            self.put(s.ADDRESS+28,raw);self.put(s.ADDRESS+16,struct.pack('<2I',4,1))
        if a==ADDRESS+20:
            w=list(struct.unpack('<128I',self.read(ADDRESS,512)))
            w[3]=5;w[6]=w[5];w[10]=5;w[19]=w[8];w[20]=100
            w[12:19]=[0]*7
            self.put(ADDRESS,struct.pack('<128I',*w))
            self.put(ADDRESS+320,struct.pack('<5f',1,2,3,4,5))
        return len(raw)
    def start_loaded_image(self,entry,msp):
        self.starts.append(entry);self.running=True
        if entry>0x34100000:
            raw=bytes(stage_ready());self.put(s.ADDRESS,raw)
            state=s.decode(raw)
            for a,(_,after) in state['observations'].items():self.put(a,struct.pack('<I',after))
        else:
            raw=model_ready();struct.pack_into('<4I',raw,12,1,0,0,0);self.put(ADDRESS,raw)
    def resume_from_halt(self):
        if self.running:raise ValueError('already running')
        if self.read(ADDRESS+16,4)!=struct.pack('<I',ACK):raise ValueError('missing ack')
        self.put(ADDRESS+12,struct.pack('<I',3));self.running=True


def payloads():
    reference=struct.pack('<5f',1,2,3,4,5)
    firmware={'entry':0x34064061,'msp':0x340F8000,
              'segments':((0x34064000,b'fake_model'),),
              'rows':tuple((i,bytes(164),reference) for i in range(1024))}
    platform={'entry':0x34180441,'msp':0x3418B000,'segments':((0x34180400,b'fake_stage'),)}
    return firmware,platform


class OrchestrationTests(unittest.TestCase):
    def test_complete_synthetic_pipeline(self):
        core=Core();sink=Sink();result=run_connected(core,*payloads(),sink,nonce=12)
        self.assertEqual(result['completed_rows'],1024)
        self.assertEqual(len(core.starts),2);self.assertFalse(core.running)
        self.assertFalse(result['energy_measured']);self.assertFalse(result['research_measurement_accepted'])
        self.assertEqual(len([n for n in sink.files if n.startswith('row_')]),1024)
        self.assertEqual(len([a for a,r in core.writes if a==ADDRESS+16]),1)
        self.assertIn('backup_stage_34180400.bin',sink.files)
        self.assertIn('platform_live_after_validation.json',sink.files)

    def test_nondefault_floating_mode_no_ack_or_inference(self):
        core=Core();core.fp_error=True;sink=Sink()
        with self.assertRaises(ValueError):run_connected(core,*payloads(),sink,nonce=12)
        self.assertFalse(any(a in (ADDRESS+16,ADDRESS+20) for a,r in core.writes))
        self.assertFalse(core.running);self.assertIn('completion_state.json',sink.files)

    def test_backup_failure_no_start(self):
        core=Core();sink=Sink()
        def fail(*args):raise OSError('disk error')
        sink.raw=fail
        with self.assertRaises(OSError):run_connected(core,*payloads(),sink,nonce=12)
        self.assertEqual(core.starts,[]);self.assertFalse(core.running)

    def test_header_deadline_after_read(self):
        clock=[0.0]
        class Reader:
            def read(self,*args):
                clock[0]+=11
                return struct.pack('<4I',s.MAGIC,1,4096,2)
        with self.assertRaises(TimeoutError):
            wait_header(Reader(),s.ADDRESS,s.MAGIC,4096,2,clock=lambda:clock[0])


if __name__=='__main__':unittest.main()
