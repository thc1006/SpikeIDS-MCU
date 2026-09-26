"""Correct only the proven SM05 route defect; stdout,never edit old evidence."""
from pathlib import Path
import hashlib
import json
import re

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'firmware_sram_accum24'
ROOT=HERE.parents[2]
GEN=ROOT/'results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate/nsl_qcfs_seed0.c'

def derive():
    old=(BASE/'accum_epochs.c').read_text();original=GEN.read_text()
    if hashlib.sha256(old.encode()).hexdigest()!='da52edfcf52aad6d0ea3e02aaa2df46ca8814d038e3a9c8769b585c63eb6326a':raise ValueError('SM05 source changed')
    if hashlib.sha256(original.encode()).hexdigest()!='8b7a8703240811f4b4f12517f33ce5c77bc004911c088514435340bc92c3b43e':raise ValueError('Original changed')
    orig=re.search(r'static void LL_ATON_Start_EpochBlock_31\(.*?\n\}',original,re.S).group()
    links=re.findall(r'ATONN_DSTPORT\(STRSWITCH, 0, ARITH, 1, 0\).*?ATONN_SRCPORT\(STRSWITCH, 0, CONVACC, (\d+), 0\)',orig)
    if links!=['3']:raise ValueError('Original third dense topology changed')
    pattern=r'(ATONN_DSTPORT\(STRSWITCH, 0, STRENG, 5, 0\).*?ATONN_SRCPORT\(STRSWITCH, 0, CONVACC, )1(, 0\))'
    new,count=re.subn(pattern,r'\g<1>'+links[0]+r'\2',old)
    if count!=2:raise ValueError('Expected one start and one end route correction only')
    return new

if __name__=='__main__':print(json.dumps({'accum_epochs.c':derive()}))
