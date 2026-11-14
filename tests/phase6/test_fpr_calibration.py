import copy,csv,json
from pathlib import Path
import numpy as np
import pytest
from src.phase6.readiness import load
from src.phase6.fpr_calibration import calibrate_negatives,fp_budget,decisions,threshold_metrics,seal_threshold,load_frozen_threshold
from src.phase6.run_fpr_calibration import read_val_predictions,verify_pair,run,COLUMNS

ROOT=Path(__file__).resolve().parents[2]
PROTOCOL=load(ROOT/'configs/phase6/split_protocol_v1.json')

@pytest.mark.parametrize('n,budget',[(1,0),(99,0),(100,1),(199,1),(200,2),(45771,457),(2**53+99,(2**53+99)//100)])
def test_integer_budgets(n,budget):assert fp_budget(n)==budget

@pytest.mark.parametrize('n',[1,2,99])
def test_small_sample_conservative_zero_fp(n):
    c=calibrate_negatives(np.arange(n,dtype=float),PROTOCOL)
    assert c['achieved_fp']==c['fp_budget']==0 and c['sample_size_status']=='ZERO_FP_BUDGET_N_LT_100'
    assert c['resolution']==1/n

@pytest.mark.parametrize('values',[[],[np.nan],[np.inf],[-np.inf],[[1,2]]])
def test_empty_or_invalid_negatives_fail(values):
    with pytest.raises(ValueError):calibrate_negatives(values,PROTOCOL)

def test_distinct_boundary_exhausts_budget_and_is_maximally_permissive():
    c=calibrate_negatives(np.arange(200,dtype=np.float64),PROTOCOL)
    assert c['fp_budget']==c['achieved_fp']==2
    assert c['boundary_logit']==197 and c['fp_if_threshold_lowered_one_ulp']==3
    assert c['threshold']['value']==np.nextafter(197.,np.inf)

def test_boundary_ties_are_never_split():
    c=calibrate_negatives(np.r_[np.zeros(198),5.,5.],PROTOCOL)
    assert c['fp_budget']==2 and c['achieved_fp']==2 # two top ties permitted together
    c=calibrate_negatives(np.r_[np.zeros(197),5.,5.,5.],PROTOCOL)
    assert c['fp_budget']==2 and c['achieved_fp']==0 and c['boundary_tie_count']==3
    assert c['fp_if_threshold_lowered_one_ulp']==3

def test_all_ties_have_zero_fps_without_illegal_tie_splitting():
    c=calibrate_negatives(np.ones(100),PROTOCOL)
    assert c['achieved_fp']==0 and c['fp_budget']==1 and c['unused_fp_budget']==1 and c['boundary_tie_count']==100

def test_float32_boundary_is_promoted_before_comparison():
    c=calibrate_negatives(np.ones(100,dtype=np.float32),PROTOCOL)
    # A Python scalar cast back to float32 rounds DOWN to the excluded boundary.
    assert np.float32(c['threshold']['value'])==np.float32(1)
    assert not decisions(np.ones(100,dtype=np.float32),c['threshold']).any()
    assert decisions(np.array([np.nextafter(np.float32(1),np.float32(np.inf))]),c['threshold'])[0]

def test_no_finite_threshold_uses_json_safe_no_alert_sentinel():
    c=calibrate_negatives([np.finfo(np.float64).max],PROTOCOL)
    assert c['threshold']=={'kind':'no_alert','value':None,'hex':None}
    assert not decisions(np.array([0.,np.finfo(np.float64).max]),c['threshold']).any()
    json.dumps(c,allow_nan=False)

def test_reversals_permutations_and_positive_outcomes_do_not_affect_threshold():
    z=np.repeat(np.arange(123),2);c=calibrate_negatives(z,PROTOCOL)
    assert c==calibrate_negatives(z[::-1],PROTOCOL)==calibrate_negatives(np.random.default_rng(3).permutation(z),PROTOCOL)
    a=threshold_metrics([0,1],[True,True],[0.,1000.],c['threshold'])
    b=threshold_metrics([0,1],[True,True],[0.,-100.],c['threshold'])
    assert a['recall']!=b['recall'] and c==calibrate_negatives(z,PROTOCOL)

def test_metrics_exclude_masked_roots_and_use_exact_inequality():
    t={'kind':'finite','value':1.,'hex':(1.).hex()}
    m=threshold_metrics([0,0,1,1,-1],[True,True,True,True,False],[1.,0.,1.,0.,100.],t)
    assert (m['tp'],m['fp'],m['tn'],m['fn'],m['masked'])==(1,1,1,1,1)
    assert m['fpr']==m['recall']==m['precision']==m['f1']==.5

def test_no_positive_and_no_alert_metrics_are_explicitly_undefined():
    c=calibrate_negatives([1.,2.],PROTOCOL)
    m=threshold_metrics([0,0],[True,True],[1.,2.],c['threshold'])
    assert m['precision'] is None and m['recall'] is None and m['f1'] is None and m['fpr']==0

@pytest.mark.parametrize('mask,labels',[([True,True],[0,-1]),([1,1],[0,1]),([True,True],[0,2])])
def test_bad_masks_labels_rejected(mask,labels):
    with pytest.raises(ValueError):threshold_metrics(labels,mask,[0.,1.],{'kind':'no_alert'})

@pytest.mark.parametrize('split',['TRAIN','TEST'])
def test_forbidden_calibration_split_before_io(split,monkeypatch):
    monkeypatch.setattr(Path,'open',lambda *a,**k:pytest.fail('Forbidden source opened'))
    with pytest.raises(ValueError):read_val_predictions(Path('scores.csv'),PROTOCOL,'Org1',split)
    with pytest.raises(ValueError):calibrate_negatives([1.],PROTOCOL,split)

def test_test_named_path_rejected_before_io(monkeypatch):
    monkeypatch.setattr(Path,'open',lambda *a,**k:pytest.fail('TEST file opened'))
    with pytest.raises(ValueError,match='TEST path'):read_val_predictions(Path('TEST/scores.csv'),PROTOCOL,'Org1')

def artifact():
    return seal_threshold(dict(status='FROZEN_VAL_THRESHOLD',calibration_split='VAL',organization='Org1',detector='graphsage',model_sha256='model',protocol_sha256='protocol',configuration_sha256='config',calibration=calibrate_negatives([1.,2.],PROTOCOL)))

def load_args():return dict(organization='Org1',detector='graphsage',model_sha256='model',protocol_sha256='protocol',configuration_sha256='config')

def test_frozen_loader_round_trip_and_no_recalibration_api(tmp_path):
    p=tmp_path/'threshold.json';a=artifact();p.write_text(json.dumps(a))
    assert load_frozen_threshold(p,**load_args())==a
    with pytest.raises(TypeError):load_frozen_threshold(p,**load_args(),split='TEST',labels=[0])

@pytest.mark.parametrize('field',['organization','detector','model_sha256','protocol_sha256','configuration_sha256'])
def test_frozen_loader_requires_matching_identity(tmp_path,field):
    p=tmp_path/'t.json';p.write_text(json.dumps(artifact()));kwargs=load_args();kwargs[field]='different'
    with pytest.raises(ValueError,match='identity mismatch'):load_frozen_threshold(p,**kwargs)

def test_frozen_loader_rejects_tampering_and_nonval_artifact(tmp_path):
    p=tmp_path/'t.json';a=artifact();a['calibration']['achieved_fp']=99;p.write_text(json.dumps(a))
    with pytest.raises(ValueError,match='seal'):load_frozen_threshold(p,**load_args())
    a=artifact();a.pop('seal_sha256');a['calibration_split']='TEST'
    with pytest.raises(ValueError):seal_threshold(a)

def test_existing_output_prevents_recalibration_before_input_access(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'read_text',lambda *a,**k:pytest.fail('Inputs opened during overwrite attempt'))
    with pytest.raises(ValueError,match='cannot be recalibrated'):run(tmp_path)

def test_paired_cohorts_cannot_silently_change():
    a=dict(keys=[('Org1','VAL','v','t',1)],y=np.array([0]),mask=np.array([True]),unseen_user=np.array([False]),unseen_ip=np.array([False]));b=copy.deepcopy(a)
    verify_pair(a,b);b['keys'][0]=('Org1','VAL','v','t',2)
    with pytest.raises(ValueError):verify_pair(a,b)

def test_real_format_reader_preserves_logit_and_exact_grid(tmp_path):
    p=tmp_path/'validation_predictions.csv'
    with p.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(COLUMNS);w.writerow(['Org1','VAL','fixture_VAL','2020-10-06T07:00:00',1,0,True,1.0000001192092896,.5,True,False])
    data=read_val_predictions(p,PROTOCOL,'Org1')
    assert data['z'][0]==1.0000001192092896 and data['mask'].tolist()==[True]

def test_random_tied_distributions_satisfy_budget_and_boundary_certificate():
    rng=np.random.default_rng(5)
    for n in [1,99,100,101,200,999,1000]:
        for _ in range(10):
            z=rng.integers(-20,20,n).astype(float);c=calibrate_negatives(z,PROTOCOL)
            assert decisions(z,c['threshold']).sum()<=n//100
            assert c['fp_if_threshold_lowered_one_ulp']>n//100
