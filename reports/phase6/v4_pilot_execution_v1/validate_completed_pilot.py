"""After successful process exit only: verify exact prefix and independently audit one campaign.
No GNN execution, original database connection, repair, retry or evaluator launch.
"""
from pathlib import Path
from datetime import datetime
import json,hashlib,sqlite3,math,sys,msvcrt
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
def read(p):return json.loads(Path(p).read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,d):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(d,f,indent=2);f.write('\n')
def main():
    execution=read(OUT/'execution_result.json');assert execution['returncode']==0,'Failed evaluator; do not validate as complete'
    cfg=read(OUT/'launch_preflight.json');run=Path(cfg['output_root']);cert=read(cfg['certificate_path']);body=cert['body'];variant=body['origin']['variant'];target=run/variant
    grant=read(cfg['approval_path']);assert grant['authorized_variants']==[variant] and grant['maximum_newly_completed_campaign_instances']==1
    assert {p.name for p in run.iterdir() if p.is_dir() and p.name.endswith('_TEST')}=={variant},'Unauthorized campaign output'
    result=json.loads((OUT/'evaluator_stdout.log').read_text().strip())
    assert result['status']=='BOUNDED_EXECUTION_COMPLETE_FULL_RUN_PENDING' and result['completed']==6 and result['pending']==165
    completion=read(target/'completion.json');assert completion['status']=='COMPLETE_VALIDATED'
    assert completion['execution_provenance']['certificate_id']==cert['certificate_id']
    from src.phase6.continuation_recovery_v4 import prefix_digests
    sampler=read(ROOT/'configs/phase6/neighbor_sampling_v1.json');batch=sampler['batch_size'];prefix=[]
    with (run/'execution.lock').open('rb') as handle:
        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        try:
            for org,old in body['stores'].items():
                p=target/org/'private/local.sqlite'
                for suffix in ('-wal','-journal'):
                    auxiliary=Path(str(p)+suffix);assert not auxiliary.exists() or auxiliary.stat().st_size==0,'Nonempty working WAL/journal needs review; preserve it'
                before=sha(p);db=sqlite3.connect(p.as_uri()+'?mode=ro&immutable=1',uri=True)
                try:
                    assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
                    hashes=prefix_digests(db,old['last_seq'],old['checkpoint_seq'],old['failure_max_id'])
                    assert all(v==old[k] for k,v in hashes.items()),'Committed original prefix differs'
                    assert db.execute('SELECT COUNT(*) FROM failures').fetchone()[0]==0
                    counts=dict(old_commands=old['last_seq'],old_scores=old['score_rows'],new_commands=0,new_local_scores=0,local_model_batch_forwards_from_records=0,old_precommit_seconds=0.,new_precommit_seconds=0.,old_model_seconds=0.,new_model_seconds=0.)
                    for seq,at,timing in db.execute('SELECT seq,asof,timings FROM commands ORDER BY seq'):
                        t=json.loads(timing);kind='old' if seq<=old['last_seq'] else 'new'
                        counts[kind+'_precommit_seconds']+=t['precommit_processing_seconds'];counts[kind+'_model_seconds']+=t['model_scoring_seconds']
                        if kind=='new':
                            counts['new_commands']+=1;counts['new_local_scores']+=t['scored_users'];counts['local_model_batch_forwards_from_records']+=math.ceil(t['scored_users']/batch)
                finally:db.close()
                assert sha(p)==before
                prefix.append(dict(organization=org,status='PASS_EXACT_ORIGINAL_SQL_PREFIX',**counts))
            saved_grid=0;new_grid_forwards={'graphsage':0,'tabular_mlp':0}
            for relative,desc in body['files'].items():
                if '/private/grid_' in relative and relative.endswith('.json') and '/grid_progress/' not in relative:
                    assert sha(target/relative)==desc['sha256'];saved_grid+=1
            assert saved_grid==40
            for org in body['stores']:
                for detector in new_grid_forwards:
                    for minute in (0,10,20,30,40,50):
                        rel=f'{org}/private/grid_{minute:02d}_{detector}.json'
                        if rel not in body['files']:
                            raw=read(target/rel);new_grid_forwards[detector]+=math.ceil(len(raw['roots'])/batch)
            for directory,description in body['journals'].items():
                for segment in description['segments']:
                    p=target/directory/segment['name'];data=p.read_bytes()
                    assert len(data)>=segment['size'] and hashlib.sha256(data[:segment['size']]).hexdigest()==segment['sha256'],'Original journal bytes changed'
            save('exact_reuse_and_execution_counts.json',dict(status='PASS_EXACT_REUSE_NO_ORIGINAL_PREDICTION_RECOMPUTATION_PATH',original_local_scores=sum(p['old_scores'] for p in prefix),original_commands=sum(p['old_commands'] for p in prefix),original_grid_bundles=saved_grid,organizations=prefix,new_grid_batch_forwards_from_records=new_grid_forwards,inference_count_definition='Deterministic batch-forward counts derived from new committed command scored_users and new raw-grid root counts under unchanged batch_size; not an injected live forward counter. Completed original journal/grid paths bypass scoring.',batch_size=batch,completed_originals_reused=5,newly_completed_instances=1,unexpected_campaign_outputs=0,independent_audit_GNN_forwards=0))
        finally:handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
    # Existing separately written evidence oracle, not the production campaign evaluator.
    from src.phase6.independent_test_validation_v1 import validate_instance,ORGS
    inventory=read(ROOT/'reports/phase6/test_execution_preflight_v1/inventory.json');entry=next(r for r in inventory if r['variant_id']==variant)
    thresholds={(o,d):read(ROOT/f'reports/phase6/calibration/v1/thresholds/{o}_{d}.json') for o in ORGS for d in ('graphsage','tabular_mlp')}
    policy=read(ROOT/'configs/phase6/indicator_sharing_v1.json')
    summary,_=validate_instance(run,entry,OUT/'independent_campaign6_audit',thresholds,policy)
    assert summary['status']=='PASS_INDEPENDENT_INSTANCE_AUDIT'
    save('independent_validation_result.json',dict(status='PASS_ONE_PILOT_INDEPENDENT_VALIDATION',variant=variant,completion_sha256=sha(target/'completion.json'),certificate_id=cert['certificate_id'],summary=str(OUT/'independent_campaign6_audit/summary.json'),GNN_forwards=0,newly_completed_instances=1,remaining_instances=165))
    print('PASS_PILOT_AND_INDEPENDENT_VALIDATION_STOP_NO_FULL_RUN',flush=True)
if __name__=='__main__':
    try:main()
    except BaseException as e:
        save('STOP_independent_validation_failure.json',dict(status='STOP',error_type=type(e).__name__,message=str(e),GNN_forwards=0));raise
