"""Synthetic-only checks for the additive offline evidence auditor."""
from datetime import datetime,timedelta
import pytest
from src.phase6.independent_test_validation_v1 import counts_and_ap,campaign_oracle

def test_tied_score_ap_and_confusion():
    rows=[dict(organization='Org1',variant_id='fixture',asof='fixture',user_id=i,
        detector='graphsage',node_label=y,logit_hex=float(z).hex(),alert=z>=0,
        threshold={'kind':'finite','hex':float(0).hex()})
        for i,(y,z) in enumerate([(1,1),(0,1),(1,-1),(0,-1)])]
    m=counts_and_ap(rows)
    assert (m['tp'],m['fp'],m['tn'],m['fn'])==(1,1,1,1)
    assert m['average_precision']==0.5
    with pytest.raises(ValueError,match='Duplicate'):
        counts_and_ap(rows+rows[:1])

def scenario(campaigns=('A',)):
    t=datetime(2020,1,1)
    specs=[dict(variant_id='fixture',campaign_id=c,start=t,end=t+timedelta(hours=1),
        targeted_organizations=['Org1','Org2']) for c in campaigns]
    evidence=[dict(variant_id='fixture',campaign_id=c,organization=o,user_id=1,at=t)
        for c in campaigns for o in ('Org1','Org2')]
    return t,specs,evidence

def decision(at,org='Org1'):
    return dict(variant_id='fixture',organization=org,user_id=1,at=at,
        family='local_only',alert=True)

def test_expiry_and_censoring():
    t,s,e=scenario()
    r=campaign_oracle(s,e,[decision(t+timedelta(minutes=10))])
    assert all(v['right_censored'] and v['event_time_seconds'] is None for v in r['campaigns'])

def test_anywhere_is_not_everywhere():
    t,s,e=scenario()
    r=campaign_oracle(s,e,[decision(t+timedelta(minutes=1))])
    c=next(v for v in r['campaigns'] if v['detector_family']=='local_only')
    assert c['any_organization_detected'] and not c['all_organizations_detected']
    assert c['event_time_seconds']==60
    assert c['unique_detected_target_users_summed_local']==1

def test_ambiguous_and_false_alerts_receive_no_campaign_credit():
    t,s,e=scenario(('A','B'))
    r=campaign_oracle(s,e,[decision(t+timedelta(minutes=1)),decision(t-timedelta(seconds=1),'Org2')])
    assert r['attribution']=={'AMBIGUOUS':1,'UNATTRIBUTED':1}
    assert all(v['primary_all_targeted_undetected'] for v in r['campaigns'])
