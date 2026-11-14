"""Synthetic mechanics tests; benign/malicious fixture meaning never enters runtime."""
import copy,json
from pathlib import Path
from datetime import datetime,timedelta,timezone
import pytest
from src.phase6.indicator_sharing import Indicator,Issuer,Recipient,Network,combine,WIRE,canonical
from src.organization.rolling_graph_v1 import OrganizationGraphRuntime,OBSERVABLE

ROOT=Path(__file__).resolve().parents[2]
C=json.loads((ROOT/'configs/phase6/indicator_sharing_v1.json').read_text())
T=datetime(2020,10,6,7)
IP='192.0.2.1';OTHER='198.51.100.2'

def graph(org='Org1',time=T,records=None):
    r=OrganizationGraphRuntime(org)
    records=records or [(1,IP),(2,IP),(3,OTHER)]
    r.apply_timestamp_batch(time,[dict(zip(OBSERVABLE,[org,time,u,ip,False])) for u,ip in records],[f'local{i}' for i in range(len(records))])
    return r.graph

def alert(user=1,reference='private-alert'):
    return dict(user_id=user,alert_id=reference,decision='ALERT')

def net():
    receivers={o:Recipient(o,C) for o in C['organizations']};return Network(C,receivers),receivers

def test_wire_allowlist_no_local_identity_or_source_alert_reference():
    issuer=Issuer('Org1',C);values=issuer.attribute(T,graph(),[alert()])
    assert len(values)==1 and set(values[0])==WIRE and values[0]['status']=='suspicious_unverified'
    assert 'private-alert' not in canonical(values) and 'user_id' not in canonical(values)
    assert issuer.provenance[0]['source_alert_id']=='private-alert' and issuer.provenance[0]['user_id']==1

def test_only_alerted_user_observed_recent_ips_are_attributed_all_outcomes():
    g=graph(records=[(1,IP),(1,OTHER),(2,'203.0.113.5')]);issuer=Issuer('Org1',C)
    assert [r['ip'] for r in issuer.attribute(T,g,[alert()])]==sorted([IP,OTHER])

def test_no_recent_evidence_does_not_invent_an_indicator():
    issuer=Issuer('Org1',C);assert issuer.attribute(T,graph(),[alert(99)])==[] and issuer.without_evidence==1

def test_recent_boundary_excludes_exactly_ten_minutes_old_evidence():
    g=graph(time=T-timedelta(minutes=10));g.advance(T)
    assert Issuer('Org1',C).attribute(T,g,[alert()])==[]

def test_future_or_nonlocal_graph_rejected():
    with pytest.raises(ValueError):Issuer('Org1',C).attribute(T,graph(time=T+timedelta(seconds=1)),[alert()])
    with pytest.raises(ValueError):Issuer('Org1',C).attribute(T,graph('Org2'),[alert()])

@pytest.mark.parametrize('row',[dict(user_id=1,alert_id='x',decision='NO_ALERT'),dict(user_id=1,alert_id=None,decision='ALERT'),dict(user_id=1,alert_id='x',decision='ALERT',campaign_id='forbidden')])
def test_non_alert_or_truth_fields_not_accepted_as_alert_evidence(row):
    with pytest.raises(ValueError):Issuer('Org1',C).attribute(T,graph(),[row])

def test_zero_delay_all_other_orgs_receive_same_timestamp_no_self_delivery():
    network,receivers=net();p=Indicator.create(C,'Org1',IP,T).payload();network.publish([p],T)
    assert not receivers['Org1'].records
    for org in C['organizations'][1:]:
        assert receivers[org].match({IP},T)==[p['indicator_id']]
        assert receivers[org].log[0]['at']==T.isoformat()
    assert network.log[1]['simulated_delay_seconds']==0 and len(network.log[1]['receivers'])==4

def test_tied_local_alert_publication_and_decisions_independent_of_org_order():
    def run(order):
        n,rs=net();payloads=[]
        for org in order:payloads+=Issuer(org,C).attribute(T,graph(org),[alert()])
        n.publish(payloads,T)
        return n.log,{o:combine(False,{IP},r,T) for o,r in rs.items()}
    assert run(C['organizations'])==run(list(reversed(C['organizations'])))

def test_cannot_utilize_future_indicator_or_rewrite_past_decision():
    n,r=net();old=combine(False,{IP},r['Org2'],T)
    n.publish([Indicator.create(C,'Org1',IP,T+timedelta(seconds=1)).payload()],T+timedelta(seconds=1))
    assert old==(False,[]) and combine(False,{IP},r['Org2'],T+timedelta(seconds=1))[0]
    with pytest.raises(ValueError):r['Org2'].match({IP},T)

@pytest.mark.parametrize('seconds',[1,-1])
def test_backdated_and_future_publication_rejected_before_delivery(seconds):
    n,r=net();p=Indicator.create(C,'Org1',IP,T+timedelta(seconds=seconds)).payload()
    with pytest.raises(ValueError):n.publish([p],T)
    assert not n.created and all(not x.records for x in r.values())

def test_matching_requires_current_authentication_not_old_recent_history():
    n,r=net();n.publish([Indicator.create(C,'Org1',IP,T).payload()],T)
    assert combine(False,set(),r['Org2'],T)==(False,[])
    assert combine(True,set(),r['Org2'],T)==(True,[])
    assert combine(False,{IP},r['Org2'],T)[0]

def test_duplicate_publication_and_receipt_idempotent():
    n,r=net();p=Indicator.create(C,'Org1',IP,T).payload();n.publish([p,p],T)
    assert len(n.created)==1 and len(r['Org2'].records)==1
    assert r['Org2'].receive(p,T) is False
    assert len(r['Org2'].match({IP},T))==1

def test_repeated_alerts_do_not_extend_live_indicator_ttl():
    issuer=Issuer('Org1',C);g=graph();first=issuer.attribute(T,g,[alert()])[0]
    g.advance(T+timedelta(minutes=1));assert issuer.attribute(g.clock,g,[alert()])==[]
    assert issuer.suppressed==1 and issuer.until[IP]==T+timedelta(minutes=10)
    g.ingest_batch(T+timedelta(minutes=10),[dict(zip(OBSERVABLE,['Org1',T+timedelta(minutes=10),1,IP,True]))],['new'])
    fresh=issuer.attribute(g.clock,g,[alert()])[0]
    assert fresh['indicator_id']!=first['indicator_id'] and fresh['expires_at']==(T+timedelta(minutes=20)).isoformat()

def test_same_ip_different_issuers_independent_episodes():
    n,r=net();n.publish([Indicator.create(C,o,IP,T).payload() for o in ['Org1','Org2']],T)
    assert len(r['Org3'].match({IP},T))==2 and len(r['Org1'].match({IP},T))==1

def test_exact_expiry_is_exclusive_and_all_recipients_expire_without_new_events():
    n,r=net();n.publish([Indicator.create(C,'Org1',IP,T).payload()],T)
    assert combine(False,{IP},r['Org2'],T+timedelta(minutes=10,microseconds=-1))[0]
    n.advance(T+timedelta(minutes=10));assert not combine(False,{IP},r['Org2'],T+timedelta(minutes=10))[0]
    assert len(n.expired)==1 and all(len(r[o].expired)==1 for o in C['organizations'][1:])

def test_ip_rotation_unflagged_address_has_no_inherited_match():
    n,r=net();n.publish([Indicator.create(C,'Org1',IP,T).payload()],T)
    assert not combine(False,{OTHER},r['Org2'],T)[0]
    n.publish([Indicator.create(C,'Org1',OTHER,T+timedelta(seconds=1)).payload()],T+timedelta(seconds=1))
    assert combine(False,{OTHER},r['Org2'],T+timedelta(seconds=1))[0]

def test_false_alert_shared_benign_ip_propagates_suspicion_not_malicious_truth():
    # IP is defined as benign in this fixture only; runtime receives no truth field.
    n,r=net();p=Issuer('Org1',C).attribute(T,graph(),[alert()]);n.publish(p,T)
    assert combine(False,{IP},r['Org2'],T)[0] and p[0]['status']=='suspicious_unverified'
    assert not Issuer('Org2',C).attribute(T,graph('Org2'),[]) # indicator-only alerts do not seed a cascade

def test_no_initial_local_alert_means_no_indicators_no_assisted_alert():
    n,r=net()
    for org in C['organizations']:n.publish(Issuer(org,C).attribute(T,graph(org),[]),T)
    assert not n.created and all(combine(False,{IP},v,T)==(False,[]) for v in r.values())

@pytest.mark.parametrize('field',['user_id','source_alert_id','campaign_id','synthetic_credential_id','features','graph','Login Timestamp'])
def test_private_and_oracle_wire_fields_rejected(field):
    p=Indicator.create(C,'Org1',IP,T).payload();p[field]='forbidden';n,r=net()
    with pytest.raises(ValueError):n.publish([p],T)
    assert not n.created and not r['Org2'].records

@pytest.mark.parametrize('field',['indicator_id','expires_at','available_at','status','policy_version'])
def test_tampered_identity_lifetime_or_policy_rejected(field):
    p=Indicator.create(C,'Org1',IP,T).payload();p[field]='wrong'
    with pytest.raises(ValueError):Indicator.parse(C,p)

def test_aware_times_and_nonlocal_self_receipt_rejected():
    with pytest.raises(ValueError):Indicator.create(C,'Org1',IP,T.replace(tzinfo=timezone.utc))
    r=Recipient('Org1',C)
    with pytest.raises(ValueError):r.receive(Indicator.create(C,'Org1',IP,T).payload(),T)

def test_conflicting_duplicate_id_fails_validation():
    n,r=net();p=Indicator.create(C,'Org1',IP,T).payload();n.publish([p],T);bad=copy.deepcopy(p);bad['ip']=OTHER
    with pytest.raises(ValueError):n.publish([bad],T)
    assert len(n.created)==1 and len(r['Org2'].records)==1

def test_primary_protocol_and_accepted_local_sources_unchanged():
    import hashlib
    pins=json.loads((ROOT/'reports/phase6/inference/preregistration_v1.json').read_text())
    for p,h in pins['source_sha256'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h
    assert hashlib.sha256((ROOT/'configs/phase6/split_protocol_v1.json').read_bytes()).hexdigest()==C['protocol_sha256']

def test_policy_explicitly_separates_additional_users_and_disallows_test():
    assert C['split']=='VAL' and 'NOT_SCORED' in C['additional_event_users']
    assert 'No cascade' in C['timestamp_barrier'] and '1%' in C['evaluation']
