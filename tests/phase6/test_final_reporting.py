import ast,csv,json,math
from pathlib import Path
import numpy as np
import pytest
from src.phase6.final_reporting import guard_split,read_predictions,ranking,confusion,aggregate_metrics,run,save

def th(x):return dict(kind='finite',value=float(x),hex=float(x).hex())
@pytest.mark.parametrize('split',['TEST','test','','TRAINING',None])
def test_forbidden_before_io(monkeypatch,split):
    monkeypatch.setattr(Path,'open',lambda *a,**k:pytest.fail('I/O before split rejection'))
    with pytest.raises(ValueError,match='before I/O'):read_predictions('missing',split,'Org1')
@pytest.mark.parametrize('split',['TRAIN','VAL'])
def test_allowed(split):guard_split(split)
def test_runner_test_before_config_io(monkeypatch):
    monkeypatch.setattr(Path,'open',lambda *a,**k:pytest.fail('Configuration read before TEST rejection'))
    with pytest.raises(ValueError):run('missing','missing','missing',['TEST'])
def test_test_named_path_before_open(monkeypatch):
    monkeypatch.setattr(Path,'open',lambda *a,**k:pytest.fail('TEST path opened'))
    with pytest.raises(ValueError,match='path'):read_predictions('x_TEST.csv','VAL','Org1')
def test_tied_grouped_ap():
    r=ranking([1,0,1,0],[2,2,1,0]);assert r['average_precision']==pytest.approx((.5+2/3)/2)
def test_tied_auc():assert ranking([1,0],[1,1])['roc_auc']==.5
@pytest.mark.parametrize('y,ap', [([0,0],None),([1,1],1.)])
def test_ranking_single_class(y,ap):
    r=ranking(y,[0,1]);assert r['average_precision']==ap;assert r['roc_auc'] is None
def test_empty_ranking():assert ranking([],[])==dict(average_precision=None,roc_auc=None,bce=None,curve=[])
def test_nonfinite_ranking():
    with pytest.raises(ValueError):ranking([1],[np.inf])
def test_binary64_boundary():
    score=np.array([4.],dtype=np.float32);threshold=th(np.nextafter(np.float64(4),np.inf));r=confusion([0],score,[True],threshold);assert r['fp']==0 and r['tn']==1
def test_mask_and_population_separated():
    r=confusion([1,-1,0,-1],[2,3,-2,3],[True,False,True,False],th(0),[True,True,False,False]);assert r['eligible']==1 and r['original_masked_inside_population']==1 and r['outside_population']==2
def test_mask_mismatch():
    with pytest.raises(ValueError):confusion([-1],[1],[True],th(0))
def test_undefined_not_zero():
    r=confusion([0],[-1],[True],th(0));assert r['precision'] is None and r['recall'] is None and r['fpr']==0
def test_all_masked_undefined():
    r=confusion([-1],[5],[False],th(0));assert r['eligible']==0 and r['f1'] is None and r['fpr'] is None
def test_macro_preserves_undefined():
    rows=[]
    for split in ['TRAIN','VAL']:
        for det in ['graphsage','tabular_mlp']:
            for i in range(1,6):
                r=dict(organization='Org'+str(i),split=split,detector=det,**confusion([1,0],[1,-1],[True,True],th(0)),average_precision=1.,roc_auc=1.,bce=.3);r['precision']=None if i==1 else 1.;rows.append(r)
    result=aggregate_metrics(rows);assert result[0]['precision'] is None and result[0]['undefined_organizations']['precision']==['Org1'];assert result[1]['tp']==5
def test_missing_organization():
    with pytest.raises(ValueError):aggregate_metrics([])
def test_existing_json_no_overwrite(tmp_path):
    p=tmp_path/'original.json';p.write_text('original')
    with pytest.raises(FileExistsError):save(p,{})
    assert p.read_text()=='original'
def test_no_execution_imports_or_calls():
    path=Path(__file__).resolve().parents[2]/'src/phase6/final_reporting.py';tree=ast.parse(path.read_text())
    imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any(any(x in (m or '') for x in ['training','graphsage','detectability_batch','inference']) for m in imports)
    forbidden={'calibrate_negatives','trial','evaluate_campaigns','replay','forward','backward'}
    assert not any(isinstance(n,ast.Call) and ((isinstance(n.func,ast.Name) and n.func.id in forbidden) or (isinstance(n.func,ast.Attribute) and n.func.attr in forbidden)) for n in ast.walk(tree))
def test_alignment_has_exact_four_and_six():
    root=Path(__file__).resolve().parents[2];a=json.loads((root/'reports/phase6/final/v1/research_alignment.json').read_text())
    assert [r['id'] for r in a['rows']]==['RQ1','RQ2','RQ3','RQ4','C1','C2','C3','C4','C5','C6']
    required={'original','designed','implemented','evidence','unsupported','subsequent_phases','paper_can_claim','paper_cannot_claim'}
    assert all(required<=r.keys() and all(r[k] for k in required) for r in a['rows'])
def test_protocol_and_no_stage_c():
    root=Path(__file__).resolve().parents[2];c=json.loads((root/'configs/phase6/final_reporting_v1.json').read_text());assert c['allowed_splits']==['TRAIN','VAL'] and not c['stage_c_implemented'] and not c['test_access']
