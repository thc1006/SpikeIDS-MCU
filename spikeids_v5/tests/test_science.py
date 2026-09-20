import copy
import itertools
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import torch
from scipy import stats
from statsmodels.stats.weightstats import ttost_paired
from statsmodels.stats.multitest import multipletests
from sklearn.metrics import precision_recall_fscore_support,matthews_corrcoef,roc_auc_score,balanced_accuracy_score
import contracts as c
import data_loaders as dl
import models
import metrics
import stats_tests as st
import experiment_all as runner

@pytest.mark.parametrize('dataset',dl.CLASSES)
def test_four_dataset_preparation(prepared,dataset):
    meta,a=dl.open_cache(prepared/dataset)
    assert meta['dataset']==dataset
    ids=[a[f'ids_{s}'] for s in dl.SPLITS]
    assert not set(ids[0])&set(ids[1]) and not set(ids[0])&set(ids[2]) and not set(ids[1])&set(ids[2])
    assert sum(map(len,ids))==len(set(np.concatenate(ids)))
    for split in dl.SPLITS:
        assert np.isfinite(a[f'x_{split}']).all()
        assert a[f'x_{split}'].dtype==np.float32
        assert len(np.unique(a[f'y_{split}']))==len(dl.CLASSES[dataset])
    assert np.abs(a['x_fit'].mean(0)).max()<1e-5
    assert meta['upstream_preprocessing_verified'] is False
    assert meta['duplicate_or_group_leakage_excluded'] is False


def test_test_only_features_never_change_fit(raw,tmp_path):
    m1,a1=dl.prepare('nslkdd',raw,tmp_path/'one',chunksize=17)
    fit=a1['x_fit'].copy();val=a1['x_validation'].copy()
    path=raw/'KDDTest+.txt';df=pd.read_csv(path,header=None);df.iloc[:,0]=1e9;df.iloc[:,2]='unknown_only_test';df.to_csv(path,index=False,header=False)
    m2,a2=dl.prepare('nslkdd',raw,tmp_path/'two',chunksize=17)
    assert np.array_equal(fit,a2['x_fit']) and np.array_equal(val,a2['x_validation'])
    assert m1['preprocessor_sha256']==m2['preprocessor_sha256']
    assert m1['data_fingerprint']!=m2['data_fingerprint']
    p=c.load_json(tmp_path/'two'/'preprocessing.json')
    assert p['unknown_categories']['test']['service']==len(a2['y_test'])
    assert all('unknown_only_test' not in s for s in p['categories']['service'])


def test_raw_change_invalidates_cache(raw,tmp_path):
    dl.prepare('nslkdd',raw,tmp_path/'cache')
    with (raw/'KDDTrain+.txt').open('a') as f:f.write((raw/'KDDTrain+.txt').read_text().splitlines()[0]+'\n')
    with pytest.raises(c.ContractError,match='another'):dl.prepare('nslkdd',raw,tmp_path/'cache')


def test_cache_tampering(prepared):
    p=prepared/'nslkdd'/'x_fit.npy'
    a=np.load(p);a[0,0]+=1;np.save(p,a)
    with pytest.raises(c.ContractError,match='changed'):dl.open_cache(prepared/'nslkdd')


def test_no_silent_label_drop(raw,tmp_path):
    p=raw/'KDDTrain+.txt';df=pd.read_csv(p,header=None);df.iloc[0,-2]='unknown_attack';df.to_csv(p,index=False,header=False)
    with pytest.raises(c.ContractError,match='Unmapped'):dl.prepare('nslkdd',raw,tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_missing_shard_fails(raw):
    (raw/'KDDTest+.txt').unlink()
    with pytest.raises(c.ContractError,match='missing'):dl.source_files('nslkdd',raw)


def test_iot_categorical_no_presplit_encoding(raw,tmp_path):
    meta,a=dl.prepare('iot23',raw,tmp_path/'before',chunksize=17)
    df=pd.read_csv(raw/'iot23'/'iot23_combined.csv')
    # Modify only rows already assigned to test; labels (and hence split) stay fixed.
    df.loc[a['ids_test'],'service']='UNSEEN_TEST'
    df.to_csv(raw/'iot23'/'iot23_combined.csv',index=False)
    m2,a2=dl.prepare('iot23',raw,tmp_path/'after',chunksize=17)
    assert np.array_equal(a['x_fit'],a2['x_fit']) and meta['preprocessor_sha256']==m2['preprocessor_sha256']


def test_cic_keeps_constants_and_features_not_test_selected(prepared):
    meta,_=dl.open_cache(prepared/'cicids2017')
    assert 'Constant Retained' in meta['features'] and 'Destination Port' not in meta['features']

@pytest.mark.parametrize('classes',[2,5,15])
def test_metrics_match_independent_sklearn(classes):
    rng=np.random.default_rng(711);y=np.tile(np.arange(classes),10)
    prob=rng.uniform(.01,1,(len(y),classes));prob/=prob.sum(1,keepdims=True);pred=prob.argmax(1)
    m=metrics.full_evaluate(y,pred,prob,classes,[str(i) for i in range(classes)])
    p,r,f,s=precision_recall_fscore_support(y,pred,labels=list(range(classes)),zero_division=0)
    assert m['macro_precision']==pytest.approx(p.mean()*100)
    assert m['macro_recall']==pytest.approx(r.mean()*100)
    assert m['macro_f1']==pytest.approx(f.mean()*100)
    assert m['weighted_f1']==pytest.approx(np.dot(f,s)/s.sum()*100)
    assert m['weighted_recall']==pytest.approx(m['overall_acc'])
    assert m['mcc']==pytest.approx(matthews_corrcoef(y,pred))
    assert m['balanced_acc']==pytest.approx(balanced_accuracy_score(y,pred)*100)
    auc=roc_auc_score(y,prob[:,1]) if classes==2 else roc_auc_score(y,prob,multi_class='ovr',average='macro')
    assert m['roc_auc_macro']==pytest.approx(auc)

@pytest.mark.parametrize('bad',['labels','probability','shape','nonfinite','empty'])
def test_metric_bad_inputs_fail(bad):
    y=np.array([0,1,2]);prob=np.eye(3)*.8+.2/3;pred=y.copy()
    if bad=='labels':y=y.astype(float)
    if bad=='probability':prob*=2
    if bad=='shape':prob=prob[:2]
    if bad=='nonfinite':prob[0,0]=np.nan
    if bad=='empty':y=y[:0];pred=pred[:0];prob=prob[:0]
    with pytest.raises(c.ContractError):metrics.full_evaluate(y,pred,prob,3,['a','b','c'])


def test_absent_class_semantics_and_binary_auc():
    y=np.array([0,1,0,1]);p=np.array([[.8,.1,.1],[.1,.8,.1],[.7,.2,.1],[.2,.7,.1]])
    r=metrics.full_evaluate(y,p.argmax(1),p,3,['a','b','c'])
    assert r['roc_auc_macro'] is None and r['per_class']['c']['fnr'] is None
    assert r['balanced_acc']==100 and r['macro_acc']==pytest.approx(200/3)

@pytest.mark.parametrize('L',[1,2,4,8])
def test_shifted_qcfs_matches_authors_ann_formula_gradients(L):
    q=models.QCFS(L=L)
    x=torch.linspace(-.2,1.2,151,requires_grad=True);z=x.detach().clone().requires_grad_()
    theta=torch.tensor(1.,requires_grad=True)
    actual=q(x)
    expected=models.FloorSTE.apply(torch.clamp(z/theta,0,1)*L+.5)/L*theta
    assert torch.equal(actual,expected)
    actual.square().sum().backward();expected.square().sum().backward()
    assert torch.equal(x.grad,z.grad) and torch.equal(q.threshold.grad,theta.grad)
    frozen=models.FrozenQCFS(q)
    assert torch.equal(frozen(x.detach()),actual.detach())


def test_legacy_floor_is_separate_and_not_t1_binary():
    shifted=models.QCFS(4);old=models.QCFS(4,formula='legacy_floor_v1')
    assert shifted(torch.tensor([.2])).item()!=old(torch.tensor([.2])).item()
    quantized=shifted(torch.tensor([.25])).item()
    binary_spike=float(.5+.25>=1.)
    assert quantized==.25 and binary_spike==0.


def test_same_seed_initializes_common_affines():
    torch.manual_seed(1);a=models.build('relu',4,3,8)
    torch.manual_seed(1);b=models.build('qcfs',4,3,8)
    for k,p in a.named_parameters():
        if k in dict(b.named_parameters()):assert torch.equal(p,dict(b.named_parameters())[k])


def test_bn_fold_guards_and_matches_oracle():
    lin=torch.nn.Linear(4,3,bias=False,dtype=torch.float64)
    bn=torch.nn.BatchNorm1d(3,affine=False,dtype=torch.float64)
    with pytest.raises(c.ContractError):models.fuse_linear_bn(lin,bn)
    bn(lin(torch.randn(20,4,dtype=torch.float64)))
    lin.eval();bn.eval();f=models.fuse_linear_bn(lin,bn)
    x=torch.randn(10,4,dtype=torch.float64)
    assert f.weight.dtype==torch.float64
    assert torch.allclose(f(x),bn(lin(x)),atol=1e-12,rtol=1e-12)


def test_if_membrane_reset_between_calls():
    torch.manual_seed(2);m=models.build('qcfs',4,3,8).eval();x=torch.randn(12,4)
    a=models.simulate_if(m,x,4);b=models.simulate_if(m,x,4)
    assert torch.equal(a,b) and a.shape==(12,3)
    assert torch.equal(models.simulate_if(m,x[:6],4),a[:6])

@pytest.mark.parametrize('alternative',['two-sided','less','greater'])
@pytest.mark.parametrize('d',[[1,1,-2,2,0],[1,2,3,4,5],[0,0,0],[.1,-.1,.2,-.2,.2]])
def test_signed_rank_against_exhaustive_scipy(d,alternative):
    result=st.exact_signed_rank(d,alternative)
    a=np.round(np.array(d,dtype=float),12);a=a[a!=0]
    if not len(a):assert result['p']==1;return
    reference=stats.wilcoxon(a,alternative=alternative,method=stats.PermutationMethod(n_resamples=np.inf))
    assert result['p']==pytest.approx(reference.pvalue,abs=1e-15)
    assert result['statistic']==reference.statistic

@pytest.mark.parametrize('alpha',[.05,.1,.01])
def test_tost_against_statsmodels(alpha):
    rng=np.random.default_rng(11);x=rng.normal(75,1,20);y=x+rng.normal(.1,.5,20)
    r=st.tost_paired(x,y,1.,alpha)
    p,lower,upper=ttost_paired(x,y,-1,1)
    assert r['p_tost']==pytest.approx(p,abs=1e-14)
    assert r['p_lower']==pytest.approx(lower[1],abs=1e-14) and r['p_upper']==pytest.approx(upper[1],abs=1e-14)
    assert r['confidence_level']==pytest.approx(1-2*alpha)
    assert r['equivalent']==(-1<r['ci'][0] and r['ci'][1]<1)
    at_boundary=st.tost_paired(x,y,r['delta_min_infimum'],alpha)
    assert at_boundary['p_tost']==pytest.approx(alpha)


def test_degenerate_effect_and_tost_inconclusive():
    w=st.wilcoxon_pair([2]*5,[1]*5)
    assert w['dz'] is None and w['mean_diff']==1 and w['p']==.0625
    t=st.tost_paired([.1]*20,[0]*20,1)
    assert t['p_tost'] is None and not t['equivalent']


def test_holm_oracle_and_missing_stays_in_family():
    p={'a':.003,'b':.05,'c':.013,'d':.8}
    h=st.holm(p)
    oracle=multipletests(list(p.values()),method='holm')[1]
    assert [h[k]['p_adj'] for k in p]==pytest.approx(oracle)
    h=st.holm({'a':.01,'undefined':None})
    assert h['a']['p_adj']==.02 and h['undefined']['p_adj']==1 and not h['undefined']['reject']
    with pytest.raises(c.ContractError):st.holm({'a':float('nan')})

@pytest.mark.parametrize('n',[5,20])
def test_power_quadrature_matches_independent_monte_carlo(n):
    sigma=.7;delta=.8;mu=.1;alpha=.05
    p=st.tost_power_normal_model(n,sigma,delta,alpha,mu)
    rng=np.random.default_rng(723);d=rng.normal(mu,sigma,(50000,n))
    means=d.mean(1);half=stats.t.ppf(1-alpha,n-1)*d.std(1,ddof=1)/np.sqrt(n)
    estimate=np.mean((means-half>-delta)&(means+half<delta))
    assert abs(p['power']-estimate)<.012
    assert p['integration_error_estimate']<1e-5


def test_required_n_bracket():
    n=st.required_n(.7,.8,power=.8)
    assert st.tost_power_normal_model(n,.7,.8)['power']>=.8
    if n>2:assert st.tost_power_normal_model(n-1,.7,.8)['power']<.8

@pytest.mark.parametrize('x,y', [([],[]),([1,np.nan],[1,2]),([1,2],[1]),([[1,2]],[[1,2]])])
def test_bad_stats_inputs(x,y):
    with pytest.raises(c.ContractError):st.tost_paired(x,y,1)


def test_bootstrap_fixed_seed_and_blocks():
    x=[.1,.2,.3,.5,.6]
    assert st.bootstrap_mean(x,seed=4,block=7)==st.bootstrap_mean(x,seed=4,block=1000)

@pytest.mark.parametrize('kind',['relu','qcfs','cnn'])
def test_cpu_training_repeat_resume(prepared,tmp_path,kind):
    args=runner.parser().parse_args(['--dataset','nslkdd','--cache',str(prepared/'nslkdd'),'--output',str(tmp_path/'x.json'),
         '--model',kind,'--epochs','3','--batch-size','16','--hidden','16','--seeds','0','--device','cpu',
         '--eval-every','2','--checkpoint-every','1','--threads','1'])
    runner.validate_args(args);data=runner.prepare_data(args);dev=torch.device('cpu')
    a=runner.train_one(kind,0,data,models,args,dev,'test',tmp_path/'a.pt')
    b=runner.train_one(kind,0,data,models,args,dev,'test',tmp_path/'b.pt')
    assert a['training_reproducibility_sha256']==b['training_reproducibility_sha256']
    with pytest.raises(InterruptedError):runner.train_one(kind,0,data,models,args,dev,'test',tmp_path/'c.pt',stop_after=1)
    args.resume=True;cresult=runner.train_one(kind,0,data,models,args,dev,'test',tmp_path/'c.pt')
    assert a['training_reproducibility_sha256']==cresult['training_reproducibility_sha256']

@pytest.mark.parametrize('n,b',[(2,2),(3,2),(17,16),(33,16),(32,16)])
def test_batches_complete_no_singleton(n,b):
    pairs=runner.batch_slices(n,b,True)
    assert [i for a,z in pairs for i in range(a,z)]==list(range(n))
    assert min(z-a for a,z in pairs)>=2


def test_json_duplicates_nonfinite_atomic_failure(tmp_path):
    p=tmp_path/'a.json';p.write_text('{"x":1,"x":2}')
    with pytest.raises(c.ContractError):c.load_json(p)
    with pytest.raises(ValueError):c.write_json(p,{'x':float('nan')})
    assert p.read_text()=='{"x":1,"x":2}'
    def crash(f):f.write(b'broken');raise OSError('injected')
    with pytest.raises(OSError):c.atomic_write(p,crash)
    assert p.read_text()=='{"x":1,"x":2}'


def test_seed_ids_not_position():
    rows=[{'seed':2,'score':2},{'seed':0,'score':0}]
    assert list(c.seed_rows(rows,[0,2]))==[2,0]
    with pytest.raises(c.ContractError):c.seed_rows([{'seed':0},{'seed':0}],[0,1])
    with pytest.raises(c.ContractError):c.seed_rows([{'score':2}],[0])


def test_locks(tmp_path):
    with c.file_lock(tmp_path/'lock'):
        with pytest.raises(c.ContractError):
            with c.file_lock(tmp_path/'lock'):pass
    with c.file_lock(tmp_path/'lock'):pass
