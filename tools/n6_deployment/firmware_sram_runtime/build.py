"""Additive offline build using the frozen S6 build engine; no target access."""
import argparse
import importlib.util
import json
from pathlib import Path
import hashlib

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'firmware_sram'
FROZEN = {
 'build.py':'37194ebe0a164873310855e11ec911f8acab468e1728e1c382addf31808d2872',
 'main.c':'7af7972cc89b2137a2a6d7cee80ccdd69209d77c33f4ce0225863869bee6bf94',
 'startup.c':'cdfafb4fd5cf4d55123358fab1396d5bb9afa18a60ba5eb0a62f7bf1b3ce9160',
 'syscalls.c':'e1ce7b80b8e3e64c9b0d888674e0c68e1a4cd6197450b0b1bc07eff78b934f6a',
 'mailbox.h':'29f9f4fd7d96e3cd3ec14dec99d14dad7353f8cca8eef421bb9a7fd5ca434e78',
 'linker.ld':'b2179f2bbd0cf749998b68185f8b8a6918dd06a57d9c447449a4f0c3fafacc38',
}


def engine():
    for name, sha in FROZEN.items():
        path = OLD / name
        if path != path.resolve() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise RuntimeError('Frozen source changed: ' + name)
    spec = importlib.util.spec_from_file_location('_s6_runtime_build_engine', OLD/'build.py')
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    original_candidate_pins = b.candidate_pins
    def pinned_candidates():
        pins = original_candidate_pins()
        for name, sha in FROZEN.items():
            p = OLD / name
            current = b.hold(pins, p)
            b.require(current['sha256'] == sha, 'Frozen source changed during preflight')
        return pins
    b.candidate_pins = pinned_candidates
    b.HERE = HERE
    b.INCLUDES = [HERE, *b.INCLUDES[1:]]
    return b


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args(argv)
    result = engine().run(args.output_dir)
    print(json.dumps(dict(arm_compile_link_succeeded=True,
        content_sha256=result['content_sha256'], hardware_executed=False)))


if __name__ == '__main__':
    main()
