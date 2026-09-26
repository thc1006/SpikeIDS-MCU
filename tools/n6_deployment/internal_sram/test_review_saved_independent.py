"""Finite saved-review parser controls. No compiler, model, or target calls.

Const aggregates/pool metadata here are independent literals. validate() tests
stub only its previously reviewed placement provider; inventory, descriptor
parsing and before/after byte checks are real temporary-file operations.
No genuine audit() or frozen failed candidate is invoked or modified.
"""
import ast
import copy
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sram_review_independent_subject', HERE / 'review_saved.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

POOLS = {
    'weights_sram': dict(name='weights_sram', address=str(0x34200000), rights='ACC_READ',
                         used_size_bytes=256, size_bytes=262144),
    'activations_sram': dict(name='activations_sram', address=str(0x34240000), rights='ACC_WRITE',
                             used_size_bytes=128, size_bytes=16384),
}


def code(cache='', macro=False):
    base = ('{(unsigned char *)ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL)}'
            if macro else '{(unsigned char *)(0x34240000UL)}')
    return f'''static const LL_Streng_TensorInitTypeDef stream = {{
 .dir=1, .raw=1, .addr_base={base},
 .offset_start=0, .offset_end=128, .offset_limit=192,
 {cache}
}};
LL_Streng_TensorInit(3, &stream, 1);
'''


@pytest.mark.parametrize('explicit', ['', '.cacheable=0, .cache_allocate=0,'])
@pytest.mark.parametrize('macro', [False, True])
def test_omitted_and_explicit_zero_raw_and_macro_bases(explicit, macro):
    records = r.descriptors(code(explicit, macro), POOLS)
    assert len(records) == 1
    row = records[0]
    assert row['effective_cacheable'] == row['effective_cache_allocate'] == 0
    assert row['prefetch_limit_beyond_used_bytes'] == 64
    assert row['cache_members_explicit'] == dict(cacheable=bool(explicit), cache_allocate=bool(explicit))


@pytest.mark.parametrize('mutation', ['nonzero_cache', 'nonzero_allocate', 'duplicate_member',
                                     'nonconst', 'alias', 'write', 'dynamic_member',
                                     'macro_member', 'duplicate_call', 'unknown_call',
                                     'data_beyond_used', 'limit_beyond_capacity',
                                     'limit_below_end', 'write_weights', 'no_raw',
                                     'uint32_overflow', 'octal_ambiguity'])
def test_narrow_descriptor_rejection(mutation):
    text = code()
    if mutation == 'nonzero_cache': text = code('.cacheable=1,')
    elif mutation == 'nonzero_allocate': text = code('.cache_allocate=1,')
    elif mutation == 'duplicate_member': text = code('.cacheable=0, .cacheable=0,')
    elif mutation == 'nonconst': text = text.replace('static const', 'static')
    elif mutation == 'alias': text += '\nconst void *other=&stream;'
    elif mutation == 'write': text += '\nstream.cacheable=1;'
    elif mutation == 'dynamic_member': text = text.replace('.offset_start=0', '.offset_start=dynamic()')
    elif mutation == 'macro_member': text = '#define offset_start offset_end\n' + text
    elif mutation == 'duplicate_call': text += '\nLL_Streng_TensorInit(4, &stream, 1);'
    elif mutation == 'unknown_call': text = text.replace('&stream, 1', '(void*)&stream, 1')
    elif mutation == 'data_beyond_used': text = text.replace('.offset_end=128', '.offset_end=129')
    elif mutation == 'limit_beyond_capacity': text = text.replace('.offset_limit=192', '.offset_limit=16385')
    elif mutation == 'limit_below_end': text = text.replace('.offset_limit=192', '.offset_limit=127')
    elif mutation == 'write_weights': text = text.replace('0x34240000', '0x34200000')
    elif mutation == 'no_raw': text = text.replace('.raw=1,', '')
    elif mutation == 'uint32_overflow': text = text.replace('.offset_limit=192', '.offset_limit=4294967296')
    elif mutation == 'octal_ambiguity':
        text = text.replace('.offset_start=0', '.offset_start=77').replace('.offset_end=128', '.offset_end=0100').replace('.offset_limit=192', '.offset_limit=0100')
    with pytest.raises(r.v.PreparationError):
        r.descriptors(text, POOLS)


def test_readonly_weight_input_accepted_but_never_writable():
    text = code().replace('0x34240000', '0x34200000').replace('.dir=1', '.dir=0')
    row, = r.descriptors(text, POOLS)
    assert row['pool'] == 'weights_sram' and row['fields']['dir'] == 0


@pytest.mark.parametrize('mutation', ['replace_c', 'extra_directory'])
def test_validate_rejects_late_descriptor_callback_output_change(tmp_path, monkeypatch, mutation):
    path = tmp_path / (r.v.NAME + '.c')
    path.write_text(code())
    monkeypatch.setattr(r, 'placement', lambda directory: {'pools': copy.deepcopy(POOLS)})
    original = r.descriptors
    def late(text, pools):
        rows = original(text, pools)
        if mutation == 'replace_c': path.write_text(code('.cacheable=1,'))
        else: (tmp_path / 'late_empty').mkdir()
        return rows
    monkeypatch.setattr(r, 'descriptors', late)
    with pytest.raises(r.v.PreparationError, match='Saved generated artifacts changed'):
        r.validate(tmp_path)


def test_validate_positive_preserves_original_bytes_and_scope(tmp_path, monkeypatch):
    path = tmp_path / (r.v.NAME + '.c')
    path.write_text(code())
    before = r.v.inventory(tmp_path)
    monkeypatch.setattr(r, 'placement', lambda directory: {'pools': copy.deepcopy(POOLS)})
    result = r.validate(tmp_path)
    assert result['dma_descriptor_count'] == 1
    assert result['full_dma_traversal_simulated'] is False
    assert result['hardware_register_state_verified'] is False
    assert result['reserved_pool_exclusion_required'] is True
    assert r.v.inventory(tmp_path) == before


def test_visible_placement_preserves_frozen_checks_except_explicit_cache_loop():
    old = ast.parse((HERE / 'generate.py').read_bytes())
    new = ast.parse((HERE / 'review_saved.py').read_bytes())
    old_func = next(n for n in old.body if isinstance(n, ast.FunctionDef) and n.name == 'validate_generated')
    new_func = next(n for n in new.body if isinstance(n, ast.FunctionDef) and n.name == 'placement')
    old_func.body = [n for n in old_func.body if not (isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == 'field')]
    old_func.name = new_func.name
    assert ast.dump(old_func, include_attributes=False) == ast.dump(new_func, include_attributes=False)
