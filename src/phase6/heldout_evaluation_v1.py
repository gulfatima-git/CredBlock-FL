"""TEST-only evaluation joins, separated from label-free runtime scoring.

No CLI or final-evaluation runner is supplied in this preparation delivery.
The execution approval gate applies before every payload-reading entry point.
Unchanged accepted pure indicator and campaign evaluators remain separate
comparison/offline components; no campaign metadata enters local inference.
"""
from datetime import datetime
from pathlib import Path
from src.phase6.readiness import REPLAY, sha
from src.phase6.temporal_protocol import require, scoring_times, validate_target


def eligible_grid_rows(protocol, organization, variant_id, anchor, asof, rows):
    """Pure offline join validation, including masked rows before exclusion."""
    require(variant_id.endswith('_TEST'), 'Only TEST label identities accepted')
    require(asof in scoring_times(protocol, anchor), 'Outside frozen primary grid')
    result=[];seen=set()
    for row in rows:
        validate_target(protocol,row,organization,'TEST',asof)
        require(row['variant_id']==variant_id, 'Cross-branch label')
        require(row['User ID'] not in seen, 'Duplicate User-time label')
        seen.add(row['User ID'])
        if row['supervision_eligible']:result.append(row)
    return result


def load_grid_labels(pins, scope, variant_id, organization, anchor, asof, expected_sha256):
    """Future execution-only label reader; never called by inference or preparation."""
    scope.assert_ready()
    require(Path(pins.root).resolve()==scope.root,'Scope/root mismatch')
    scope.check_variant(variant_id,organization)
    require(asof in scoring_times(pins.protocol,anchor),'Outside frozen primary grid')
    path=scope.check_input(pins.root/REPLAY/variant_id/f'{organization}_labels.parquet',
                           variant_id,organization,labels=True)
    path=pins.check(path)
    require(sha(path)==expected_sha256,'Label identity mismatch')
    import duckdb
    db=duckdb.connect(':memory:')
    try:
        cursor=db.execute('''SELECT * FROM read_parquet(?) WHERE label_time=?
          AND contains(query_kind,'grid_snapshot') ORDER BY "User ID"''',[str(path),asof])
        columns=[d[0] for d in cursor.description]
        rows=[dict(zip(columns,r)) for r in cursor.fetchall()]
    finally:db.close()
    return eligible_grid_rows(pins.protocol,organization,variant_id,anchor,asof,rows)


def exact_grid_predictions(bundle, view, variant_id, rows, *, scope):
    """Score all eligible User roots, not only operationally affected Users.

The accepted sampler supplies the same feature transforms and root ordering.
No labels enter sampling, features or the model; they are joined afterward.
"""
    import numpy as np
    import torch
    from src.phase6.input_pipeline import TemporalNeighborSampler
    from src.phase6.fpr_calibration import decisions
    scope.assert_ready()
    scope.check_variant(variant_id,view.organization)
    require(view.organization==bundle.organization,'Nonlocal fixed-grid model')
    require(variant_id.endswith('_TEST'),'TEST namespace required')
    index={key:i for i,key in enumerate(view.private_keys)}
    users=[r['User ID'] for r in rows]
    require(len(users)==len(set(users)), 'Duplicate eligible roots')
    require(all(r['supervision_eligible'] and r['node_label'] in (0,1) for r in rows),'Ineligible evaluation row')
    require(all(('U',u) in index for u in users),'Eligible User absent from causal graph')
    sampler=TemporalNeighborSampler(view,variant_id,'TEST',tuple(bundle.sampler['fanouts_model_order']),
                                    bundle.sampler['seed'],bundle.protocol)
    # Preserve accepted cache batching of ALL observable recent Users, including
    # masked roots. Selecting eligible roots first could change matrix shapes
    # and binary32 rounding at a frozen binary64 decision boundary.
    roots=sampler.user_rows[view.x[sampler.user_rows,5]>0]
    require(set(users).issubset({view.private_keys[int(i)][1] for i in roots}),
            'Eligible User absent from accepted recent-root census')
    values=[]
    with torch.inference_mode():
        for a in range(0,len(roots),bundle.sampler['batch_size']):
            packet=sampler.sample(roots[a:a+bundle.sampler['batch_size']])
            require(not packet.supervision.eligible_mask.any(),'Inference supervision must be masked')
            if getattr(bundle,'detector','graphsage')=='tabular_mlp':
                from src.phase6.comparator_data import root_features
                values.extend(bundle.model(root_features(packet)).numpy().tolist())
            else:values.extend(bundle.model(packet).numpy().tolist())
    scores=np.asarray(values,dtype=np.float64)
    require(np.isfinite(scores).all(),'Nonfinite held-out score')
    alerts=decisions(scores,bundle.threshold)
    predictions={view.private_keys[int(i)][1]:(s,a) for i,s,a in zip(roots,scores,alerts)}
    return [dict(user_id=u,logit_hex=float(predictions[u][0]).hex(),
                 alert=bool(predictions[u][1]),node_label=r['node_label'])
            for u,r in zip(users,rows)]


def indicator_barrier(services, commands, issuers, network, at):
    """Reuse accepted zero-delay policy after ALL original local decisions.

    commands maps organizations active at this timestamp to complete loader
    frames. Inactive recipients still receive and expire indicators. Additional
    event Users remain separate from paired score rows. No assisted alert issues
    indicators. The caller persists returned private decisions organization-locally.
    """
    from src.phase6.indicator_sharing import combine
    organizations=set(network.config['organizations'])
    require(set(services)==set(issuers)==organizations,'All five local organizations required')
    require(set(commands)<=organizations,'Unknown local command')
    payloads=[];frames={}
    for org in sorted(organizations):
        service=services[org]
        service.scope.assert_ready()
        require(service.organization==org and service.split=='TEST','Wrong local TEST service')
    network.advance(at)
    for org in sorted(commands):
        service=services[org];frame=commands[org]
        if frame['observations']:
            service.process_batch(at,frame['observations'],frame['tokens'],
                                  heartbeat=frame['heartbeat'],final=frame['final'])
        else:service.tick(at,final=frame['final'])
        scores=[dict(zip(('user_id','decision','alert_id'),r)) for r in service.db.execute(
            'SELECT user_id,decision,alert_id FROM scores WHERE seq=? ORDER BY user_id',(service.seq,))]
        payloads.extend(issuers[org].attribute(at,service.runtime.graph,
                        [r for r in scores if r['decision']=='ALERT']))
        current={}
        for row in frame['observations']:current.setdefault(row['User ID'],set()).add(row['IP Address'])
        frames[org]=(scores,current)
    network.publish(payloads,at)
    output={}
    for org,(scores,current) in sorted(frames.items()):
        paired=[];additional=[];scored={r['user_id'] for r in scores}
        for row in scores:
            local=row['decision']=='ALERT'
            combined,hits=combine(local,current.get(row['user_id'],set()),network.recipients[org],at)
            paired.append(dict(user_id=row['user_id'],local_alert=local,
                               local_plus_indicator_alert=combined,indicator_ids=hits))
        for user in sorted(set(current)-scored):
            combined,hits=combine(False,current[user],network.recipients[org],at)
            additional.append(dict(user_id=user,local_status='NOT_SCORED',
                                    local_plus_indicator_alert=combined,indicator_ids=hits))
        output[org]=dict(paired=paired,additional_event_users=additional)
    return output


def evaluate_test_campaigns(scope, specifications, evidence, decisions, complete_coverage, protocol):
    """Offline-only binding to the unchanged, split-neutral accepted evaluator."""
    from src.phase6.detectability import evaluate_campaigns
    from src.phase6.temporal_protocol import bounds
    scope.assert_ready()
    lo,hi=bounds(protocol,'TEST')
    for spec in specifications:
        scope.check_variant(spec['variant_id'],spec['targeted_organizations'][0])
        require(lo<=spec['start']<spec['end']<=hi,'Campaign outside frozen TEST interval')
    require(all(e['variant_id'].endswith('_TEST') for e in evidence),'Other-split campaign evidence')
    require(all(d['variant_id'].endswith('_TEST') for d in decisions),'Other-split decisions')
    return evaluate_campaigns(specifications,evidence,decisions,complete_coverage)
