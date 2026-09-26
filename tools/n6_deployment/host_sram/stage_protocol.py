"""Event-driven platform-stage mailbox. No reset, loader, power or model ACK."""
import struct
from protocol import ProtocolError, require, u32

ADDRESS=0x34188000
SIZE=4096
MAGIC=0x4E365349
FILTERS=((0x54027000,7),(0x54028000,7),(0x54029000,11),
         (0x5402A000,11),(0x5402B000,11),(0x54034000,2))
FINAL={
    0xE000ED14:(0x30000,0), 0xE000ED94:(1,0), 0xE000EDD0:(3,0),
    0x56028000:(8,8), 0x56028004:(8,8), 0x56028020:(0x33330000,0),
    0x56028024:(0x777077,0x100000), 0x56028254:(0x1000,0x1000),
    0x56028258:(0x4200,0x4200), 0x56028260:(0xC0000000,0xC0000000),
    0x5602824C:(1,1), 0x52023100:(0x100000,0),
    0x5402401C:(0x400,0x400), 0x5402403C:(0x400,0x400),
    0x54024C14:(0x370,0x310), 0x56028220:(0xC0000000,0), 0x580DFC00:(1,0),
}
for base,count in FILTERS:
    FINAL[base+8]=(0xFFFFFFFF,0)
    for index in range(count):
        for offset in (0,0x10,0x20): FINAL[base+0x40+index*0x40+offset]=(1,0)


def decode(raw):
    require(type(raw) is bytes and len(raw)==SIZE,'Expected complete platform mailbox')
    w=struct.unpack('<1024I',raw)
    require(w[:3]==(MAGIC,1,SIZE),'Wrong platform-stage identity')
    require(w[3] in (1,2,3,4) and w[4]%2==0,'Unpublished platform state')
    require(not any(w[27:32]) and not any(w[624:]),'Unexpected claim/reserved field')
    require((w[12]>>4)&0xFFF==0xD22 and w[13]&0x30000==0 and w[14]==0 and w[15]&3==0,
            'Wrong core/cache/Thread entry')
    require(w[9]&3==0,'Unprivileged/non-MSP initial context')
    require(w[3]==2 and w[26]==1,'Platform initialization rejected/faulted/incomplete')
    p=w[32:48]
    require(p[0]==0 and p[1]==12 and p[12:]==(0x10400,1,0,0),'Platform did not complete exact profile')
    require(p[9] in (0,0x80) and p[10]==(32000000 if p[9] else 64000000),'HSI divider metadata mismatch')
    count=p[11]
    require(0<count<=192,'Observation count invalid')
    observations={}
    for i in range(count):
        address,before,after=w[48+3*i:51+3*i]
        require(address not in observations,'Duplicate MMIO observation')
        observations[address]=(before,after)
    require(not any(w[48+3*count:624]),'Unused observation slots changed')
    for address,(mask,value) in FINAL.items():
        require(address in observations and observations[address][1]&mask==value,
                'Missing or inconsistent final MMIO observation: '+hex(address))
    require(0x56028048 in observations and
            all(v&0x180==p[9] for v in observations[0x56028048]),'HSI divider changed')
    return {'sequence':w[4],'heartbeat':w[5],'host_nonce':w[6],'echo_nonce':w[7],
            'nominal_cpu_npu_hz':p[10],'observations':observations,
            'raw':raw,'frequency_measured':False,'model_executed':False}


def snapshot(read, *, attempts=8):
    require(type(attempts) is int and 1<=attempts<=64,'Snapshot budget')
    def exact(a,n):
        raw=read(a,n)
        require(type(raw) is bytes and len(raw)==n,'Short stage read')
        return raw
    for _ in range(attempts):
        before=struct.unpack('<I',exact(ADDRESS+16,4))[0]
        raw=exact(ADDRESS,SIZE)
        after=struct.unpack('<I',exact(ADDRESS+16,4))[0]
        if before==after==struct.unpack_from('<I',raw,16)[0] and before%2==0:
            return decode(raw)
    raise TimeoutError('Platform publication did not stabilize')


def challenge(read,write,nonce):
    u32(nonce)
    before=snapshot(read)
    require(nonce!=0 and nonce not in (before['host_nonce'],before['echo_nonce']), 'Nonce must be fresh/nonzero')
    n=write(ADDRESS+24,struct.pack('<I',nonce))
    require(type(n) is int and n==4,'Ambiguous nonce write; no retry')
    for _ in range(8):
        after=snapshot(read)
        require(after['host_nonce']==nonce,'Nonce changed or stage restarted')
        require(after['raw'][128:]==before['raw'][128:],'Platform report changed after initialization')
        if after['echo_nonce']==nonce and after['heartbeat']!=before['heartbeat'] and after['sequence']!=before['sequence']:
            require(after['sequence']==(before['sequence']+2)&0xFFFFFFFF and
                    after['heartbeat']==(before['heartbeat']+1)&0xFFFFFFFF,
                    'More than one publication for a single nonce')
            return after
    raise TimeoutError('No fresh platform liveness response')


def live_register_check(read,stage):
    """Read MMIO directly again after halting stage and before model handoff.

    This is not electrical qualification or a runtime NPU execution proof.
    All reads are finite observations; there is no atomic/future-state claim.
    """
    expected={**FINAL,0x56028048:(0x180,0x80 if stage['nominal_cpu_npu_hz']==32000000 else 0)}
    raw_readbacks={}
    for address,(mask,value) in expected.items():
        raw=read(address,4)
        require(type(raw) is bytes and len(raw)==4,'Short direct MMIO read')
        actual=struct.unpack('<I',raw)[0];raw_readbacks[address]=actual
        require(actual&mask==value,'Live platform configuration changed: '+hex(address))
    return raw_readbacks
