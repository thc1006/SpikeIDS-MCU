"""Explicit one-shot ESP validation. Default checks fixed vectors offline.

No power control, reset, bootloader command, firmware selection or flashing.
Use an outer process timeout for device/driver calls. This numerical collector
cannot certify which image was programmed: deployment/readback is separate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from protocol import Session,request,MODEL,VECTORS
from validate import REPO,load_rows,run


class Store:
    def __init__(self,path):
        path=Path(path)
        if not path.is_absolute() or path!=path.resolve() or not path.is_relative_to(REPO/'results'):
            raise ValueError('Canonical absolute fresh results directory required')
        path.mkdir(mode=0o700,exist_ok=False,parents=False)
        self.path=path;self.event_number=0

    def json(self,name,value):
        if Path(name).name!=name:raise ValueError('Flat result filename required')
        raw=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
        fd=os.open(self.path/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:
            if stream.write(raw)!=len(raw):raise OSError('Short retained JSON write')
            stream.flush();os.fsync(stream.fileno())

    def event(self,value):
        self.json(f'wire_{self.event_number:06d}.json',value)
        self.event_number+=1


def main(argv=None):
    sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest()
             for p in Path(__file__).resolve().parent.glob('*.py')}
    def check_sources():
        if any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=sha for p,sha in sources.items()):
            raise ValueError('Collector source changed during validation')
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--execute-esp-validation',action='store_true')
    parser.add_argument('--port')
    parser.add_argument('--expected-usb-serial')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    rows=load_rows()
    requests=tuple(request(i,row_id,x) for i,(row_id,x,_) in enumerate(rows,1))
    check_sources()
    if not args.execute_esp_validation:
        print(json.dumps({'offline_vectors_checked':True,'rows':1024,'model_sha256':MODEL,
                          'validation_sha256':VECTORS,'hardware_accessed':False}));return 0
    if not args.port or not args.expected_usb_serial or args.output is None:
        parser.error('Execution requires --port, --expected-usb-serial and --output')
    store=Store(args.output)
    store.json('INTENT.json',{'kind':'esp_full_logit_numerical_validation',
        'model_sha256':MODEL,'validation_sha256':VECTORS,'source_sha256':sources,
        'requested_port':args.port,'expected_usb_serial':args.expected_usb_serial,
        'original_row_ids':[r[0] for r in rows],'automatic_retry':False,
        'power_control':False,'flash_written':False,'firmware_readback_verified':False})
    try:
        check_sources()
        from serial_transport import open_exact_esp
        with open_exact_esp(args.port,args.expected_usb_serial,requests,store.event) as exchange:
            session=Session(exchange,2)
            metrics=run(session,rows,lambda r:store.json(f"row_{r['ordinal']:04d}.json",r))
            store.json('HELLO_IDENTITY.json',session.identity)
            store.json('PARITY.json',metrics)
            if not metrics['full_logit_parity_passed']:raise ValueError('Original full-logit parity gate failed')
        check_sources()
        store.json('RESULT.json',{**metrics,'actual_process_exit':None,'port_close_completed':True,
                                 'provisional_without_external_exit':True})
        check_sources()
        print(json.dumps(metrics,sort_keys=True));return 0
    except BaseException as exc:
        store.json('FAILED.json',{'error':type(exc).__name__+': '+str(exc),
            'research_measurement_accepted':False,'automatic_retry':False})
        raise


if __name__=='__main__':raise SystemExit(main())
