"""Independent finite offline controls; no ST compiler, model or target calls.

The full-run fixture substitutes fixed location/hash policy for tiny files and
a real stdlib subprocess. The real capture, NPY-header reader, output owner,
generated-metadata consumer, hashing, failure and publisher paths are exercised.
It does not model compiler correctness, numerical parity or hardware behavior.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import zipfile

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('internal_sram_independent_subject', HERE / 'generate.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def dump(path, value):
    path.write_text(json.dumps(value, sort_keys=True))


def npy(dtype, shape):
    header = repr(dict(descr=dtype, fortran_order=False, shape=shape)).encode()
    header += b' ' * ((64 - ((10 + len(header) + 1) % 64)) % 64) + b'\n'
    count = 1
    for n in shape:
        count *= n
    return b'\x93NUMPY\x01\x00' + struct.pack('<H', len(header)) + header + bytes(count * int(dtype[-1]))


def metadata():
    pools = []
    for ident, (name, (base, size, rights, fname, is_weights)) in enumerate(g.POOLS.items(), 1):
        pools.append(dict(id=ident, name=name, address=str(base), size_bytes=size,
                          rights=rights, cacheable='CACHEABLE_OFF', subpools=[],
                          user_allocated=False, attributes=dict(use_for_initrs=is_weights),
                          fname=f'atonbuf.{fname}.raw', used_size_bytes=64 if is_weights else 164,
                          buffers=[3] if is_weights else [1, 2], alignment=8))
    buffers = [dict(id=1, mpool_id=2, is_param=False, offset_start=0, size_bytes=164, alignment=4,
                    shape=[1, 41], format='STAI_FORMAT_FLOAT', nbits=32),
               dict(id=2, mpool_id=2, is_param=False, offset_start=0, size_bytes=20, alignment=4,
                    shape=[1, 5], format='STAI_FORMAT_FLOAT', nbits=32),
               dict(id=3, mpool_id=1, is_param=True, offset_start=0, size_bytes=64, alignment=8)]
    io = lambda width: [dict(shape=[1, width], data_format=dict(type='FLOAT', size=32, quantizer='NONE'))]
    return dict(json_schema_version='2.0', ec_blobs_info=[], memory_pools=pools, buffers=buffers,
                memory_footprint=dict(weights=64, activations=164),
                graphs=[dict(original_inputs=io(41), original_outputs=io(5), inputs=[1], outputs=[2],
                             nodes=[dict(id=1, name='software', mapping='NODE_SW'),
                                    dict(id=2, name='hardware', mapping='NODE_HW')])])


def generated(folder, info=None):
    folder.mkdir()
    name = g.v.NAME
    for suffix in ('.h',):
        (folder / (name + suffix)).write_text('toy header')
    for suffix in ('.c', '.h'):
        (folder / ('stai_' + name + suffix)).write_text('toy wrapper')
    (folder / (name + '.c')).write_text('''void *weights = ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34200000UL);
void *activations = ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL + 0);
struct toy_flags flags = {.cacheable=0, .cache_allocate=0};
''')
    dump(folder / (name + '_c_info.json'), metadata() if info is None else info)
    (folder / (name + '_generate_report.txt')).write_text('''Total number of epochs 2
>> pure software (SW) epochs 1
>> hybrid epochs (using both software and hardware) 0
>> pure hardware (HW or EC) epochs 1
''')
    (folder / (name + '_atonbuf.SRAM_WEIGHTS.raw')).write_bytes(bytes(range(64)))


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    parent = repo / 'results' / 'fresh_phase'
    parent.mkdir(parents=True)
    here = repo / 'tools' / 'candidate'
    here.mkdir(parents=True)
    source = here / 'generate.py'
    source.write_bytes((HERE / 'generate.py').read_bytes())
    for name in ('PLAN.md', *g.PROFILE_HASHES):
        (here / name).write_bytes((HERE / name).read_bytes())
    helper = here / 'prepare_vendor.py'
    helper.write_bytes(g.HELPER.read_bytes())
    payload = repo / 'results' / 'old_export' / 'nslkdd' / 'qcfs' / 'qdq'
    payload.mkdir(parents=True)
    for name in g.v.INPUT_HASHES:
        (payload / name).write_bytes(b'opaque original fixture ' + name.encode())
    with zipfile.ZipFile(payload / 'validation_vectors.npz', 'w') as z:
        for name, dtype, shape in [('x', '<f4', (1024, 41)), ('reference_logits', '<f4', (1024, 5)),
                                   ('original_logits', '<f4', (1024, 5)), ('validation_row_ids', '<i8', (1024,))]:
            z.writestr(name + '.npy', npy(dtype, shape))
    install = tmp_path / 'installed'
    install.mkdir()
    toy_artifacts = tmp_path / 'toy_compiler_result'
    generated(toy_artifacts)
    mode = tmp_path / 'mode'
    mode.write_text('success')
    tool = install / 'fake_compiler'
    tool.write_text(f'''#!{sys.executable}
from pathlib import Path
import shutil, sys
assert sys.argv[1]=='generate'
assert '--binary' in sys.argv
print('toy compiler stdout', flush=True)
print('toy compiler stderr', file=sys.stderr, flush=True)
if Path({str(mode)!r}).read_text()=='nonzero': raise SystemExit(23)
out=Path(sys.argv[sys.argv.index('--output')+1])
for file in Path({str(toy_artifacts)!r}).iterdir(): shutil.copyfile(file,out/file.name)
''')
    tool.chmod(0o700)
    for key, value in dict(SELF=source, HERE=here, HELPER=helper, OUTPUT_PARENT=parent, DOC_HASHES={}).items():
        monkeypatch.setattr(g, key, value)
    for key, value in dict(REPO=repo, SELF=helper, PAYLOAD=payload, INSTALL=install, TOOL=tool,
                           INPUT_HASHES={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in payload.iterdir()},
                           TOOL_HASHES={'fake_compiler': hashlib.sha256(tool.read_bytes()).hexdigest()}).items():
        monkeypatch.setattr(g.v, key, value)
    return dict(output=parent / 'internal_sram_actual_01', source=source, payload=payload,
                here=here, mode=mode, templates=toy_artifacts)


def test_held_profile_exact_two_absolute_noncacheable_domains():
    profile = json.loads((HERE / 'neural_art.json').read_bytes())
    assert profile == {'Profiles': {'internal_sram': {'memory_pool': './internal_sram.mpool',
                        'options': '--native-float --cache-maintenance --Os --Oauto-sched'}}}
    pools = json.loads((HERE / 'internal_sram.mpool').read_bytes())['memory']
    assert pools['cacheinfo'] == [] and len(pools['mempools']) == 2
    for p, lo, hi, rights in zip(pools['mempools'], (0x34200000, 0x34240000),
                                (0x34240000, 0x34244000), ('ACC_READ', 'ACC_WRITE')):
        assert int(p['offset']['value'], 16) == lo
        assert int(p['size']['value']) * 1024 == hi - lo
        assert lo % 64 == hi % 64 == 0
        assert 0x34200000 <= lo < hi <= 0x34270000
        assert lo >= 0x34185100  # Separate from probe including its mailbox.
        assert p['mode'] == 'USEMODE_ABSOLUTE' and p['fformat'] == 'FORMAT_RAW'
        assert p['prop']['rights'] == rights and p['prop']['cacheable'] == 'CACHEABLE_OFF'


def test_full_run_retains_original_inputs_actual_exit_and_unaccepted_scope(evidence):
    f = evidence
    before = {str(p): g.v.snapshot(p) for p in f['payload'].iterdir()}
    report = g.run(f['output'])
    assert report['actual_process_exit'] is None
    assert type(report['call']['actual_return_code']) is int and report['call']['actual_return_code'] == 0
    assert report['call']['argv'][1] == 'generate'
    assert report['call']['argv'].count('generate') == 1
    assert all(report[k] is False for k in g.LIMITS)
    # A changed epoch footprint is an observation, not a required old 40-epoch result.
    assert report['observations']['mapping']['reported_epochs'] == dict(total=2, software=1, hybrid=0, hardware=1)
    assert report['reference_headers']['x.npy']['shape'] == [1024, 41]
    assert (f['output'] / 'model_qdq_int8.onnx').read_bytes() == (f['payload'] / 'model_qdq_int8.onnx').read_bytes()
    assert not (f['output'] / 'FAILED.json').exists()
    g.v.recheck(before)
    bare = dict(report)
    digest = bare.pop('content_sha256')
    assert hashlib.sha256(g.v.encoded(bare)).hexdigest() == digest
    assert json.loads((f['output'] / 'RESULT.json').read_bytes()) == report


def test_fixed_model_wrong_sha_fails_before_output(evidence):
    (evidence['payload'] / 'model_qdq_int8.onnx').write_bytes(b'wrong')
    with pytest.raises(g.v.PreparationError, match='Fixed SHA'):
        g.run(evidence['output'])
    assert not evidence['output'].exists()


def test_existing_namespace_not_adopted(evidence):
    evidence['output'].mkdir()
    marker = evidence['output'] / 'original'
    marker.write_bytes(b'untouched')
    with pytest.raises(g.v.PreparationError, match='already exists'):
        g.run(evidence['output'])
    assert list(evidence['output'].iterdir()) == [marker] and marker.read_bytes() == b'untouched'


def test_real_child_nonzero_preserves_streams_no_result(evidence):
    evidence['mode'].write_text('nonzero')
    with pytest.raises(g.v.PreparationError, match='Single compiler call failed'):
        g.run(evidence['output'])
    p = evidence['output']
    record = json.loads((p / 'generate.json').read_bytes())
    assert record['actual_return_code'] == 23 and record['timed_out'] is False
    assert (p / 'generate.stdout').read_text() == 'toy compiler stdout\n'
    assert (p / 'generate.stderr').read_text() == 'toy compiler stderr\n'
    assert (p / 'FAILED.json').exists() and not (p / 'RESULT.json').exists()


@pytest.mark.parametrize('mutation', ['external_pool', 'probe_pool', 'cache', 'param_spill',
                                     'unlisted_pool', 'offset_overrun', 'bad_alignment',
                                     'fake_bool_id', 'raw_short', 'raw_extra', 'c_external',
                                     'c_cache', 'c_unused_extent', 'io_buf_type',
                                     'io_buf_size', 'io_wrong_ref'])
def test_generated_artifact_negative_controls(tmp_path, mutation):
    folder = tmp_path / 'generated'
    r = metadata()
    if mutation == 'external_pool': r['memory_pools'][0]['address'] = str(0x71000000)
    elif mutation == 'probe_pool': r['memory_pools'][0]['address'] = str(0x34180400)
    elif mutation == 'cache': r['memory_pools'][0]['cacheable'] = 'CACHEABLE_ON'
    elif mutation == 'param_spill': r['buffers'][2]['mpool_id'] = 2
    elif mutation == 'unlisted_pool': r['buffers'][0]['mpool_id'] = 3
    elif mutation == 'offset_overrun': r['buffers'][2]['offset_start'] = 1
    elif mutation == 'bad_alignment': r['buffers'][2]['alignment'] = 3
    elif mutation == 'fake_bool_id': r['memory_pools'][0]['id'] = True
    elif mutation == 'io_buf_type': r['buffers'][0]['format'] = 'STAI_FORMAT_S8'
    elif mutation == 'io_buf_size': r['buffers'][0]['size_bytes'] = 163
    elif mutation == 'io_wrong_ref': r['graphs'][0]['inputs'] = [3]
    generated(folder, r)
    if mutation == 'raw_short': (folder / (g.v.NAME + '_atonbuf.SRAM_WEIGHTS.raw')).write_bytes(bytes(63))
    elif mutation == 'raw_extra': (folder / 'external.raw').write_bytes(b'x')
    elif mutation == 'c_external': (folder / (g.v.NAME + '.c')).write_text('void *p=ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x71000000UL);')
    elif mutation == 'c_cache':
        p = folder / (g.v.NAME + '.c')
        p.write_text(p.read_text().replace('.cacheable=0', '.cacheable=1'))
    elif mutation == 'c_unused_extent':
        p = folder / (g.v.NAME + '.c')
        p.write_text(p.read_text().replace('0x34240000UL + 0', '0x34240000UL + 164'))
    with pytest.raises(g.v.PreparationError):
        g.validate_generated(folder)


@pytest.mark.parametrize('mutation', ['extra_empty_directory', 'result_replacement'])
def test_late_input_hash_callback_cannot_change_published_output(evidence, monkeypatch, mutation):
    original = g.v.recheck
    injected = []
    def late(pins):
        result = original(pins)
        # Last recheck in current wrapper receives only original inputs. The
        # prior two post-publication rechecks include owned outputs as well.
        output = evidence['output']
        if (output / 'RESULT.json').exists() and not any(Path(p).is_relative_to(output) for p in pins):
            if mutation == 'extra_empty_directory': (output / 'late_empty').mkdir()
            else: (output / 'RESULT.json').write_bytes(b'replaced')
            injected.append(True)
        return result
    monkeypatch.setattr(g.v, 'recheck', late)
    with pytest.raises(g.v.PreparationError):
        g.run(evidence['output'])
    assert injected and (evidence['output'] / 'FAILED.json').exists()


def test_source_mutate_restore_after_subprocess_rejected(evidence, monkeypatch):
    original = g.invoke
    def late(owner, pins):
        result = original(owner, pins)
        path = evidence['source']
        old = path.read_bytes()
        path.write_bytes(b'mutated')
        path.write_bytes(old)
        return result
    monkeypatch.setattr(g, 'invoke', late)
    with pytest.raises(g.v.PreparationError, match='Held file changed'):
        g.run(evidence['output'])
    assert (evidence['output'] / 'FAILED.json').exists()


def test_foreign_root_rebind_never_receives_failed_marker(evidence, monkeypatch):
    original = g.invoke
    foreign = evidence['payload']
    before = g.v.inventory(foreign)
    def rebound(owner, pins):
        result = original(owner, pins)
        owner.path.rename(owner.path.with_name('owned_partial'))
        owner.path.symlink_to(foreign, target_is_directory=True)
        return result
    monkeypatch.setattr(g, 'invoke', rebound)
    with pytest.raises(g.v.PreparationError):
        g.run(evidence['output'])
    assert g.v.inventory(foreign) == before
    assert not (foreign / 'FAILED.json').exists()
