"""SM07M offline build over the frozen SM06 builder; never connects to a board."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'firmware_sram_accum24_route'
BASE_BUILD_SHA='e629145ae191c8f2c66cf182d2c33f76bb60342f1994625d4ec429dcaef2980d'

def engine():
    if hashlib.sha256((BASE/'build.py').read_bytes()).hexdigest()!=BASE_BUILD_SHA:raise ValueError('SM06 builder changed')
    spec=importlib.util.spec_from_file_location('_sm07m_builder',BASE/'build.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    b=m.engine();prior=b.candidate_pins
    def pins():
        p=prior();b.hold(p,BASE/'build.py');b.hold(p,HERE/'measure.h');return p
    # GEN stays SM06's corrected generate/ (its nsl_qcfs_seed0.c includes ../accum_epochs.c).
    b.candidate_pins=pins;b.HERE=HERE;b.INCLUDES=[HERE,*b.INCLUDES[1:]]
    return b

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);p.add_argument('--output-dir',required=True,type=Path)
    r=engine().run(p.parse_args().output_dir)
    print(json.dumps(dict(arm_compile_link_succeeded=True,content_sha256=r['content_sha256'],hardware_executed=False)))
