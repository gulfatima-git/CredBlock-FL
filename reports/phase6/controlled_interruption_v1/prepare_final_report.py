"""Append-only report assembly from completed recovery audit evidence; no evaluator."""
from pathlib import Path
import json, hashlib
import stat
from datetime import datetime

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
def read(name): return json.loads((OUT/name).read_bytes())
def write(path,value):
    with path.open('x',encoding='utf-8') as f: f.write(value)

summary=read('recovery_assessment_summary.json')
assert summary['status']=='PASS_POST_INTERRUPTION_RECOVERY_VERIFICATION'
assert read('post_audit_host_state.json')['status']=='PASS_NO_EVALUATOR_AFTER_OFFLINE_AUDIT'
assert read('post_audit_lease_state.json')['status']=='PASS_ORIGINAL_LEASE_AVAILABLE_AND_LOCK_UNCHANGED'
audit_source=read('offline_assessment_source_record_v2.json')
assert hashlib.sha256(Path(audit_source['source']).read_bytes()).hexdigest()==audit_source['sha256'],'Audit source changed'
partial=read('incomplete_instance_assessment.json')
assert partial['status']=='PASS_RECOVERABLE_INCOMPLETE_INSTANCE'
snapshot=read('physical_snapshot_manifest.json')
seal_path=ROOT/'reports/phase6/v2_forensic_v1/SNAPSHOT_SEAL.json'
seal=json.loads(seal_path.read_bytes())
assert seal['manifest_sha256']==hashlib.sha256((OUT/'physical_snapshot_manifest.json').read_bytes()).hexdigest(),'Snapshot seal differs'
expected=set(snapshot['files'])
for namespace in ('source','snapshot'):
    base=Path(snapshot[namespace])
    observed={p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}
    assert observed==expected,namespace+' census changed'
    for rel,desc in snapshot['files'].items():
        info=(base/rel).stat()
        assert info.st_size==desc['size'],rel+' size changed'
        if namespace=='source': assert info.st_mtime_ns==desc['mtime_ns'],rel+' source metadata changed'
        else: assert not info.st_mode & stat.S_IWRITE,rel+' snapshot not read-only'
write(OUT/'post_audit_snapshot_census.json',json.dumps(dict(status='PASS_SOURCE_AND_SNAPSHOT_CENSUS_METADATA_AND_READONLY',files=len(expected),additional_SQLite_files_created=False,scope='Metadata only; per-file content preservation is sealed separately'),indent=2)+'\n')
scores=read('all_saved_score_identity_verification.json')
checkpoint=read('checkpoint_recovery_verification.json')
assert checkpoint['status']=='PASS_ALL_CHECKPOINTS_AND_GRAPH_RECOVERY'
assert scores['status']=='PASS_ALL_30_SCORE_STORES'
assert read('post_audit_preservation.json')['status']=='PASS_TARGETED_POST_AUDIT_PRESERVATION'
orgs=partial['organizations']; sharing=partial['sharing']
table='\n'.join(f"| {o['organization']} | {o['commands']} | {o['input_events']} | {o['saved_scores']} | {o['committed_grid_bundles']} | {o['saved_grid_rows']} | {o['latest_checkpoint_seq']} | {o['last_committed_time']} |" for o in orgs)
pending=json.dumps(sharing['pending'],indent=2)
completed='\n'.join('- '+c['variant'] for c in summary['completed'])
report=f'''# Phase 6 controlled interruption and recovery verification

Technical status: **PASS — saved-state recovery verification**. Production continuation remains **NOT AUTHORIZED**. Phase 6 remains IN_PROGRESS; Phase 7 remains UNSTARTED. This is neither final TEST acceptance nor a v4 execution approval.

## Authorization, prechecks and actual interruption

The explicit user authorization is preserved in user_authorization_record.json. Worker 22264, launcher 12092 and parent PowerShell 12764 were matched by creation time, command line and parent relationships. No duplicate evaluator was present. The inspected console contained those three processes plus the self-protected sender. Sixty-nine explicitly scoped reviewed source/configuration/evidence hashes and the v4 release identity matched before delivery.

Exactly one CTRL_C_EVENT was sent at 2026-11-18T13:33:49.091231+05:00. The API reported success. Worker and launcher exited by 13:33:53.600867+05:00 with observed Windows status 0xC000013A. The parent shell was subsequently absent in independent process queries. The original execution session recorded KeyboardInterrupt at the graph detection-view stage before the following prediction call, and session exit code 1. This was an arbitrary recoverable interruption, not a graceful or campaign-boundary shutdown. No retry, forced termination, suspension or evaluator launch occurred.

Evidence: live_preflight.json, live_recipient_scope.json, signal_attempt.json, signal_delivery_result.json, process_exit_observations.json, independent_exit_check.json and original_traceback_observation.json. The one-attempt marker must never be reused to send another event.

## Forensic preservation and SQLite

After independently establishing process absence and acquiring the original read-only execution lease, a separate forensic snapshot was sealed at reports/phase6/v2_forensic_v1/physical. It contains {len(snapshot['files']):,} files totaling {snapshot['total_bytes']:,} bytes and {len(snapshot['database_sets'])} database sets. Original and snapshot file hashes matched; every copied file was set read-only. This is hash-sealed, read-only preservation, not hardware WORM storage.

The first capture attempt failed when a second handle tried to read the byte-locked execution.lock. It had copied 51,688 files; only execution.lock and required_inventory.json remained. The failed attempt and diagnosis are preserved. A disposable fixture reproduced the Windows reader conflict. The additive second capture used the owning read-only lease handle, verified the existing copies, and added the missing two files without overwriting originals or prior copies. Final capture passed. This failure was not concealed or classified as source corruption.

All 30 forensic SQLite databases passed integrity_check. The complete inventory contains no nonempty WAL; database_derivations.json records every WAL/SHM presence or absence. No original database was opened through SQLite, checkpointed, repaired or deleted. Therefore the current production evidence establishes self-contained post-exit databases; it does not establish actual recovery of a nonempty production WAL. Reviewed WAL-aware support remains backed by its separate synthetic evidence. Sidecars that may have existed before process exit cannot be claimed to have been byte-captured before normal SQLite cleanup.

Targeted post-audit checks reconfirmed all 69 reviewed file hashes and all 30 original/snapshot database hashes. All ten selected model/threshold pairs match original identities, without model deserialization. Snapshot flags, full capture hashes, lock preservation and database derivations have separate evidence files.

## Completed campaigns independently verified

**{summary['completed_verified']}/171 campaigns are complete and independently verified.** There are {171-summary['completed_verified']} incomplete campaigns, consisting of one partially executed campaign and 165 not yet started. Completed campaigns retain their original completion provenance:

{completed}

Each completed campaign passed the independent saved-evidence validator, including completion artifacts, all-five-organization coverage, fixed-grid metrics, operational sharing decisions, temporal attribution and censoring. Evidence is in completed_audits/<variant>/summary.json. Successful recovery is not a claim that all 171 scientific evaluations are complete.

## Reusable partial campaign

Variant: {partial['variant_id']}. It is explicitly NOT COMPLETE. Its incomplete state must not be reported as full-horizon detection or non-detection.

| Organization | Committed commands | Input events | Saved local scores | Grid bundles | Grid rows | Latest checkpoint sequence | Last committed time |
|---|---:|---:|---:|---:|---:|---:|---|
{table}

The partial campaign contains {sum(o['saved_scores'] for o in orgs):,} reusable committed local scores and {sum(o['saved_grid_rows'] for o in orgs):,} committed grid rows. Across all 30 stores, {scores['total_scores']:,} saved local scores passed exact finite-logit, binary64 threshold/decision, model, threshold and feature-schema identity checks. All {sum(s['checkpoints'] for s in checkpoint['sets'])} checkpoints and latest-checkpoint-plus-command recovery passed for every organization, covering {sum(s['committed_commands'] for s in checkpoint['sets']):,} committed commands and replaying {sum(s['graph_commands_replayed'] for s in checkpoint['sets'])} graph commands after latest checkpoints. The completed/partial independent history audits additionally replay their required histories. Independent graph replay used **zero GNN forwards**.

The partial sharing chain has {sharing['completed_barriers']} completed barriers; latest complete timestamp: {sharing['latest_completed_barrier']}. It preserves {sharing['indicator_episodes']} indicator episodes and {sharing['receipts']} receipts. Issuance, publication, recipient identity, availability, exclusive expiry and paired decisions were independently checked. Pending barrier details:

```json
{pending}
```

Per-organization committed SQL without LOCAL publication and pending commands are recorded verbatim in incomplete_instance_assessment.json. Such committed predictions are reusable; missing publication is not permission to recompute them. Volatile work after the last durable command may have been lost. There is no claim to preserve an in-progress feature tensor or an uncommitted prediction. Future continuation may compute genuinely uncommitted work only after separate authorization.

## Gates and limitations

| Gate | Finding |
|---|---|
| Original worker/launcher exit and lease availability | PASS |
| Hash-sealed complete physical snapshot | PASS, after documented capture-reader correction |
| Thirty database integrity checks | PASS |
| Thirty checkpoint and graph recovery sets | PASS |
| Saved prediction, threshold and identity preservation | PASS |
| Five original completed campaign reconciliations | PASS |
| All-five-organization partial committed-prefix consistency | PASS |
| Scientific protocol/model/source preservation | PASS within explicit preservation scope |
| Recovered-state readiness for a separately authorized bounded v4 pilot | PASS; production integration still requires its explicit certificate/authorization gates |
| Actual nonempty production WAL recovery | NOT EXERCISED; no nonempty WAL found |
| Production v4 continuation/pilot | NOT RUN; separate authorization required |
| Full 171-instance TEST completion | PENDING |

Frozen protocol SHA256 remains 9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b. Reviewed v4 release remains 4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370. Frozen register remains d9e2b1a63308e00da05b5dac2afd83f27b259c006e69044f593130db0cc0aaef. No architecture, feature, sampling, threshold, split, scoring unit, attribution or evaluation denominator was changed. No training or calibration occurred.

This recovery assessment uses the established independent validator for completed campaigns and separately written offline partial-state checks; it is not a second evaluator or a claim of a newly independent implementation of every numerical primitive. Graph commands were replayed to verify state, never to repeat committed GNN inference. Shared-Parquet logical-versus-physical isolation limitations remain. Fixed-grid 1% VAL calibration does not imply 1% operational or TEST FPR. The accepted VAL finding remains 0/171 wholly undetected campaigns; it does not demonstrate recovery of campaigns missed by every organization. Accepted historical scope incidents and failed reviews remain untouched.

The reviewed v4 synthetic release evidence remains in reports/phase6/wal_continuation_v4_v1/TECHNICAL_ACCEPTANCE_REPORT.md. Its documented limitation remains: the full matrix was not rerun after three guard-only changes; focused final-source tests and static/certificate rechecks supported applicability. This recovery audit does not replace that evidence with an actual production-v4 result.

## Recommendation and next gate

The verified saved state is suitable for review of a separately authorized, bounded v4 continuation pilot. This report does not create a production continuation certificate, capture authorization or execution grant. Before any pilot: bind the reviewed release, original predecessor identities, sealed forensic evidence and all-five-organization committed boundaries; validate the required v4 authorization/certificate gates; write only in a separate v4 namespace; reuse the five original completions and committed partial predictions without GNN repetition; and independently reconcile the pilot before considering the remaining run.

No production-equivalent v4 runtime was measured here. Prior indexed-journal/synthetic speedups cannot establish a reliable remaining-run ETA; a separately authorized bounded pilot must measure it. Full scientific completion remains pending all 171 instances and final independent validation. Stop here for the user's decision.
'''
write(OUT/'TECHNICAL_RECOVERY_REPORT.md',report)
progress=json.loads((ROOT/'reports/phase6/progress_v33.json').read_bytes())
progress.update(version='phase6-progress-v34',recorded_on_local_date='2026-11-18',updated_at=datetime.now().astimezone().isoformat(),phase6='IN_PROGRESS',phase6_status='TEST_INTERRUPTED_RECOVERY_VERIFIED_AWAITING_CONTINUATION_APPROVAL',previous_record='reports/phase6/progress_v33.json',previous_record_sha256=hashlib.sha256((ROOT/'reports/phase6/progress_v33.json').read_bytes()).hexdigest(),next_exact_action='User review of controlled interruption recovery report; await separate v4 pilot authorization')
progress['controlled_interruption_recovery']=dict(status='PASS_SAVED_STATE_RECOVERY_VERIFICATION',report='reports/phase6/controlled_interruption_v1/TECHNICAL_RECOVERY_REPORT.md',original_v2_stopped=True,interrupt_events_sent=1,complete_verified=summary['completed_verified'],required=171,partial_variant=partial['variant_id'],partial_committed_local_scores=sum(o['saved_scores'] for o in orgs),GNN_forwards=0,v4_launched=False,v4_execution_authorized=False,phase7_started=False)
progress['subphases']['9']['stage_c']='TEST_INTERRUPTED_SAVED_STATE_VERIFIED_AWAITING_CONTINUATION_APPROVAL'
progress['test_predictions_performed']=True
progress['wal_aware_continuation_v4'].update(status='RECOVERY_VERIFIED_AWAITING_SEPARATE_PILOT_APPROVAL',original_runner_not_controlled=False,original_progress_not_reinspected=False,live_interruption_authorized=True,live_capture_authorized=True,production_execution_authorized=False)
progress['historical_sections_note']='Earlier implementation and transition snapshots retain their historical measurements; controlled_interruption_recovery is the current verified progress authority. Prior progress files are unchanged.'
write(ROOT/'reports/phase6/progress_v34.json',json.dumps(progress,indent=2)+'\n')
write(OUT/'recovery_progress_event.json',json.dumps(progress['controlled_interruption_recovery'],indent=2)+'\n')
write(OUT/'capture_incident_resolution.json',json.dumps(dict(status='RESOLVED_CAPTURE_READER_CONFLICT',original_failure='capture_failure_135408228705.json',diagnosis='capture_failure_diagnosis.json',correction='forensic_capture_v2.py',verification='physical_snapshot_manifest.json',failed_evidence_preserved=True,original_files_overwritten=False,original_database_connections=False,explanation='Read the leased byte through the owning read-only handle; preserve and reverify previous copied files; append only two missing files.'),indent=2)+'\n')
files={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file()}
files['reports/phase6/progress_v34.json']=hashlib.sha256((ROOT/'reports/phase6/progress_v34.json').read_bytes()).hexdigest()
files['reports/phase6/v2_forensic_v1/SNAPSHOT_SEAL.json']=hashlib.sha256(seal_path.read_bytes()).hexdigest()
write(OUT/'delivery_manifest_v1.json',json.dumps(dict(status='APPEND_ONLY_RECOVERY_REPORT_DELIVERY',files_sha256=files,private_forensic_payloads_excluded=True),indent=2)+'\n')
print('PASS_REPORT_ASSEMBLED_NO_EVALUATOR_LAUNCH')
