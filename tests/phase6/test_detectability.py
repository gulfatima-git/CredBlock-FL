from datetime import datetime,timedelta
import copy,pytest
from src.phase6.detectability import evaluate_campaigns,FAMILIES

T=datetime(2020,10,6,7)
def spec(c='c',variant='v',orgs=('Org1','Org2'),start=T,end=None):
 return dict(variant_id=variant,campaign_id=c,start=start,end=end or T+timedelta(hours=1),targeted_organizations=list(orgs),seed=1001,factors=dict(family='fixture',RIP_target=.2,Raccount_target=.2,Sorg_target=len(orgs)))
def ev(u=1,seconds=0,org='Org1',c='c',variant='v'):
 return dict(variant_id=variant,campaign_id=c,organization=org,user_id=u,at=T+timedelta(seconds=seconds))
def decision(seconds=0,u=1,org='Org1',family='local_only',alert=True,variant='v'):
 return dict(variant_id=variant,organization=org,user_id=u,at=T+timedelta(seconds=seconds),family=family,alert=alert)
def coverage(orgs=('Org1','Org2'),variant='v'):
 return {(variant,o,f):True for o in orgs for f in FAMILIES}
def campaign(r,f='local_only',c='c'):return next(x for x in r['campaign_results'] if x['detector_family']==f and x['campaign_id']==c)
def run(ds,evidence=None,specs=None,cov=None):
 return evaluate_campaigns(specs or [spec()],evidence or [ev(),ev(org='Org2')],ds,coverage() if cov is None else cov)

def test_exact_actual_onset_qualifies_and_planned_pre_onset_does_not():
 r=run([decision(59),decision(60)],evidence=[ev(seconds=60),ev(seconds=60,org='Org2')])
 c=campaign(r);assert c['event_time_seconds']==0 and c['any_organization_detected'] and c['detected_organizations']==1
 assert [x['status'] for x in r['private_alert_attribution']]==['UNATTRIBUTED','UNIQUE']

@pytest.mark.parametrize('seconds,qualifies',[(599,True),(600,False),(601,False)])
def test_exact_trailing_evidence_expiration(seconds,qualifies):
 assert campaign(run([decision(seconds)]))['any_organization_detected']==qualifies

def test_delayed_alert_after_last_attempt_qualifies_inside_recent_window():
 assert campaign(run([decision(300)]))['event_time_seconds']==300

def test_alert_at_exclusive_end_or_after_is_not_a_detection():
 assert campaign(run([decision(3600),decision(3601)]))['primary_all_targeted_undetected'] is True

def test_all_targeted_rule_distinguishes_one_missed_org_from_campaign_undetection():
 r=run([decision()]);c=campaign(r)
 assert not c['primary_all_targeted_undetected'] and c['partially_detected'] and not c['all_organizations_detected']
 assert next(x for x in r['organization_results'] if x['organization']=='Org2' and x['detector_family']=='local_only')['status']=='UNDETECTED_WITHIN_HORIZON'

def test_all_orgs_detected_and_no_orgs_detected_are_separate():
 assert campaign(run([decision(),decision(org='Org2')]))['all_organizations_detected']
 c=campaign(run([]));assert c['primary_all_targeted_undetected'] is True and c['event_time_seconds'] is None and c['right_censored'] and c['censor_time_seconds']==3600

def test_false_alert_on_other_user_or_other_org_does_not_get_credit():
 c=campaign(run([decision(u=999),decision(org='Org3')]))
 assert c['primary_all_targeted_undetected'] is True

def test_families_are_not_pooled_and_indicator_result_can_differ():
 r=run([decision(family='local_plus_indicator')]);assert campaign(r)['primary_all_targeted_undetected'] and campaign(r,'local_plus_indicator')['any_organization_detected']

def test_repeated_alert_rows_and_unique_target_users_are_different_units():
 r=run([decision(i) for i in [0,1,2]],evidence=[ev(),ev(u=2),ev(org='Org2')])
 x=next(x for x in r['organization_results'] if x['organization']=='Org1' and x['detector_family']=='local_only')
 assert x['qualifying_alert_rows']==3 and x['unique_exposed_target_users']==2 and x['unique_detected_target_users']==1

def test_same_numeric_user_id_in_other_org_does_not_cross_attribute():
 r=run([decision(org='Org2')],evidence=[ev(),ev(u=2,org='Org2')]);assert campaign(r)['primary_all_targeted_undetected'] is True

def test_overlapping_campaign_same_user_is_ambiguous_not_double_credited():
 r=run([decision(100)],evidence=[ev(),ev(c='other',seconds=50),ev(org='Org2'),ev(c='other',seconds=50,org='Org2')],specs=[spec(),spec('other')])
 assert all(c['primary_all_targeted_undetected'] for c in r['campaign_results'])
 assert r['private_alert_attribution'][0]['status']=='AMBIGUOUS'

def test_overlapping_windows_different_users_keep_unique_attribution():
 r=run([decision(100)],evidence=[ev(),ev(c='other',u=2),ev(org='Org2'),ev(c='other',u=2,org='Org2')],specs=[spec(),spec('other')])
 assert campaign(r)['any_organization_detected'] and campaign(r,c='other')['primary_all_targeted_undetected']

def test_same_user_same_time_other_variant_is_not_joined():
 s=[spec(),spec(variant='other')];e=[ev(),ev(org='Org2'),ev(variant='other'),ev(variant='other',org='Org2')]
 cov={**coverage(),**coverage(variant='other')};r=run([decision()],evidence=e,specs=s,cov=cov)
 assert next(c for c in r['campaign_results'] if c['variant_id']=='other' and c['detector_family']=='local_only')['primary_all_targeted_undetected']

def test_missing_org_or_family_coverage_is_pending_never_undetected():
 cov=coverage();del cov[('v','Org2','local_only')];c=campaign(run([],cov=cov))
 assert not c['evaluable'] and c['primary_all_targeted_undetected'] is None
 r=run([decision()],cov={});assert all(c['status']=='NOT_EVALUABLE' for c in r['campaign_results'])

def test_no_exposure_not_called_undetected():
 r=evaluate_campaigns([spec()],[],[],coverage());assert all(c['status']=='NOT_EVALUABLE' and c['global_onset'] is None for c in r['campaign_results'])

def test_org_delayed_exposure_uses_global_and_local_time_origins_separately():
 r=run([decision(301,org='Org2')],evidence=[ev(),ev(seconds=300,org='Org2')])
 x=next(x for x in r['organization_results'] if x['organization']=='Org2' and x['detector_family']=='local_only')
 assert x['event_time_seconds']==301 and x['local_exposure_delay_seconds']==1

def test_duplicate_user_time_decisions_rejected():
 with pytest.raises(ValueError,match='Duplicate operational'):run([decision(),decision()])

def test_future_evidence_cannot_credit_earlier_alert():
 assert campaign(run([decision(1)],evidence=[ev(seconds=2),ev(seconds=2,org='Org2')]))['primary_all_targeted_undetected']

def test_inputs_not_mutated_and_order_reproducible():
 s=[spec()];e=[ev(),ev(org='Org2')];d=[decision(1),decision(2,org='Org2')];before=copy.deepcopy((s,e,d))
 a=evaluate_campaigns(s,e,d,coverage());b=evaluate_campaigns(list(reversed(s)),list(reversed(e)),list(reversed(d)),coverage())
 assert a==b and (s,e,d)==before

@pytest.mark.parametrize('kind',['unknown_campaign','wrong_org','outside_window'])
def test_invalid_truth_join_fails_closed(kind):
 e=ev()
 if kind=='unknown_campaign':e['campaign_id']='unknown'
 elif kind=='wrong_org':e['organization']='Org5'
 else:e['at']=T+timedelta(hours=1)
 with pytest.raises(ValueError):run([],evidence=[e])

@pytest.mark.parametrize('variant',['x_TEST','../x_VAL','x/other_VAL','x\\other_VAL'])
def test_test_or_traversal_variant_rejected_before_dataset_access(variant):
 from src.phase6.run_detectability import eligible_variant
 with pytest.raises(ValueError,match='TEST forbidden'):eligible_variant(variant)
