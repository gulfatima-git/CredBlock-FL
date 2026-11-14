import copy,json,sqlite3
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import pytest,torch
from src.phase6.readiness import load,sha
from src.phase6.local_graphsage import state_digest
from src.organization.rolling_graph_v1 import OrganizationGraphRuntime,OBSERVABLE
from src.phase6.inference_registry import LocalModelRegistry,InferenceBundle
from src.phase6.local_inference import LocalInference,adjacent
from src.phase6.inference_replay import load_stream

ROOT=Path(__file__).resolve().parents[2]
CONFIG=load(ROOT/'configs/phase6/continuous_inference_v1.json')
T=datetime(2020,10,6,7)

def pins():
    summary=load(ROOT/'reports/phase6/calibration/v1/summary.json')
    shared=['configs/phase6/split_protocol_v1.json','configs/phase6/feature_allowlist_v1.json','configs/phase6/neighbor_sampling_v1.json','configs/phase6/local_training_v1.json','configs/phase6/fpr_calibration_v1.json','src/organization/rolling_graph_v1.py','src/phase6/local_graphsage.py','src/phase6/input_pipeline.py','src/phase6/fpr_calibration.py']
    models={}
    for r in summary['thresholds']:
        if r['detector']!='graphsage':continue
        org=r['organization'];p=f'reports/phase6/calibration/v1/thresholds/{org}_graphsage.json'
        models[org]=dict(model_path=str(Path(r['model_path']).relative_to(ROOT)),model_sha256=r['model_sha256'],threshold_path=p,threshold_sha256=sha(ROOT/p))
    return dict(protocol_sha256=summary['protocol_sha256'],shared_sha256={p:sha(ROOT/p) for p in shared},models=models)

def warmup(org='Org1'):
    runtime=OrganizationGraphRuntime(org);t=T-timedelta(minutes=1)
    runtime.apply_timestamp_batch(t,[dict(zip(OBSERVABLE,[org,t,u,ip,False])) for u,ip in [(1,'a'),(2,'a'),(3,'b')]],['H0','H1','H2'])
    return runtime.graph

def event(t=T,u=1,ip='c',org='Org1'):
    return dict(zip(OBSERVABLE,[org,t,u,ip,False]))

def service(tmp_path,config=None,org='Org1'):
    torch.set_num_threads(1)
    return LocalInference(tmp_path/'private.sqlite',org,'synthetic_local_stream',LocalModelRegistry(ROOT,org,pins()),config or copy.deepcopy(CONFIG),warmup(org),source_identity={'kind':'synthetic-only'})

def reopen(tmp_path,config=None,org='Org1'):
    return LocalInference(tmp_path/'private.sqlite',org,'synthetic_local_stream',LocalModelRegistry(ROOT,org,pins()),config or copy.deepcopy(CONFIG),source_identity={'kind':'synthetic-only'})

def test_update_precedes_scoring_same_persistent_graph_and_observable_neighborhood_targets(tmp_path):
    s=service(tmp_path);identity=id(s.runtime.graph);before=state_digest(s.bundle.model.state_dict())
    s.process_batch(T,[event()],['R0'])
    assert id(s.runtime.graph)==identity and s.runtime.graph.retained.nodes[('U',1)][0]==2
    assert {r[0] for r in s.db.execute('SELECT user_id FROM scores')}=={1,2} # unchanged User 2 shares a touched User's retained IP
    assert s.adjacency==adjacent(s.runtime.graph)
    assert state_digest(s.bundle.model.state_dict())==before and all(not p.requires_grad and p.grad is None for p in s.bundle.model.parameters())
    s.close()

def test_complete_tied_batch_has_one_postupdate_decision_per_user(tmp_path):
    s=service(tmp_path);seen=[]
    original=s._predict
    def predict(view,users):
        seen.append(s.runtime.graph.retained.nodes[('U',4)][0]);return original(view,users)
    s._predict=predict
    s.process_batch(T,[event(u=4,ip='x'),event(u=4,ip='y')],['R0','R1'])
    assert seen==[2] and s.db.execute('SELECT COUNT(*) FROM scores WHERE user_id=4').fetchone()[0]==1
    with pytest.raises(ValueError):s.process_batch(T,[event(u=5)],['R2'])
    s.close()

@pytest.mark.parametrize('kind',['duplicate_token','out_of_order','cross_org','truth_column','timezone','future_split','invalid_outcome'])
def test_invalid_inputs_fail_before_graph_mutation_and_are_logged(tmp_path,kind):
    s=service(tmp_path);s.process_batch(T,[event()],['R0']);t=T+timedelta(seconds=1);row=event(t);token='R1'
    if kind=='duplicate_token':token='R0'
    elif kind=='out_of_order':t=T-timedelta(seconds=1);row=event(t)
    elif kind=='cross_org':row['organization']='Org2'
    elif kind=='truth_column':row['campaign_id']='forbidden'
    elif kind=='timezone':t=t.replace(tzinfo=timezone.utc);row=event(t)
    elif kind=='future_split':t=datetime(2020,12,1);row=event(t)
    else:row['LoginSuccessful']=None
    before=s.runtime.graph.checkpoint_bytes();digest=s.decision_digest()
    with pytest.raises(ValueError):s.process_batch(t,[row],[token])
    assert s.runtime.graph.checkpoint_bytes()==before and s.decision_digest()==digest and not s.faulted
    assert s.db.execute('SELECT COUNT(*) FROM failures').fetchone()[0]==1;s.close()

def test_ten_minute_and_seven_day_lower_bounds_expire_exactly(tmp_path):
    s=service(tmp_path);s.process_batch(T,[event()],['R0'])
    s.tick(T+timedelta(minutes=9)) # warm-up exactly ten minutes old
    assert ('U',2) not in s.runtime.graph.recent.nodes
    assert s.runtime.graph.recent.nodes[('U',1)][0]==1
    s.tick(T+timedelta(minutes=10));assert not s.runtime.graph.recent.nodes
    s.tick(T+timedelta(days=7));assert not s.runtime.graph.retained.nodes and not s.runtime.graph.retained.edges
    assert s.adjacency=={} and 'R0' not in s.runtime.graph.seen
    with pytest.raises(ValueError,match='Duplicate committed'):s.process_batch(T+timedelta(days=7,seconds=1),[event(T+timedelta(days=7,seconds=1))],['R0'])
    s.close()

def test_binary64_threshold_is_not_rounded_to_float32_and_alert_logs_are_exact(tmp_path):
    s=service(tmp_path);threshold=s.bundle.threshold['value']
    def predict(view,users):return [threshold if i==0 else np.nextafter(threshold,-np.inf) for i in range(len(users))],0.
    s._predict=predict;s.process_batch(T,[event()],['R0'])
    rows=s.db.execute('SELECT logit_hex,threshold_hex,decision,alert_id FROM scores ORDER BY user_id').fetchall()
    assert rows[0][0]==threshold.hex()==rows[0][1] and rows[0][2]=='ALERT' and rows[0][3]
    assert rows[1][2]=='NO_ALERT' and rows[1][3] is None;s.close()

def test_restart_replays_committed_journal_and_matches_uninterrupted_results(tmp_path):
    cfg=copy.deepcopy(CONFIG);cfg['persistence']['checkpoint_every_commits']=2
    s=service(tmp_path/'a',cfg)
    for i in range(3):s.process_batch(T+timedelta(seconds=i),[event(T+timedelta(seconds=i),u=4,ip='new')],[f'R{i}'])
    blob=s.runtime.graph.checkpoint_bytes();digest=s.decision_digest();s.close();s=reopen(tmp_path/'a',cfg)
    assert s.recovered_commands==1 and s.input_offset==3 and s.runtime.graph.checkpoint_bytes()==blob and s.decision_digest()==digest
    t=T+timedelta(seconds=3);s.process_batch(t,[event(t,u=4,ip='new')],['R3'])
    other=service(tmp_path/'b',cfg)
    for i in range(4):other.process_batch(T+timedelta(seconds=i),[event(T+timedelta(seconds=i),u=4,ip='new')],[f'R{i}'])
    assert other.runtime.graph.checkpoint_bytes()==s.runtime.graph.checkpoint_bytes() and other.decision_digest()==s.decision_digest()
    s.close();other.close()

def test_scoring_failure_faults_client_without_committing_partial_alerts(tmp_path):
    s=service(tmp_path)
    def fail(*args):raise RuntimeError('injected scoring failure')
    s._predict=fail
    with pytest.raises(RuntimeError):s.process_batch(T,[event()],['R0'])
    assert s.faulted and s.db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==0
    assert s.db.execute('SELECT COUNT(*) FROM scores').fetchone()[0]==0
    with pytest.raises(ValueError,match='restart'):s.process_batch(T+timedelta(seconds=1),[event(T+timedelta(seconds=1))],['R1'])
    s.close();s=reopen(tmp_path);s.process_batch(T,[event()],['R0']);assert s.input_offset==1;s.close()

def test_storage_failure_rolls_back_input_tokens_and_decisions(tmp_path):
    s=service(tmp_path);s.db.execute("CREATE TRIGGER fail_scores BEFORE INSERT ON scores BEGIN SELECT RAISE(ABORT,'injected storage failure'); END");s.db.commit()
    with pytest.raises(sqlite3.IntegrityError):s.process_batch(T,[event()],['R0'])
    assert s.faulted and all(s.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0 for table in ['commands','scores','event_tokens'])
    s.db.execute('DROP TRIGGER fail_scores');s.db.commit();s.close();s=reopen(tmp_path);s.process_batch(T,[event()],['R0']);assert s.input_offset==1;s.close()

def test_invalid_candidate_retains_last_usable_bundle(tmp_path):
    s=service(tmp_path);before=s.bundle.fingerprint;candidate=copy.deepcopy(pins());candidate['models']['Org1']['model_sha256']='bad'
    result=s.try_model_candidate(candidate)
    assert result['status']=='REJECTED_RETAINED_LAST_USABLE' and s.bundle.fingerprint==before
    s.process_batch(T,[event()],['R0']);assert s.db.execute('SELECT COUNT(*) FROM scores').fetchone()[0]>0;s.close()

@pytest.mark.parametrize('field',['model_sha256','threshold_sha256'])
def test_startup_rejects_wrong_model_or_threshold_hash(field):
    p=pins();p['models']['Org1'][field]='bad'
    with pytest.raises(ValueError):InferenceBundle(ROOT,'Org1',p)

def test_schema_order_mismatch_rejected(monkeypatch):
    from src.phase6 import inference_registry as module
    original=module.load
    def wrong(path):
        result=original(path)
        if Path(path).name=='feature_allowlist_v1.json':result['features']=list(reversed(result['features']))
        return result
    monkeypatch.setattr(module,'load',wrong)
    with pytest.raises(ValueError,match='schema/order'):InferenceBundle(ROOT,'Org1',pins())

def test_wrong_restart_stream_identity_rejected(tmp_path):
    s=service(tmp_path);s.close()
    with pytest.raises(ValueError,match='identity mismatch'):LocalInference(tmp_path/'private.sqlite','Org1','wrong_stream',LocalModelRegistry(ROOT,'Org1',pins()),CONFIG)

def test_checkpoint_tampering_rejected(tmp_path):
    s=service(tmp_path);s.db.execute('UPDATE checkpoints SET graph=?',(b'tampered',));s.db.commit();s.close()
    with pytest.raises(ValueError,match='integrity'):reopen(tmp_path)

def test_test_loader_rejected_before_any_path_access():
    class ForbiddenPins:
        @property
        def root(self):pytest.fail('TEST source path accessed')
    with pytest.raises(ValueError,match='TEST forbidden'):load_stream(ForbiddenPins(),'x_TEST','Org1',split='TEST')

def test_final_clock_flush_is_separate_from_primary_grid(tmp_path):
    s=service(tmp_path);last=T+timedelta(minutes=59,seconds=59,microseconds=999999)
    s.process_batch(T+timedelta(minutes=55),[event(T+timedelta(minutes=55),u=4)],['R0'])
    r=s.tick(last,final=True)
    assert r['trigger']=='final' and r['asof']==last.isoformat()
    assert s.db.execute('SELECT MAX(asof) FROM commands').fetchone()[0]==last.isoformat();s.close()

def test_all_five_registry_bundles_load_without_training():
    for org in CONFIG['organizations']:
        b=InferenceBundle(ROOT,org,pins());assert not b.model.training and all(not p.requires_grad for p in b.model.parameters())

def test_empty_event_batch_is_logged_without_mutation(tmp_path):
    s=service(tmp_path);before=s.runtime.graph.checkpoint_bytes()
    with pytest.raises(ValueError,match='tick'):s.process_batch(T,[],[])
    assert s.runtime.graph.checkpoint_bytes()==before and s.db.execute('SELECT COUNT(*) FROM failures').fetchone()[0]==1
    s.close()
