"""Separate offline SM03 build; fixed original compiler/model/runtime, no USB."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'firmware_sram_runtime'


def engine():
    if hashlib.sha256((BASE/'build.py').read_bytes()).hexdigest()!='2edcb14af35266f5dec57f6b05c9236be2e78475315b3bd49cf1be9f50a94e80':
        raise RuntimeError('Frozen SM02 build engine changed')
    # The older build engine independently verifies all frozen S6/vendor inputs.
    spec=importlib.util.spec_from_file_location('_sm03_previous_builder',BASE/'build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    b=module.engine()
    original=b.candidate_pins
    def inputs():
        pins=original()
        b.hold(pins,BASE/'build.py')
        b.hold(pins,HERE/'compat.c')
        return pins
    b.candidate_pins=inputs
    b.HERE=HERE
    b.INCLUDES=[HERE,*b.INCLUDES[1:]]
    b.FLAGS=[*b.FLAGS,'-ffp-contract=off','-fno-fast-math',
        '-Wl,--wrap=ll_sw_forward_quantizelinear',
        '-Wl,--wrap=ll_sw_forward_dequantizelinear']
    return b


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--output-dir',type=Path,required=True)
    r=engine().run(p.parse_args().output_dir)
    print(json.dumps(dict(arm_compile_link_succeeded=True,content_sha256=r['content_sha256'],hardware_executed=False)))
