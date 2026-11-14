import copy,csv
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest,torch
from src.phase6.readiness import load
from src.phase6.comparator_data import root_features,TabularSplit,validate_identity,identity_digest,load_tabular,require_training
from src.phase6.non_graph_comparator import LocalTabularMLP,best_local,select_candidate,train_select_repeat,write_predictions
from src.phase6.local_graphsage import classification_metrics,masked_bce
from src.phase6.run_local_comparator import verify_graph_predictions

ROOT=Path(__file__).resolve().parents[2]
PROTOCOL=load(ROOT/'configs/phase6/split_protocol_v1.json')
CONFIG=load(ROOT/'configs/phase6/non_graph_comparator_v1.json')

def tiny(split='TRAIN',org='Org1'):
    x=torch.tensor([[1.,0.,1.,1.,1.,1.,1.],[1.,1.,0.,0.,1.,0.,0.],[2.,0.,2.,1.,1.,2.,1.],[3.,1.,2.,.6,1.,1.,1.]])
    y=torch.tensor([1,0,1,-1]);mask=y!=-1
    t='2020-03-01T13:00:00' if split=='TRAIN' else '2020-10-06T07:00:00'
    keys=[(org,split,'fixture_'+split,t,i) for i in range(4)]
    return TabularSplit(x,y,mask,keys,np.array([True,False,True,False]),np.array([False,True,True,False]),[(0,2),(2,4)],split,org,dict(positive=2,negative=1,masked_recent_roots=1))

def packet():
    x=torch.arange(40,dtype=torch.float32).reshape(5,8);x[:2,7]=0
    return SimpleNamespace(packets=[SimpleNamespace(x=x,edge_index='never read')],routing=[SimpleNamespace(destination_rows=np.arange(2))],supervision='never read',provenance='never read')

def test_root_projection_exactly_seven_user_features():
    b=packet();torch.testing.assert_close(root_features(b),b.packets[-1].x[:2,:7]);assert root_features(b).shape==(2,7)

def test_no_graph_context_edges_labels_or_metadata_affect_projection():
    b=packet();before=root_features(b)
    b.packets[-1].x[2:]=float('nan');b.packets[-1].edge_index={'ground_truth':'forbidden'}
    b.supervision=torch.tensor([999,999]);b.provenance={'campaign':'secret'}
    torch.testing.assert_close(before,root_features(b),rtol=0,atol=0)

def test_projection_clones_and_does_not_modify_pipeline():
    b=packet();x=root_features(b);x[:]=0;assert b.packets[-1].x[0,1]!=0

@pytest.mark.parametrize('change',['ip','nan','width'])
def test_bad_root_schema_rejected(change):
    b=packet()
    if change=='ip':b.packets[-1].x[0,7]=1
    elif change=='nan':b.packets[-1].x[0,0]=float('nan')
    else:b.packets[-1].x=b.packets[-1].x[:,:7]
    with pytest.raises(ValueError):root_features(b)

@pytest.mark.parametrize('bad',[torch.zeros(2,8),torch.zeros(2,7,dtype=torch.float64),{'x':torch.zeros(2,7)},torch.full((2,7),float('nan'))])
def test_model_denies_extra_columns_metadata_and_invalid_inputs(bad):
    with pytest.raises(ValueError):LocalTabularMLP()(bad)

def test_masked_root_contributes_zero_gradient():
    d=tiny();m=LocalTabularMLP();z=m(d.x);z.retain_grad();masked_bce(z,d.y,d.mask).backward();assert z.grad[-1]==0

@pytest.mark.parametrize('split',['VAL','TEST'])
def test_optimizer_guard_forbids_non_train(split):
    with pytest.raises(ValueError):require_training(tiny(split),PROTOCOL,'Org1')

def test_optimizer_guard_forbids_other_organization():
    with pytest.raises(ValueError):require_training(tiny(org='Org2'),PROTOCOL,'Org1')

def test_test_cache_rejected_before_io(monkeypatch):
    monkeypatch.setattr(Path,'read_text',lambda *a,**k:pytest.fail('TEST path was opened'))
    with pytest.raises(ValueError,match='never opens TEST'):load_tabular(Path('nonexistent_TEST'),PROTOCOL,'TEST','Org1')

@pytest.mark.parametrize('kind',['future','offgrid','duplicate','mask','label','org','variant'])
def test_identity_leakage_and_cohort_guards(kind):
    d=tiny();keys=list(d.keys)
    if kind=='future':keys[0]=(*keys[0][:3],'2020-12-01T00:00:00',0)
    elif kind=='offgrid':keys[0]=(*keys[0][:3],'2020-03-01T13:01:00',0)
    elif kind=='duplicate':keys[1]=keys[0]
    elif kind=='mask':d.mask[-1]=True
    elif kind=='label':d.y[0]=2
    elif kind=='org':keys[0]=('Org2',*keys[0][1:])
    else:keys[0]=(*keys[0][:2],'fixture_TEST',*keys[0][3:])
    with pytest.raises(ValueError):validate_identity(keys,d.y,d.mask,'Org1','TRAIN',PROTOCOL)

def test_identity_digest_includes_mask_labels_and_ids():
    d=tiny();a=identity_digest(d.keys,d.y,d.mask);d.y[0]=0
    assert identity_digest(d.keys,d.y,d.mask)!=a

def test_candidate_selection_ap_then_bce_then_id():
    trials=[dict(candidate={'id':i},validation=dict(average_precision=a,bce=b)) for i,a,b in [('z',.7,.2),('a',.7,.2),('b',.7,.3),('c',.6,.1)]]
    assert select_candidate(trials)['candidate']['id']=='a'

@pytest.mark.parametrize('gap,gb,cb,expected',[(.1,.3,.9,'tabular_mlp'),(-.1,.9,.1,'graphsage'),(0,.3,.2,'tabular_mlp'),(0,.2,.3,'graphsage'),(0,.2,.2,'graphsage')])
def test_frozen_best_local_order(gap,gb,cb,expected):
    g=dict(eligible=3,positive=1,negative=2,average_precision=.6,bce=gb);c=dict(g,average_precision=.6+gap,bce=cb)
    assert best_local(g,c,PROTOCOL)==expected

def test_best_local_rejects_unequal_eligible_counts():
    g=dict(eligible=3,positive=1,negative=2,average_precision=.6,bce=.2)
    with pytest.raises(ValueError):best_local(g,dict(g,eligible=4),PROTOCOL)

def test_paired_graph_comparison_rejects_same_count_different_user(tmp_path):
    d=tiny('VAL');z=np.array([1.,-1.,2.,0.],dtype=np.float32);p=tmp_path/'scores.csv';write_predictions(p,d,z)
    expected=classification_metrics(d.y,z,d.mask)
    assert verify_graph_predictions(p,d,z,expected)['paired_keys_labels_masks_equal']
    keys=list(d.keys);keys[0]=(*keys[0][:4],999);d.keys=keys
    with pytest.raises(ValueError,match='key/label/mask'):verify_graph_predictions(p,d,z,expected)

def test_paired_graph_comparison_rejects_changed_scores(tmp_path):
    d=tiny('VAL');z=np.zeros(4,dtype=np.float32);p=tmp_path/'scores.csv';write_predictions(p,d,z)
    with pytest.raises(ValueError,match='predictions differ'):verify_graph_predictions(p,d,z+1,classification_metrics(d.y,z,d.mask))

def test_tiny_optimizer_and_exact_reproduction_smoke(tmp_path):
    torch.set_num_threads(1);c=copy.deepcopy(CONFIG);c['training'].update(max_epochs=2,early_stopping_patience=1)
    result,z=train_select_repeat(c,tiny(),tiny('VAL'),PROTOCOL,tmp_path/'models')
    assert result['exact_reproduction'] and result['selected']['optimizer_updates']>0 and len(z)==4
    assert result['selected']['selected_state_digest']!=result['selected']['initial_state_digest']

def test_representative_cannot_satisfy_full_gate(tmp_path,monkeypatch):
    from src.phase6 import run_local_comparator as r
    monkeypatch.setattr(r,'BASE',tmp_path);monkeypatch.setattr(r,'verify_preregistration',lambda:CONFIG)
    p=tmp_path/'full_v1/Org1';p.mkdir(parents=True)
    (p/'summary.json').write_text('{"status":"PASS_REPRESENTATIVE_ONLY","mode":"representative","test_inputs_opened":0,"threshold_calibration_performed":false}')
    with pytest.raises(ValueError,match='completed full component'):r.finalize()
    assert not (tmp_path/'final_v1').exists()
