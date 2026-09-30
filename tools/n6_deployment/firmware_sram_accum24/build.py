"""SM05 offline candidate compiler; never connects to a board or PPK."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'firmware_sram_firstfloat'

def engine():
    if hashlib.sha256((BASE/'build.py').read_bytes()).hexdigest()!='a04b7ddfa160cf7b9d81dbe91df7e17fe0570d722735429247f6c905d586220e':
        raise ValueError('Frozen SM04 builder changed')
    spec=importlib.util.spec_from_file_location('_sm05_builder',BASE/'build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    b=module.engine();prior=b.candidate_pins
    def pins():
        p=prior();b.hold(p,BASE/'build.py');b.hold(p,HERE/'prepare.py');return p
    b.candidate_pins=pins;b.HERE=HERE;b.GEN=HERE/'generate';b.INCLUDES=[HERE,*b.INCLUDES[1:]]
    return b

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--output-dir',required=True,type=Path)
    r=engine().run(p.parse_args().output_dir)
    print(json.dumps(dict(arm_compile_link_succeeded=True,content_sha256=r['content_sha256'],hardware_executed=False)))
