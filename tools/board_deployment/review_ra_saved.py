"""Independent saved RA artifact verification; no build/program/board access."""
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'results/ra4e1_v5_build_20260925_01'


def check(path,pin):
    before=path.stat();raw=path.read_bytes();after=path.stat()
    assert path==path.resolve() and hashlib.sha256(raw).hexdigest()==pin['sha256'],str(path)
    for key,value in pin.items():
        if key!='sha256':assert getattr(before,key)==value==getattr(after,key),(str(path),key)


def main():
    report_raw=(OUT/'RESULT.json').read_bytes()
    assert hashlib.sha256(report_raw).hexdigest()=='bd43f525c8beb8605d3f317d1cfd6893bb11d7a537f5b9913f9c6e655360849a'
    r=json.loads(report_raw)
    for p,pin in r['input_pins'].items():check(Path(p),pin)
    for p,pin in r['artifact_inventory']['files'].items():check(OUT/p,pin)
    assert len(r['commands'])==37 and all(type(c['returncode']) is int and c['returncode']==0
            and c['timeout'] is False for c in r['commands'])
    assert (OUT/'undefined.stdout').read_bytes()==b''
    raw=(OUT/'firmware.elf').read_bytes();h=struct.unpack_from('<16sHHIIIIIHHHHHH',raw)
    assert h[1:4]==(2,40,1) and h[4]==4293
    loads=[];flash=bytearray(123120)
    for i in range(h[10]):
        typ,off,va,pa,fs,ms,flags,align=struct.unpack_from('<8I',raw,h[5]+i*h[9])
        if typ!=1 or not ms:continue
        assert (0<=va<va+ms<=0x80000) or (0x20000000<=va<va+ms<=0x20020000)
        if fs:
            assert 0<=pa<pa+fs<=123120
            flash[pa:pa+fs]=raw[off:off+fs]
        loads.append((va,fs,ms))
    assert bytes(flash)==(OUT/'firmware.bin').read_bytes()
    assert (0x2001f000,0,512) in loads
    msp,reset=struct.unpack_from('<2I',flash)
    assert reset==h[4] and msp==0x20002000
    upper=0;hexbytes={};eof=False;start_address=None
    for line in (OUT/'firmware.hex').read_text().splitlines():
        assert line.startswith(':') and not eof
        b=bytes.fromhex(line[1:]);assert len(b)==b[0]+5 and sum(b)%256==0
        n,kind=b[0],b[3];a=int.from_bytes(b[1:3],'big')
        if kind==0:
            for j,value in enumerate(b[4:4+n]):
                address=upper+a+j;assert 0<=address<123120 and address not in hexbytes
                hexbytes[address]=value
        elif kind==2:
            assert n==2 and a==0;upper=int.from_bytes(b[4:6],'big')<<4
        elif kind==4:
            assert n==2 and a==0;upper=int.from_bytes(b[4:6],'big')<<16
        elif kind==1:
            assert n==0 and a==0;eof=True
        elif kind==3:
            assert n==4 and a==0 and start_address is None
            start_address=(int.from_bytes(b[4:6],'big')<<4)+int.from_bytes(b[6:8],'big')
        elif kind==5:
            assert n==4 and a==0 and start_address is None
            start_address=int.from_bytes(b[4:8],'big')
        else:raise AssertionError('Unexpected HEX record type')
    assert eof and start_address==reset and len(hexbytes)==123120
    assert bytes(hexbytes[i] for i in range(123120))==bytes(flash)
    assert r['target_parity_accepted'] is False and r['hardware_accessed'] is False
    for p,pin in r['input_pins'].items():check(Path(p),pin)
    for p,pin in r['artifact_inventory']['files'].items():check(OUT/p,pin)
    assert (OUT/'RESULT.json').read_bytes()==report_raw
    return {'input_pins':len(r['input_pins']),'artifact_pins':len(r['artifact_inventory']['files']),
        'commands_zero':37,'elf_bin_hex_equal':True,'flash_bytes':len(flash),
        'initial_msp':hex(msp),'entry':hex(reset),'mailbox':hex(0x2001f000),
        'option_programming_records':False,'board_executed':False}


if __name__=='__main__':print(json.dumps(main(),sort_keys=True))
