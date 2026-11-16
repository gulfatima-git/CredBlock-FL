"""Offline-only campaign evaluator. Never imported by local inference/indicators."""
from collections import defaultdict
from datetime import datetime,timedelta
from bisect import bisect_right
from src.phase6.temporal_protocol import require

FAMILIES=('local_only','local_plus_indicator')

def evaluate_campaigns(specifications,evidence,decisions,complete_coverage):
    """Pure operational evaluation. Truth inputs and private IDs remain evaluator-side."""
    specs={};events=defaultdict(list);exposed=defaultdict(set);onsets={};local_onsets={};user_onsets={}
    for source in specifications:
        s=dict(source);key=(s['variant_id'],s['campaign_id'])
        require(key not in specs and s['start']<s['end'],'Duplicate/invalid campaign interval')
        require(s['targeted_organizations'] and len(set(s['targeted_organizations']))==len(s['targeted_organizations']),'Missing/duplicate targeted organizations')
        require(s['start'].tzinfo is None and s['end'].tzinfo is None,'Expected naive source campaign times');specs[key]=s
    for e in evidence:
        key=(e['variant_id'],e['campaign_id']);require(key in specs,'Unknown campaign evidence')
        s=specs[key];org=e['organization'];u=e['user_id'];t=e['at']
        require(type(u)is int and org in s['targeted_organizations'] and s['start']<=t<s['end'],'Nonlocal/out-of-horizon targeting evidence')
        account=(key[0],org,u);events[account].append((t,key));exposed[(key,org)].add(u)
        onsets[key]=min(onsets.get(key,t),t);local_onsets[(key,org)]=min(local_onsets.get((key,org),t),t);user_onsets[(key,org,u)]=min(user_onsets.get((key,org,u),t),t)
    times={}
    for key,values in events.items():values.sort();times[key]=[x[0] for x in values]
    first={};qualifying=defaultdict(int);raw=defaultdict(lambda:dict(score_rows=0,raw_alert_rows=0,raw_alert_users=set()));private=[];seen=set()
    for d in sorted(decisions,key=lambda d:(d['variant_id'],d['at'],d['organization'],d['user_id'],d['family'])):
        variant,org,u,t,family,alert=(d[k] for k in ['variant_id','organization','user_id','at','family','alert'])
        require(family in FAMILIES and type(alert)is bool and type(u)is int and t.tzinfo is None,'Invalid operational decision')
        require(any(k[0]==variant for k in specs),'Decision from another branch')
        unique=(variant,org,u,t,family);require(unique not in seen,'Duplicate operational User-time decision');seen.add(unique)
        r=raw[(variant,org,family)];r['score_rows']+=1
        if not alert:continue
        r['raw_alert_rows']+=1;r['raw_alert_users'].add(u)
        account=(variant,org,u);values=events.get(account,[]);ts=times.get(account,[])
        lower=bisect_right(ts,t-timedelta(minutes=10));upper=bisect_right(ts,t)
        candidates=sorted({key for _,key in values[lower:upper] if onsets[key]<=t<specs[key]['end']})
        credit=candidates[0] if len(candidates)==1 else None
        private.append(dict(variant_id=variant,organization=org,user_id=u,at=t.isoformat(),family=family,status='UNIQUE' if credit else 'AMBIGUOUS' if candidates else 'UNATTRIBUTED',candidate_campaign_ids=[k[1] for k in candidates]))
        if credit:
            q=(credit,org,family);qualifying[q]+=1;user=(credit,org,u,family);first[user]=min(first.get(user,t),t)
    organizations=[];campaigns=[];users=[]
    for key,s in sorted(specs.items()):
        onset=onsets.get(key)
        for family in FAMILIES:
            org_rows=[]
            for org in s['targeted_organizations']:
                targets=sorted(exposed[(key,org)]);found=[first[(key,org,u,family)] for u in targets if (key,org,u,family) in first]
                detection=min(found) if found else None;complete=bool(complete_coverage.get((key[0],org,family),False));evaluable=complete and bool(targets) and onset is not None
                r=raw[(key[0],org,family)]
                row=dict(variant_id=key[0],campaign_id=key[1],organization=org,detector_family=family,**s['factors'],seed=s['seed'],
                    complete_coverage=complete,evaluable=evaluable,status='DETECTED' if evaluable and detection else 'UNDETECTED_WITHIN_HORIZON' if evaluable else 'INCOMPLETE' if not complete else 'NO_EXPOSURE',
                    global_onset=onset.isoformat() if onset else None,local_exposure_onset=local_onsets[(key,org)].isoformat() if targets else None,observation_end_exclusive=s['end'].isoformat(),
                    operational_score_rows=r['score_rows'],raw_alert_rows=r['raw_alert_rows'],raw_unique_alerted_users=len(r['raw_alert_users']),qualifying_alert_rows=qualifying[(key,org,family)],
                    unique_exposed_target_users=len(targets),unique_detected_target_users=len(found),detected=detection is not None,first_qualifying_alert=detection.isoformat() if detection else None,
                    event_time_seconds=(detection-onset).total_seconds() if detection else None,local_exposure_delay_seconds=(detection-local_onsets[(key,org)]).total_seconds() if detection else None,
                    right_censored=detection is None,censor_time_seconds=(s['end']-onset).total_seconds() if onset else None)
                organizations.append(row);org_rows.append(row)
                for u in targets:
                    when=first.get((key,org,u,family));start=user_onsets[(key,org,u)]
                    users.append(dict(variant_id=key[0],campaign_id=key[1],organization=org,user_id=u,family=family,first_exposure=start.isoformat(),first_detection=when.isoformat() if when else None,event_time_seconds=(when-start).total_seconds() if when else None,right_censored=when is None))
            evaluable=all(r['evaluable'] for r in org_rows);detected=sum(r['detected'] for r in org_rows);first_detection=min((datetime.fromisoformat(r['first_qualifying_alert']) for r in org_rows if r['detected']),default=None)
            campaigns.append(dict(variant_id=key[0],campaign_id=key[1],detector_family=family,**s['factors'],seed=s['seed'],targeted_organization_count=len(org_rows),evaluable=evaluable,
                detected_organizations=detected,any_organization_detected=bool(detected),all_organizations_detected=detected==len(org_rows),partially_detected=0<detected<len(org_rows),
                primary_all_targeted_undetected=(detected==0) if evaluable else None,status='DETECTED' if evaluable and detected else 'UNDETECTED_ALL_TARGETED_ORGANIZATIONS' if evaluable else 'NOT_EVALUABLE',
                global_onset=onset.isoformat() if onset else None,observation_end_exclusive=s['end'].isoformat(),event_time_seconds=(first_detection-onset).total_seconds() if first_detection else None,
                right_censored=first_detection is None,censor_time_seconds=(s['end']-onset).total_seconds() if onset else None,
                unique_exposed_target_users_summed_local=sum(r['unique_exposed_target_users'] for r in org_rows),unique_detected_target_users_summed_local=sum(r['unique_detected_target_users'] for r in org_rows)))
    return dict(organization_results=organizations,campaign_results=campaigns,private_user_results=users,private_alert_attribution=private)
