"""SM04 offline build: original first Gemm semantics, later dense NPU retained."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'firmware_sram_qcompat'


def engine():
    if hashlib.sha256((BASE/'build.py').read_bytes()).hexdigest()!='310f3e2031ca7ac2e93865c80dfc1b2ee311c196ab02186a37c19f913055fdcd':
        raise ValueError('Frozen SM03 builder changed')
    spec=importlib.util.spec_from_file_location('_sm04_builder',BASE/'build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    b=module.engine();previous=b.candidate_pins
    def pins():
        held=previous();b.hold(held,BASE/'build.py')
        return held
    b.candidate_pins=pins
    b.HERE=HERE;b.GEN=HERE/'generate'
    # The original engine uses GEN for both compiled source names and its
    # informational weights_path. Source wrappers moved; weights did not.
    # Normalize before BOTH content hashing and result encoding, never edit
    # an emitted receipt. Runtime payloads still come from the pinned bundle.
    encode=b.encoded
    def encoded(value):
        if isinstance(value,dict) and value.get('kind')=='n6_sram_offline_firmware_build':
            value['weights_path']=str(b.VENDOR/'generate/nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw')
        return encode(value)
    b.encoded=encoded
    # Keep original headers; the two source wrappers retain original includes.
    b.INCLUDES=[HERE,*b.INCLUDES[1:]]
    b.FLAGS=[*b.FLAGS,'-fexcess-precision=standard','-Wl,--wrap=ll_sw_forward_conv','-Wl,--wrap=LL_ATON_LIB_Cast']
    return b


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--output-dir',required=True,type=Path)
    r=engine().run(p.parse_args().output_dir)
    print(json.dumps(dict(arm_compile_link_succeeded=True,content_sha256=r['content_sha256'],hardware_executed=False)))
