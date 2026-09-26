"""Additive offline SM06 route correction,old SM05 evidence stays immutable."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'firmware_sram_accum24'

def engine():
    if hashlib.sha256((BASE/'build.py').read_bytes()).hexdigest()!='dbf3a0b8e3a0d71c3c70beb32045303f6820372f621571758543affe6ef27be6':raise ValueError('SM05 builder changed')
    spec=importlib.util.spec_from_file_location('_sm06_builder',BASE/'build.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    b=m.engine();prior=b.candidate_pins
    def pins():
        p=prior();b.hold(p,BASE/'build.py');b.hold(p,HERE/'prepare.py');return p
    b.candidate_pins=pins;b.HERE=HERE;b.GEN=HERE/'generate';b.INCLUDES=[HERE,*b.INCLUDES[1:]]
    return b

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);p.add_argument('--output-dir',required=True,type=Path)
    r=engine().run(p.parse_args().output_dir)
    print(json.dumps(dict(arm_compile_link_succeeded=True,content_sha256=r['content_sha256'],hardware_executed=False)))
