from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import torch
from torch.nn import functional as F

from src.organization.rolling_graph_v1 import OrganizationGraphRuntime,OBSERVABLE
from src.phase6.input_pipeline import BranchPipeline,PinnedInputs,TemporalNeighborSampler
from src.phase6.local_graphsage import LocalGraphSAGE,masked_bce,classification_metrics,state_digest
from src.phase6.local_training import seed_all,select_and_repeat
from src.phase6.readiness import load,sha
from src.phase6.training_data import WarmupForks,serialize_batch,cached_batches,dump_json,guarded_split

ROOT=Path(__file__).resolve().parents[2]
PROTOCOL=load(ROOT/'configs/phase6/split_protocol_v1.json')


def fixture(split='TRAIN'):
    t=datetime(2020,3,1,13) if split=='TRAIN' else datetime(2020,10,6,7)
    runtime=OrganizationGraphRuntime('Org1')
    rows=[dict(zip(OBSERVABLE,['Org1',t,u,ip,False])) for u,ip in [(1,'a'),(1,'b'),(2,'a'),(3,'c')]]
    runtime.apply_timestamp_batch(t,rows,[str(i) for i in range(len(rows))])
    view=runtime.training_view()
    sampler=TemporalNeighborSampler(view,'tiny_'+split,split,(100,100),1)
    batch=sampler.sample([0,1,2])
    batch.supervision.y[:]=torch.tensor([1,0,-1])
    batch.supervision.eligible_mask[:]=torch.tensor([True,True,False])
    return view,batch


def test_sampled_blocks_match_full_graphsage_forward():
    seed_all(3)
    view,batch=fixture()
    model=LocalGraphSAGE(7,2,0).eval()
    sampled=model(batch)
    full=torch.tensor(view.x.copy())
    adjacency=torch.tensor(view.edge_index.copy())
    for layer in model.layers:
        full=F.relu(layer(full,adjacency))
    reference=model.head(full[batch.root_rows.copy()]).squeeze(-1)
    torch.testing.assert_close(sampled,reference,rtol=1e-6,atol=1e-7)


def test_second_layer_consumes_hidden_state_not_raw_features():
    seed_all(7)
    _,batch=fixture()
    model=LocalGraphSAGE(11,2,0).eval()
    first=model(batch).detach()
    batch.packets[1].x[:,:7]*=100
    torch.testing.assert_close(first,model(batch),rtol=0,atol=0)
    with torch.no_grad():
        model.layers[0].lin_l.weight.add_(0.8)
    assert not torch.equal(first,model(batch))


def test_masks_exclude_unknown_roots_from_actual_loss_and_gradient():
    seed_all(10)
    _,batch=fixture()
    model=LocalGraphSAGE(16,2,0)
    logits=model(batch);logits.retain_grad()
    loss=masked_bce(logits,batch.supervision.y,batch.supervision.eligible_mask)
    loss.backward()
    assert logits.grad[2].item()==0
    assert any(p.grad is not None and p.grad.abs().sum()>0 for p in model.layers[0].parameters())
    assert any(p.grad is not None and p.grad.abs().sum()>0 for p in model.layers[1].parameters())


def test_all_masked_batch_has_no_optimizer_loss():
    assert masked_bce(torch.zeros(2),torch.tensor([-1,-1]),torch.tensor([False,False])) is None


def test_average_precision_groups_ties_and_masks():
    assert classification_metrics([1,0],[0,0],[True,True])['average_precision']==0.5
    assert classification_metrics([1,0,-1],[10,-10,100],[True,True,False])['average_precision']==1
    assert classification_metrics([-1],[0],[False])['average_precision'] is None


@pytest.mark.parametrize('bad_split',['TEST','UNKNOWN'])
def test_no_test_cache_can_be_opened_even_for_selection(tmp_path,bad_split):
    with pytest.raises(ValueError,match='never opens TEST'):
        next(cached_batches(tmp_path,PROTOCOL,bad_split,'Org1'))


def test_model_represented_inductively_without_fixed_id_embeddings():
    seed_all(3)
    view,batch=fixture('VAL')
    model=LocalGraphSAGE(16,2,0).eval()
    score=model(batch)
    assert score.shape==(3,) and torch.isfinite(score).all()
    assert not any(isinstance(module,torch.nn.Embedding) for module in model.modules())


def write_tiny_cache(folder,split):
    folder.mkdir()
    view,batch=fixture(split)
    payload=serialize_batch(batch,view,{'users':set(),'ips':set()} if split=='VAL' else None)
    file=folder/'grid.pt'
    torch.save([payload],file)
    dump_json(folder/'manifest.json',dict(split=split,organization='Org1',positive=1,negative=1,
        files=[dict(path=file.name,sha256=sha(file),split=split,organization='Org1',
                    variant_id='tiny_'+split,asof=batch.provenance['asof'])]))


def test_real_optimizer_checkpoint_selection_and_exact_repeat_smoke(tmp_path):
    torch.set_num_threads(2)
    train,val=tmp_path/'TRAIN',tmp_path/'VAL'
    write_tiny_cache(train,'TRAIN');write_tiny_cache(val,'VAL')
    config=load(ROOT/'configs/phase6/local_training_v1.json')
    config['training']['max_epochs']=2
    config['training']['early_stopping_patience']=1
    config['candidates']=[{'id':'tiny','hidden_dim':8}]
    result=select_and_repeat(config,'Org1',train,val,PROTOCOL,tmp_path/'models')
    assert result['exact_repeat_state_and_validation_scores']
    checkpoint=torch.load(result['checkpoint'],weights_only=True)
    assert checkpoint['split_fitted']=='TRAIN' and checkpoint['split_selected']=='VAL'
    assert state_digest(checkpoint['model_state'])==result['selected_state_digest']


@pytest.mark.parametrize('split',['TRAIN','VAL'])
def test_warmup_forks_equal_original_pipeline_at_real_grid_times(split):
    pins=PinnedInputs(ROOT)
    factory=WarmupForks(pins,'Org1',split)
    first=f'CFV1_RA_CS_004_SEED1001_{split}'
    second=f'CFV1_SO_CS_027_SEED1001_{split}'
    try:
        with factory.open(first) as branch:
            branch.snapshot(branch.grid[2])
        with factory.open(second) as cached,BranchPipeline(pins,second,'Org1') as original:
            for i in [0,1,5]:
                a=cached.snapshot(cached.grid[i]);b=original.snapshot(original.grid[i])
                assert a.digest()==b.digest()
                assert cached.supervision_at(cached.grid[i])==original.supervision_at(original.grid[i])
    finally:
        factory.close()
