"""Synthetic callbacks and serial factory only: no USB enumeration or port I/O."""
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest
import protocol as p
import serial_transport as t


@pytest.fixture(scope='module')
def requests():
    return tuple(p.request(i+1,100000+i*7,struct.pack('<41f',*(float(i+j) for j in range(41))))
                 for i in range(1024))


def hello():
    raw=struct.pack('<7I',p.HELLO,1,2,1,1,41,5)+p.MODEL.encode()+p.VECTORS.encode()
    return raw+p.crc(raw)


class Wire:
    def __init__(self,noise=b'',fragment=17):
        self.now=0.0;self.noise=noise;self.fragment=fragment;self.rx=bytearray()
        self.writes=[];self.reads=[];self.events=[]
    def clock(self):return self.now
    def write(self,raw,remaining):
        assert 0<remaining<=10;self.writes.append(raw);self.now+=0.001
        if raw==p.hello_query():self.rx.extend(self.noise+hello())
        else:
            _,_,seq,ordinal,row_id,_,_=struct.unpack_from('<4IQ2I',raw)
            frame=struct.pack('<4IQ2I',p.RESPONSE,1,seq,ordinal,row_id,0,5)+p.MODEL_RAW+struct.pack('<5f',1,2,3,4,5)
            self.rx.extend(frame+p.crc(frame))
        return len(raw)
    def read(self,count,remaining):
        assert 0<remaining<=10;self.reads.append(count);self.now+=0.001
        n=min(count,self.fragment,len(self.rx));raw=bytes(self.rx[:n]);del self.rx[:n]
        return raw
    def exchange(self,requests,**kwargs):
        return t.SerialExchange(self.read,self.write,self.events.append,requests,clock=self.clock,**kwargs)


def test_full1024_fragmented_responses_and_prefix_raw_retained(requests):
    w=Wire(b'boot\r\n\x00untrusted: ');x=w.exchange(requests)
    assert x(p.hello_query(),160)==hello()
    for raw in requests:assert len(x(raw,88))==88
    assert len(w.writes)==1025 and x.next==1025 and not x.poisoned
    frames=[e for e in w.events if e['event']=='frame']
    assert len(frames)==1025 and bytes.fromhex(frames[0]['hello_prefix_noise_hex'])==w.noise
    assert b''.join(bytes.fromhex(e['raw_hex']) for e in w.events if e['event']=='read' and e['exchange']==0)==w.noise+hello()
    assert [bytes.fromhex(e['raw_hex']) for e in w.events if e['event']=='request']==w.writes
    with pytest.raises(ValueError):x(requests[-1],88)
    assert x.poisoned and len(w.writes)==1025


def test_noise_at_bound_accepted_and_over_bound_poisoned(requests):
    w=Wire(b'abcd');assert w.exchange(requests,max_hello_noise=4)(p.hello_query(),160)==hello()
    w=Wire(b'abcde');x=w.exchange(requests,max_hello_noise=4)
    with pytest.raises(ValueError,match='noise bound'):x(p.hello_query(),160)
    with pytest.raises(ValueError,match='Poisoned'):x(p.hello_query(),160)
    assert len(w.writes)==1 and any(e['event']=='read' for e in w.events)


@pytest.mark.parametrize('count',[None,False,0,11])
def test_partial_or_ambiguous_write_never_retried(requests,count):
    w=Wire()
    def write(raw,remaining):w.writes.append(raw);return count
    x=t.SerialExchange(w.read,write,w.events.append,requests,clock=w.clock)
    with pytest.raises(ValueError,match='partial write'):x(p.hello_query(),160)
    assert x.poisoned and len(w.writes)==1 and not w.reads


def test_write_exception_preserves_attempt_and_poisons(requests):
    w=Wire()
    def write(raw,remaining):w.writes.append(raw);raise OSError('ambiguous device write')
    x=t.SerialExchange(w.read,write,w.events.append,requests,clock=w.clock)
    with pytest.raises(OSError):x(p.hello_query(),160)
    assert x.poisoned and w.events[0]['event']=='request' and len(w.writes)==1


@pytest.mark.parametrize('event',['request','write_return','read','frame'])
def test_retention_failure_poisons_and_no_further_io(requests,event):
    w=Wire()
    def retain(row):
        if row['event']==event:raise OSError('retention failure')
        w.events.append(row)
    x=t.SerialExchange(w.read,w.write,retain,requests,clock=w.clock)
    with pytest.raises(OSError):x(p.hello_query(),160)
    before=len(w.writes),len(w.reads)
    with pytest.raises(ValueError,match='Poisoned'):x(p.hello_query(),160)
    assert (len(w.writes),len(w.reads))==before and x.poisoned
    if event=='request':assert not w.writes


def test_late_read_is_retained_but_not_accepted(requests):
    w=Wire(fragment=4096)
    def read(count,remaining):
        raw=w.read(count,remaining);w.now+=11;return raw
    x=t.SerialExchange(read,w.write,w.events.append,requests,clock=w.clock)
    with pytest.raises(TimeoutError):x(p.hello_query(),160)
    assert x.poisoned and bytes.fromhex(w.events[-1]['raw_hex'])==hello()[:4]


def test_late_write_return_or_final_retention_does_not_accept(requests):
    w=Wire()
    def write(raw,remaining):
        n=w.write(raw,remaining);w.now+=11;return n
    x=t.SerialExchange(w.read,write,w.events.append,requests,clock=w.clock)
    with pytest.raises(TimeoutError):x(p.hello_query(),160)
    assert x.poisoned and not w.reads and w.events[-1]['event']=='write_return'
    w=Wire()
    def retain(row):
        w.events.append(row)
        if row['event']=='frame':w.now+=11
    x=t.SerialExchange(w.read,w.write,retain,requests,clock=w.clock)
    with pytest.raises(TimeoutError):x(p.hello_query(),160)
    assert x.poisoned and x.next==0


def test_retention_time_counts_before_write_deadline(requests):
    w=Wire()
    def retain(row):w.events.append(row);w.now+=11
    x=t.SerialExchange(w.read,w.write,retain,requests,clock=w.clock)
    with pytest.raises(TimeoutError):x(p.hello_query(),160)
    assert x.poisoned and not w.writes


def test_bad_crc_frame_retained_without_resync(requests):
    w=Wire()
    def write(raw,remaining):
        n=w.write(raw,remaining);w.rx[-1]^=1;return n
    x=t.SerialExchange(w.read,write,w.events.append,requests,clock=w.clock)
    with pytest.raises(ValueError,match='HELLO CRC'):x(p.hello_query(),160)
    assert x.poisoned and w.events[-1]['event']=='frame'


@pytest.mark.parametrize('bad',[b'',b'12345'])
def test_empty_or_oversized_read_recorded_then_rejected(requests,bad):
    w=Wire();x=t.SerialExchange(lambda *_:bad,w.write,w.events.append,requests,clock=w.clock)
    with pytest.raises(ValueError,match='Empty or oversized'):x(p.hello_query(),160)
    assert x.poisoned and w.events[-1]['raw_hex']==bad.hex()


def test_no_out_of_order_request_or_inference_prefix_skipping(requests):
    w=Wire();x=w.exchange(requests);x(p.hello_query(),160)
    with pytest.raises(ValueError,match='fixed ordered'):x(requests[1],88)
    assert len(w.writes)==1 and x.poisoned
    w=Wire();x=w.exchange(requests);x(p.hello_query(),160)
    w.rx.extend(b'!')
    with pytest.raises(ValueError,match='Response CRC'):x(requests[0],88)
    assert x.poisoned and len(w.writes)==2


class FakePort:
    def __init__(self,events,**options):
        assert options['port'] is None and options['exclusive'] is True
        assert options['rtscts'] is options['dsrdtr'] is options['xonxoff'] is False
        self.events=events;self.options=options;self.port=None;self.dtr=True;self.rts=True;self.closed=False
    def open(self):
        assert self.dtr is False and self.rts is False and self.port is not None
        self.events.append('open')
    def close(self):self.closed=True;self.events.append('close')


def opening_fixture(tmp_path):
    node=tmp_path/'ttyACM-test';node.write_bytes(b'not a real tty')
    alias=tmp_path/'by-id';alias.symlink_to(node)
    actions=[];made=[];records=[]
    def factory(**kw):
        p=FakePort(actions,**kw);made.append(p);return p
    def enumerate_ports():
        actions.append('enumerate')
        return [SimpleNamespace(device=str(node),serial_number='SERIAL-EXACT',vid=0x303a,pid=0x1001)]
    def exclusive(device):assert device is made[0];actions.append('exclusive')
    return node,alias,actions,made,records,dict(serial_factory=factory,enumerate_ports=enumerate_ports,claim_exclusive=exclusive)


def test_live_wrapper_explicit_byid_identity_exclusive_before_yield_and_close(tmp_path,requests):
    node,alias,actions,made,records,kwargs=opening_fixture(tmp_path)
    with t.open_exact_esp(str(alias),'SERIAL-EXACT',requests,records.append,**kwargs) as x:
        assert actions==['enumerate','open','exclusive','enumerate']
        assert made[0].port==str(node) and not x.poisoned
    assert made[0].closed and x.poisoned and actions[-1]=='close'
    assert records[0]['os_open_line_glitch_possible'] is True
    assert records[0]['library_open_discards_preopen_input'] is True
    assert records[-1]['electrical_state_verified'] is False


def test_all_input_validation_before_enumeration_or_open(tmp_path,requests):
    node,_,actions,_,records,kwargs=opening_fixture(tmp_path)
    bad=list(requests);bad[-1]=p.request(1024,999999,struct.pack('<41f',*([0.0]*41)))[:-1]+b'!'
    nonfinite=list(requests);raw=bytearray(nonfinite[-1]);struct.pack_into('<I',raw,64,0x7fc00000)
    raw[-4:]=p.crc(raw[:-4]);nonfinite[-1]=bytes(raw)
    for rows in (requests[:-1],tuple(bad),list(requests),tuple(nonfinite)):
        with pytest.raises(ValueError):
            with t.open_exact_esp(str(node),'SERIAL-EXACT',rows,records.append,**kwargs):pass
    assert not actions and not records


def test_wrong_or_duplicate_usb_identity_never_opens(tmp_path,requests):
    node,_,actions,made,records,kwargs=opening_fixture(tmp_path)
    for infos in ([SimpleNamespace(device=str(node),serial_number='OTHER',vid=0x303a,pid=0x1001)],
                  [SimpleNamespace(device=str(node),serial_number='SERIAL-EXACT',vid=0x303a,pid=0x1001)]*2):
        kwargs['enumerate_ports']=lambda:infos
        with pytest.raises(ValueError):
            with t.open_exact_esp(str(node),'SERIAL-EXACT',requests,records.append,**kwargs):pass
    assert not made and not actions


def test_identity_change_after_open_closes_without_yield(tmp_path,requests):
    node,_,actions,made,records,kwargs=opening_fixture(tmp_path);calls=0
    def enumerate_ports():
        nonlocal calls
        calls+=1
        return [SimpleNamespace(device=str(node),serial_number='SERIAL-EXACT' if calls==1 else 'CHANGED',vid=0x303a,pid=0x1001)]
    kwargs['enumerate_ports']=enumerate_ports
    with pytest.raises(ValueError):
        with t.open_exact_esp(str(node),'SERIAL-EXACT',requests,records.append,**kwargs):raise AssertionError('must not yield')
    assert made[0].closed and actions==['open','exclusive','close']


def test_exclusive_or_afteropen_retention_failure_still_closes(tmp_path,requests):
    node,_,actions,made,records,kwargs=opening_fixture(tmp_path)
    def exclusive(_):raise OSError('TIOCEXCL failure')
    kwargs['claim_exclusive']=exclusive
    with pytest.raises(OSError):
        with t.open_exact_esp(str(node),'SERIAL-EXACT',requests,records.append,**kwargs):pass
    assert made[0].closed
    kwargs['claim_exclusive']=lambda _:None
    def retain(row):
        if row['event']=='selected_device_after_open':raise OSError('retention unavailable')
        records.append(row)
    with pytest.raises(OSError):
        with t.open_exact_esp(str(node),'SERIAL-EXACT',requests,retain,**kwargs):pass
    assert made[-1].closed
