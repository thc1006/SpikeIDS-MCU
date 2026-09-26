"""Full-logit wire contract for the selected portable RA/ESP candidate.

Pure codec/session logic: no USB imports, power, device selection or retry.
The exchange transport must retain raw requests/replies and enforce a deadline.
"""
import math
import struct
import zlib

MODEL='22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d'
VECTORS='cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb'
MODEL_RAW=bytes.fromhex(MODEL)
REQUEST=0x51523556
RESPONSE=0x53523556
HELLO_QUERY=0x51483556
HELLO=0x49483556


def require(value,message):
    if not value:raise ValueError(message)


def u32(value,name):
    require(type(value) is int and 0<=value<=0xFFFFFFFF,'Invalid '+name)
    return value


def crc(raw):return struct.pack('<I',zlib.crc32(raw))


def hello_query():
    raw=struct.pack('<2I',HELLO_QUERY,1)
    return raw+crc(raw)


def decode_hello(raw,board_id):
    require(type(raw) is bytes and len(raw)==160,'HELLO length')
    require(type(board_id) is int and board_id in (1,2),'Unknown platform')
    require(raw[-4:]==crc(raw[:-4]),'HELLO CRC')
    fields=struct.unpack_from('<7I',raw)
    require(fields==(HELLO,1,board_id,1,1,41,5),'HELLO platform/backend/FP environment/shape')
    require(raw[28:92]==MODEL.encode() and raw[92:156]==VECTORS.encode(),'HELLO selected model/vectors')
    return {'board_id':board_id,'backend':'portable FP32 QDQ','model_sha256':MODEL,
            'validation_sha256':VECTORS,'floating_environment_passed':True}


def request(sequence,row_id,input_words):
    u32(sequence,'sequence')
    require(1<=sequence<=1024,'Sequence outside original validation run')
    require(type(row_id) is int and 0<=row_id<=0x7FFFFFFFFFFFFFFF,'Invalid original row ID')
    require(type(input_words) is bytes and len(input_words)==164,'All 41 raw FP32 inputs required')
    require(all(math.isfinite(x) for x in struct.unpack('<41f',input_words)),'Nonfinite input')
    raw=struct.pack('<4IQ2I',REQUEST,1,sequence,sequence-1,row_id,41,164)+MODEL_RAW+input_words
    require(len(raw)==228,'Internal request layout')
    return raw+crc(raw)


def decode_response(raw,sequence,row_id):
    require(type(raw) is bytes and len(raw)==88,'Full response length')
    require(raw[-4:]==crc(raw[:-4]),'Response CRC')
    magic,version,seq,ordinal,rid,status,count=struct.unpack_from('<4IQ2I',raw)
    require((magic,version,seq,ordinal,rid)==(RESPONSE,1,sequence,sequence-1,row_id),
            'Response ABI/sequence/ordinal/row identity')
    require(raw[32:64]==MODEL_RAW,'Response model identity')
    require(status==0 and count==5,'Board error status or incomplete logits: '+str(status))
    require(all(math.isfinite(x) for x in struct.unpack('<5f',raw[64:84])),'Nonfinite output')
    return raw[64:84]


class Session:
    def __init__(self,exchange,board_id):
        require(type(board_id) is int and board_id in (1,2),'Unknown board')
        self.exchange=exchange;self.board_id=board_id
        self.next=1;self.poisoned=False;self.identity=None

    def hello(self):
        require(not self.poisoned and self.identity is None,'HELLO unavailable')
        try:
            self.identity=decode_hello(self.exchange(hello_query(),160),self.board_id)
            return self.identity
        except BaseException:
            self.poisoned=True;raise

    def infer(self,row_id,input_words):
        require(not self.poisoned and self.identity is not None,'Unverified or poisoned session')
        raw=request(self.next,row_id,input_words)  # invalid caller input does not reach transport
        try:
            reply=self.exchange(raw,88)
            result=decode_response(reply,self.next,row_id)
            self.next+=1
            return result
        except BaseException:
            self.poisoned=True;raise
