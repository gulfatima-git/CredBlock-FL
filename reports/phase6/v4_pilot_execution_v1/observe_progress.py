"""Read operational progress and external samples only; never open SQLite."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
base=ROOT/'reports/phase6/heldout_test_v2/wal_v4_transition/pilot_campaign6_v1'
variant='CFV1_RA_CS_005_SEED1003_TEST';meta=base/'continuation_meta'/variant
def journal(path):
    counts={};last=None
    for p in sorted(path.glob('barriers.*.jsonl')):
        for line in p.read_bytes().splitlines(keepends=True):
            if not line.endswith(b'\n'):continue
            b=json.loads(line)['body'];event=b['event'];counts[event]=counts.get(event,0)+1
            if event=='COMPLETE':last=b.get('at')
    return counts,last
copies,_=journal(meta/'copy_progress');sharing,last=journal(base/variant/'sharing/progress')
mixed,_=journal(base/'mixed_manifest/progress')
samples=(OUT/'resource_samples.jsonl').read_text().splitlines()
sample=json.loads(samples[-1]) if samples else None
stderr=(OUT/'evaluator_stderr.log').read_text(errors='replace')
record=dict(at=datetime.now(timezone(timedelta(hours=5))).isoformat(),elapsed_seconds=sample['elapsed_seconds'] if sample else None,available_GiB=sample['available_physical_bytes']/2**30 if sample else None,tree_RSS_MiB=sample['tree_rss_bytes']/2**20 if sample else None,worker_CPU_seconds=max((p['cpu_seconds'] for p in sample['processes']),default=None) if sample else None,workspace_ready=(meta/'ready.json').exists(),copy_files=copies.get('COPY_FILE',0),restored_images=copies.get('RESTORE_IMAGE',0),complete_barriers_including_reused=sharing.get('COMPLETE',0),new_complete_barriers=max(0,sharing.get('COMPLETE',0)-1674),latest_complete_barrier=last,instance_complete=(base/variant/'completion.json').exists(),evaluator_exited=(OUT/'execution_result.json').exists(),stderr_tail=stderr[-1800:])
record.update(mixed_manifest_completed_records=mixed.get('INSTANCE_COMPLETE',0),continuation_executor_marker=(base/variant/'executor_v4.json').exists(),local_WAL_files_present=sum((base/variant/f'Org{o}/private/local.sqlite-wal').exists() for o in range(1,6)))
record['version_transition_journals']=sharing.get('ENGINE_TRANSITION',0)+sum(journal(base/variant/f'Org{o}/private/grid_progress')[0].get('ENGINE_TRANSITION',0) for o in range(1,6))
with (OUT/'operational_observations.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
print(json.dumps(record,indent=2))
