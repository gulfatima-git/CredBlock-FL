import json,csv
from pathlib import Path
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');BASE=ROOT/'reports/phase6/detectability';AUD=BASE/'technical_review_v2/continuation_00004';FIN=BASE/'technical_review_v2/final_v1'
HERE=Path(__file__).parent/'excel_all_phases_v1'
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def csvrows(p):
 with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def value(x):
 if x in [None,'']:return None
 if x in ['True','False']:return x=='True'
 try:return int(x)
 except (TypeError,ValueError):
  try:return float(x)
  except (TypeError,ValueError):return x
def tab(name,path,keys,labels=None):
 rs=csvrows(path);return dict(name=name,source=str(path),headers=labels or keys,rows=[[value(r[k]) for k in keys] for r in rs])
s=load(FIN/'summary.json');assert s['status']=='PASS' and not s['user_accepted']
tabs=[tab('Campaigns',AUD/'campaign_results.csv',['variant_id','family','seed','RIP_target','Raccount_target','Sorg_target','detector_family','evaluable','any_organization_detected','all_organizations_detected','partially_detected','primary_all_targeted_undetected','targeted_organization_count','detected_organizations','unique_exposed_target_users_summed_local','unique_detected_target_users_summed_local','event_time_seconds','right_censored','censor_time_seconds','global_onset','observation_end_exclusive']),
tab('Organizations',AUD/'organization_results.csv',['variant_id','organization','detector_family','family','seed','RIP_target','Raccount_target','Sorg_target','complete_coverage','status','unique_exposed_target_users','unique_detected_target_users','qualifying_alert_rows','detected','right_censored','event_time_seconds','censor_time_seconds','raw_alert_rows','raw_unique_alerted_users','operational_score_rows']),
tab('Factors',FIN/'factor_results.csv',['detector_family','design_family','factor','level','campaigns','detected_campaigns','undetected_campaigns','undetected_percent','all_targeted_organizations_detected','organization_trials','detected_organization_trials','exposed_user_occurrences','detected_user_occurrences','detected_user_percent']),
tab('Operational',AUD/'operational_results.csv',['variant_id','organization','events','scoring_decisions','local_alerts','combined_alerts','additional_alerts','indicators_issued','indicators_received','unique_indicators_used','event_only_unscored_rows','final_ten_minutes_events','final_ten_minutes_scores'])]
side=load(AUD/'sqlite_sidecar_inventory_after.json');tabs.append(dict(name='Sidecars',source=str(AUD/'sqlite_sidecar_inventory_after.json'),headers=['Path','Database','Kind','Bytes','SHA256','Role'],rows=[[r[k] for k in ['path','database','kind','bytes','sha256','classification']] for r in side]))
with (HERE/'subphase8_review_inputs.json').open('x',encoding='utf-8') as f:json.dump(dict(summary=s,tabs=tabs),f)
print('Prepared verified workbook inputs')
