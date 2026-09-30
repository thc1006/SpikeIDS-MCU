"""Synthetic descriptor parser controls; no retained candidate reads."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import test_generate as a

spec=importlib.util.spec_from_file_location('saved_sram_review',Path(__file__).with_name('review_saved.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
POOLS={p['name']:p for p in a.tiny_metadata()['memory_pools']}

def source(*,cache='',base='(0x34240000UL)',end=164,limit=320,extra=''):
    return f'''static const LL_Streng_TensorInitTypeDef toy = {{
 .dir=0, .raw=1, .addr_base={{(unsigned char *){base}}},
 .offset_start=0, .offset_end={end}, .offset_limit={limit}, {cache}
}};
LL_Streng_TensorInit(3,&toy,1);
{extra}
'''

class SavedReviewTests(unittest.TestCase):
    def reject(self,text):
        with self.assertRaises(Exception):r.descriptors(text,POOLS)
    def test_omitted_zero_and_prefetch_reserved_padding(self):
        result=r.descriptors(source(),POOLS)
        self.assertEqual(result[0]['effective_cacheable'],0)
        self.assertEqual(result[0]['prefetch_limit_beyond_used_bytes'],64)
        self.assertFalse(result[0]['cache_members_explicit']['cacheable'])
    def test_explicit_zero(self):
        self.assertEqual(r.descriptors(source(cache='.cacheable=0,.cache_allocate=0,'),POOLS)[0]['effective_cache_allocate'],0)
    def test_macro_physical_address(self):
        self.assertEqual(r.descriptors(source(base='ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL)'),POOLS)[0]['pool'],'activations_sram')
    def test_nonzero_cache(self):self.reject(source(cache='.cacheable=1,'))
    def test_nonzero_allocate(self):self.reject(source(cache='.cache_allocate=1,'))
    def test_unknown_cache_expression(self):self.reject(source(cache='.cacheable=UNKNOWN,'))
    def test_c_octal_literal_not_misread_decimal(self):
        self.reject(source(end='0100',limit='0100').replace('.offset_start=0','.offset_start=77'))
    def test_uint32_boundary(self):
        self.assertEqual(r.number('0xffffffffUL'),0xffffffff)
        for value in ('4294967296','0x100000000UL'):
            with self.assertRaises(Exception):r.number(value)
    def test_nonconst(self):self.reject(source().replace('static const','static'))
    def test_positional(self):self.reject(source().replace('.raw=1,','1,'))
    def test_duplicate_member(self):self.reject(source(cache='.raw=1,'))
    def test_unknown_member(self):self.reject(source(cache='.unknown=0,'))
    def test_symbol_mutation(self):self.reject(source(extra='toy.cacheable=1;'))
    def test_pointer_alias(self):self.reject(source(extra='const void *alias=&toy;'))
    def test_wrong_call_symbol(self):self.reject(source().replace('3,&toy,1','3,&other,1'))
    def test_duplicate_call(self):self.reject(source(extra='LL_Streng_TensorInit(4,&toy,1);'))
    def test_count_two(self):self.reject(source().replace('3,&toy,1','3,&toy,2'))
    def test_type_macro(self):self.reject('#define LL_Streng_TensorInitTypeDef other\n'+source())
    def test_extent_beyond_used(self):self.reject(source(end=257))
    def test_limit_beyond_capacity(self):self.reject(source(limit=16385))
    def test_limit_before_end(self):self.reject(source(limit=100))
    def test_weight_write(self):self.reject(source(base='(0x34200000UL)',end=16,limit=16).replace('.dir=0','.dir=1'))
    def test_cache_outside(self):self.reject(source(extra='another.cacheable=1;'))
    def test_full_placement_and_descriptor_projection(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);a.write_generated(p)
            (p/f'{r.v.NAME}.c').write_text(source()+ '\nvoid *weight=ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34200000UL);')
            result=r.validate(p)
            self.assertEqual(result['dma_descriptor_count'],1)
            self.assertFalse(result['full_dma_traversal_simulated'])
    def test_projection_does_not_remove_external_address_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);a.write_generated(p)
            (p/f'{r.v.NAME}.c').write_text(source()+'\nvoid *weight=ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x71000000UL);')
            with self.assertRaises(Exception):r.validate(p)

if __name__=='__main__':unittest.main()
