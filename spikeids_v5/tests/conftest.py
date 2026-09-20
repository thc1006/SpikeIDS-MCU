import os
# Must precede torch/CUDA initialization, including when optional GPU tests run.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
os.environ.setdefault("NVIDIA_TF32_OVERRIDE", "0")
os.environ.setdefault("TORCH_ALLOW_TF32_CUBLAS_OVERRIDE", "0")
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import pytest
import torch
from data_loaders import NSL_FEATURES, CLASSES, IOT_NUM, CATS

torch.set_num_threads(1)
torch.use_deterministic_algorithms(True,warn_only=False)


def make_raw(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(327)
    nsl_labels=["back","ipsweep","warezclient","rootkit","normal"]
    for filename,repeat in (("KDDTrain+.txt",12),("KDDTest+.txt",5)):
        n=5*repeat;df=pd.DataFrame(rng.uniform(0,5,(n,len(NSL_FEATURES))),columns=NSL_FEATURES)
        for c,v in zip(CATS['nslkdd'],('tcp','http','SF')):df[c]=v
        df['label']=np.tile(nsl_labels,repeat);df['difficulty']=0
        df.to_csv(root/filename,index=False,header=False)
    for role,repeat in (("training",12),("testing",5)):
        y=np.tile(CLASSES['unsw'],repeat);n=len(y)
        df=pd.DataFrame({'id':np.arange(n),'dur':rng.uniform(0,10,n),'proto':['tcp']*n,
                         'service':['http']*n,'state':['FIN']*n,'sbytes':rng.uniform(0,99,n),
                         'attack_cat':y,'label':(y!='Normal').astype(int)})
        df.to_csv(root/f'UNSW_NB15_{role}-set.csv',index=False)
    for dataset in ('iot23','cicids2017'):
        directory=root/dataset;directory.mkdir(exist_ok=True)
        names=CLASSES[dataset];y=np.tile(names,20);n=len(y)
        if dataset=='iot23':
            y=np.where(y=='PortScan','PartOfAHorizontalPortScan',y)
            df=pd.DataFrame({c:rng.uniform(0,50,n) for c in IOT_NUM})
            for c,v in zip(CATS[dataset],('tcp','http','SF')):df[c]=v
            df['label']=y
        else:
            df=pd.DataFrame({' Flow Duration':rng.uniform(0,100,n),' Fwd Packet Length Mean':rng.uniform(0,20,n),
                             ' Constant Retained':np.ones(n),' Destination Port':rng.integers(0,65535,n),' Label':y})
        df.to_csv(directory/f'{dataset}_combined.csv',index=False)
    return root

@pytest.fixture
def raw(tmp_path):return make_raw(tmp_path/'raw')

@pytest.fixture
def prepared(raw,tmp_path):
    from data_loaders import prepare
    root=tmp_path/'cache'
    for d in CLASSES:prepare(d,raw,root/d,chunksize=31)
    return root
