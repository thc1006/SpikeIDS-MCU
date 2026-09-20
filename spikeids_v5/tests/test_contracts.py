"""Adversarial I/O/paper contracts and optional backend checks; never paper data."""
import ast
import copy
from pathlib import Path
import subprocess
import sys
import numpy as np
import pandas as pd
import pytest
import torch
import contracts as c
import data_loaders as dl
import models
import experiment_all as runner
import paper_contract as paper
from export_verified import compare_logits
from deployment_gate import cycles_to_microseconds


def test_runner_output_lock_is_a_real_context_manager(tmp_path):
    p=tmp_path/'run.lock'
    with runner.output_lock(p):
        with pytest.raises(RuntimeError):
            with runner.output_lock(p):pass
    with runner.output_lock(p):pass


@pytest.mark.parametrize('directive',[r'\input section',r'\input{\name}',r'\includeonly{section}',r'\InputIfFileExists{section}{}{}',r'\input{../outside}'])
def test_unresolved_or_unsafe_tex_input_is_not_ignored(tmp_path,directive):
    (tmp_path/'main.tex').write_text(directive)
    with pytest.raises(c.ContractError):paper.tex_sources(tmp_path/'main.tex')


def test_cyclic_and_missing_tex_fail(tmp_path):
    p=tmp_path/'main.tex';p.write_text(r'\input{absent}')
    with pytest.raises(c.ContractError,match='Missing'):paper.tex_sources(p)
    p.write_text(r'\input{child}');(tmp_path/'child.tex').write_text(r'\input{main}')
    with pytest.raises(c.ContractError,match='Cyclic'):paper.tex_sources(p)


def test_tex_nested_sources_and_escaped_comments(tmp_path):
    (tmp_path/'main.tex').write_text('\\input {result_macros_v5}\n\\input{section}\n% ignored input\\input absent\n')
    (tmp_path/'result_macros_v5.tex').write_text(paper.macro_text({'vFiveSeeds':'20'}))
    (tmp_path/'section.tex').write_text(r'Accuracy is \vFiveSeeds. Cost is 5\% of a value. % trailing')
    sources=paper.tex_sources(tmp_path/'main.tex')
    assert set(sources)=={'main.tex','section.tex','result_macros_v5.tex'}
    assert r'5\%' in sources['section.tex'] and 'trailing' not in sources['section.tex']
    assert paper.prose_findings(tmp_path/'main.tex')==[]
    (tmp_path/'section.tex').write_text(r'\renewcommand{\vFiveSeeds}{10}')
    assert any('redefinition' in issue for issue in paper.prose_findings(tmp_path/'main.tex'))


def test_missing_macro_input_fails(tmp_path):
    (tmp_path/'main.tex').write_text('A paper without generated results')
    with pytest.raises(c.ContractError,match='does not input'):paper.prose_findings(tmp_path/'main.tex')


def test_small_p_never_printed_as_zero():
    assert paper.fmt_p(.0000007)=='<0.001'
    assert paper.fmt_p(None)==r'\text{undefined}'
    with pytest.raises(c.ContractError):paper.fmt_p(float('nan'))


@pytest.mark.parametrize('case',['omit_array','forge_semantic_hash','omit_preprocessor'])
def test_resealing_bad_cache_metadata_does_not_bypass_checks(prepared,case):
    path=prepared/'nslkdd'/'metadata.json';m=c.load_json(path);m.pop('content_sha256')
    if case=='omit_array':m['files_sha256'].pop('ids_fit.npy')
    if case=='forge_semantic_hash':m['data_fingerprint']='0'*64
    if case=='omit_preprocessor':m['files_sha256'].pop('preprocessing.json')
    if case!='forge_semantic_hash':
        m['data_fingerprint']=c.digest({k:v for k,v in m.items() if k!='data_fingerprint'})
    c.write_json(path,c.seal(m))
    with pytest.raises(c.ContractError):dl.open_cache(prepared/'nslkdd')


def test_numeric_category_codes_cannot_masquerade_as_raw(raw,tmp_path):
    p=raw/'iot23'/'iot23_combined.csv';df=pd.read_csv(p);df['proto']=6;df.to_csv(p,index=False)
    with pytest.raises(c.ContractError,match='numeric category'):dl.prepare('iot23',raw,tmp_path/'bad')


def test_cycles_frequency_units_and_logits_gate():
    assert cycles_to_microseconds([800,1600],800_000_000).tolist()==[1.,2.]
    x=np.array([[1.,2.],[3.,0.]])
    assert compare_logits(x,x,0.,0.)['allclose']
    y=x.copy();y[0]=[3.,2.]
    assert compare_logits(x,y,1.,0.)['prediction_disagreement_fraction']==.5
    with pytest.raises(c.ContractError):compare_logits(x,y,-1.,0.)


@pytest.mark.parametrize('cycles,hz',[([1.5],800),([0],800),([-1],800),([],800),([1],0),([1],float('nan'))])
def test_bad_timing_rejected(cycles,hz):
    with pytest.raises(c.ContractError):cycles_to_microseconds(cycles,hz)


@pytest.mark.parametrize('name',['run_v4_rerun.sh','finalize_and_check.sh'])
def test_shell_entry_points_propagate_failure_and_parse(name):
    p=c.PACKAGE/name;text='\n'.join(line for line in p.read_text().splitlines() if not line.lstrip().startswith('#'))
    assert 'set -euo pipefail' in text and '|| echo' not in text and 'train_fast.py' not in text
    subprocess.run(['bash','-n',str(p)],check=True)


@pytest.mark.parametrize('optimizer',['foreach','fused'])
def test_cpu_optimizer_independent_repeat_and_resume(prepared,tmp_path,optimizer):
    args=runner.parser().parse_args(['--dataset','nslkdd','--cache',str(prepared/'nslkdd'),'--output',str(tmp_path/'x.json'),
       '--model','qcfs','--optimizer',optimizer,'--epochs','2','--batch-size','16','--hidden','16','--seeds','0',
       '--device','cpu','--eval-every','1','--checkpoint-every','1','--threads','1'])
    runner.validate_args(args);data=runner.prepare_data(args);device=torch.device('cpu')
    a=runner.train_one('qcfs',0,data,models,args,device,'test',tmp_path/'a.pt')
    b=runner.train_one('qcfs',0,data,models,args,device,'test',tmp_path/'b.pt')
    assert a['training_reproducibility_sha256']==b['training_reproducibility_sha256']
    with pytest.raises(InterruptedError):runner.train_one('qcfs',0,data,models,args,device,'test',tmp_path/'c.pt',stop_after=1)
    args.resume=True
    z=runner.train_one('qcfs',0,data,models,args,device,'test',tmp_path/'c.pt')
    assert a['training_reproducibility_sha256']==z['training_reproducibility_sha256']


def test_no_assert_statement_is_used_as_a_runtime_contract():
    for p in c.PACKAGE.glob('*.py'):
        assert not any(isinstance(node,ast.Assert) for node in ast.walk(ast.parse(p.read_text()))),p.name


def test_parquet_raw_preparation_when_dependency_available(raw,tmp_path):
    pytest.importorskip('pyarrow',reason='Parquet engine unavailable in this environment')
    for role in ('training','testing'):
        p=raw/f'UNSW_NB15_{role}-set.csv'
        pd.read_csv(p).to_parquet(p.with_suffix('.parquet'),index=False)
    m,a=dl.prepare('unsw',raw,tmp_path/'parquet')
    assert m['dataset']=='unsw' and np.isfinite(a['x_fit']).all()


def test_onnx_qdq_minimal_execution_when_dependencies_available(tmp_path):
    onnx=pytest.importorskip('onnx',reason='ONNX is unavailable in this environment')
    ort=pytest.importorskip('onnxruntime',reason='ONNX Runtime is unavailable in this environment')
    from onnxruntime.quantization import quantize_static,QuantFormat,QuantType,CalibrationDataReader
    class Reader(CalibrationDataReader):
        def __init__(self):self.it=iter([{'input':np.ones((1,4),dtype=np.float32)*i/10} for i in range(10)])
        def get_next(self):return next(self.it,None)
    torch.manual_seed(0);model=models.build('qcfs',4,3,8)
    model(torch.randn(16,4));model.eval();frozen=models.freeze_for_export(model,fold_bn=False)
    x=torch.ones(1,4);p=tmp_path/'fp32.onnx';q=tmp_path/'qdq.onnx'
    torch.onnx.export(frozen,x,str(p),dynamo=False,input_names=['input'],output_names=['logits'],opset_version=17)
    onnx.checker.check_model(onnx.load(p))
    sess=ort.InferenceSession(str(p),providers=['CPUExecutionProvider'])
    with torch.no_grad():reference=model(x).numpy()
    assert np.allclose(reference,sess.run(None,{'input':x.numpy()})[0],atol=1e-5,rtol=1e-5)
    quantize_static(str(p),str(q),Reader(),quant_format=QuantFormat.QDQ,
        activation_type=QuantType.QInt8,weight_type=QuantType.QInt8,op_types_to_quantize=['Gemm','MatMul'])
    onnx.checker.check_model(onnx.load(q))
    out=ort.InferenceSession(str(q),providers=['CPUExecutionProvider']).run(None,{'input':x.numpy()})[0]
    assert np.isfinite(out).all() and out.shape==(1,3)


@pytest.mark.skipif(not torch.cuda.is_available(),reason='CUDA hardware is unavailable in this environment')
def test_cuda_qcfs_repeat_and_resume(prepared,tmp_path):
    args=runner.parser().parse_args(['--dataset','nslkdd','--cache',str(prepared/'nslkdd'),'--output',str(tmp_path/'x.json'),
        '--model','qcfs','--optimizer','fused','--epochs','2','--batch-size','16','--hidden','16','--seeds','0',
        '--device','cuda','--eval-every','1','--checkpoint-every','1','--threads','1'])
    runner.validate_args(args);data=runner.prepare_data(args);device=torch.device('cuda')
    runner.place_data(data,device,'gpu',0.)
    a=runner.train_one('qcfs',0,data,models,args,device,'test',tmp_path/'a.pt')
    b=runner.train_one('qcfs',0,data,models,args,device,'test',tmp_path/'b.pt')
    assert a['training_reproducibility_sha256']==b['training_reproducibility_sha256']
    with pytest.raises(InterruptedError):runner.train_one('qcfs',0,data,models,args,device,'test',tmp_path/'c.pt',stop_after=1)
    args.resume=True;z=runner.train_one('qcfs',0,data,models,args,device,'test',tmp_path/'c.pt')
    assert a['training_reproducibility_sha256']==z['training_reproducibility_sha256']
