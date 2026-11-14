"""Verify five completed independent components, then create acceptance evidence.

This refuses partial/representative training and never opens TEST branch files.
"""
import argparse
import csv
import json
from pathlib import Path
import shutil

import numpy as np
import torch

from src.phase6.input_pipeline import PROTOCOL_SHA256
from src.phase6.local_graphsage import LocalGraphSAGE,state_digest
from src.phase6.readiness import ROOT,load,sha
from src.phase6.temporal_protocol import require
from src.phase6.training_data import cached_batches,dump_json


def verify_components(plan):
    config=load(ROOT/'configs/phase6/local_training_v1.json')
    protocol=load(ROOT/'configs/phase6/split_protocol_v1.json')
    require(sha(ROOT/'configs/phase6/split_protocol_v1.json')==PROTOCOL_SHA256,'Frozen protocol changed')
    records=[];source_hashes=None;cache_files=0
    for org in config['organizations']:
        directory=ROOT/plan['components'][org]
        summary=load(directory/'summary.json')
        require(summary['mode']=='full' and summary['organizations']==[org] and
                summary['status']=='PASS_FULL_SINGLE_ORGANIZATION_TRAINING_COMPONENT','Component is not a completed full local run: '+org)
        require(summary['test_inputs_opened']==0 and summary['protocol_sha256']==PROTOCOL_SHA256,'TEST/protocol violation')
        coverage=summary['coverage'][0]
        require(coverage['organization']==org and coverage['train_variants']==coverage['val_variants']==171 and
                coverage['train_grids']==coverage['val_grids']==1026,'Incomplete corpus: '+org)
        inputs=load(directory/'input_sha256.json')
        require(all('_TEST' not in name and '/TEST/' not in name for name in inputs['frozen_inputs']),'TEST input found')
        if source_hashes is None: source_hashes=inputs['source_sha256']
        require(source_hashes==inputs['source_sha256'],'Training source/config differs between organizations')
        for name,digest in inputs['source_sha256'].items():
            require(sha(ROOT/name)==digest,'Training source/config changed: '+name)
        for name,digest in load(directory/'artifact_sha256.json').items():
            require(sha(directory/name)==digest,'Component artifact changed: '+name)
        model=summary['models'][0]
        require(model['organization']==org and model['exact_repeat_state_and_validation_scores'],'No exact reproduction: '+org)
        train=directory/'cache'/org/'TRAIN';val=directory/'cache'/org/'VAL'
        for split,cache in [('TRAIN',train),('VAL',val)]:
            manifest=load(cache/'manifest.json')
            require(manifest['scope']=='FULL' and manifest['split']==split and manifest['organization']==org,'Wrong cache scope')
            observed={entry['variant_id'] for entry in manifest['files']}
            expected={p.parent.name for p in (ROOT/'data/phase5/controlled_replay_labels_all_orgs_causal_v1').glob(f'CFV1*_{split}/replay_manifest.json')}
            require(observed==expected and len(observed)==171,'Frozen branch assignment coverage differs')
            require(len({entry['path'] for entry in manifest['files']})==1026,'Duplicate/missing fixed grids')
            for entry in manifest['files']:
                require(entry['split']==split and entry['organization']==org and sha(cache/entry['path'])==entry['sha256'],'Cached input changed')
                cache_files+=1
            metrics=model['selected_model_train_metrics'] if split=='TRAIN' else model['validation']
            require(metrics['eligible']==manifest['positive']+manifest['negative'] and metrics['positive']==manifest['positive'],
                    'Selected model census differs from exact-grid corpus')
        checkpoint=Path(model['checkpoint'])
        require(sha(checkpoint)==model['checkpoint_sha256'],'Selected checkpoint changed')
        saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
        require(saved['organization']==org and saved['split_fitted']=='TRAIN' and saved['split_selected']=='VAL','Wrong checkpoint lineage')
        require(saved['train_cache_sha256']==sha(train/'manifest.json') and saved['validation_cache_sha256']==sha(val/'manifest.json'),
                'Checkpoint input hash mismatch')
        require(state_digest(saved['model_state'])==model['selected_state_digest'],'Checkpoint weight digest mismatch')
        require(all(torch.isfinite(t).all().item() for t in saved['model_state'].values()),'Nonfinite model state')
        require(saved['seed']==config['training']['initial_seed_base']+config['organizations'].index(org),'Initialization seed mismatch')
        train_manifest=load(train/'manifest.json')
        require(saved['positive_weight']==train_manifest['negative']/train_manifest['positive'],'Class weighting not derived from TRAIN')
        selected_by_val=sorted(model['trial_summaries'],key=lambda t:(-t['validation']['average_precision'],t['validation']['bce'],t['candidate']['id']))[0]
        require(selected_by_val['candidate']==model['selected_candidate'],'Hyperparameters not selected by frozen VAL rule')
        winner=next(t for t in model['trial_summaries'] if t['candidate']['id']==model['selected_candidate']['id'])
        repeat=model['reproduction_summary']
        require(winner['initial_state_digest']==repeat['initial_state_digest'] and
                winner['selected_state_digest']==repeat['selected_state_digest'] and
                winner['selected_epoch']==repeat['selected_epoch'],'Repeat model differs')
        a=directory/'models'/org/model['selected_candidate']['id']/'validation_predictions.csv'
        b=directory/'models'/org/'reproducibility_repeat'/'validation_predictions.csv'
        require(sha(a)==sha(b),'Repeated VAL predictions differ')
        network=LocalGraphSAGE(model['selected_candidate']['hidden_dim'],config['model']['num_layers'],config['model']['dropout'])
        network.load_state_dict(saved['model_state'],strict=True);network.eval()
        batch,_=next(cached_batches(val,protocol,'VAL',org,verify_files=True))
        with torch.no_grad(): predicted=network(batch).numpy()
        with a.open(newline='',encoding='utf-8') as stream:
            reader=csv.DictReader(stream)
            expected=np.asarray([float(next(reader)['logit']) for _ in range(len(predicted))],dtype=np.float32)
        require(np.array_equal(predicted,expected),'Safe checkpoint reload scores differ')
        require(model['validation']['inductive_unseen_user']['eligible']>0 and model['validation']['inductive_unseen_ip_context']['eligible']>0,
                'No real inductive VAL coverage')
        require(winner['first_layer_gradient_updates']>0 and winner['optimizer_updates']>0,'No local GraphSAGE parameter training')
        records.append(dict(**model,coverage=coverage,component_directory=str(directory),
                            model_parameters=sum(p.numel() for p in network.parameters())))
    require(len(records)==5 and len({r['selected_state_digest'] for r in records})==5,'Five independent local models not verified')
    baseline=load(ROOT/'reports/phase6/training/accepted_inputs_before_subphase3_v1.json')
    for name,digest in baseline.items(): require(sha(ROOT/name)==digest,'Accepted evidence changed: '+name)
    return records,cache_files,len(baseline)


def report_text(records,cache_files,preserved):
    lines=['# Phase 6 Subphase 3 (6.2B): Five Independent Local GraphSAGE Models','',
        '**Technical acceptance gate: PASS; user acceptance pending.** Five independently trained local models have been verified on the complete accepted TRAIN/VAL inventory. TEST remains unopened.','',
        'Subphase 2 is USER_ACCEPTED in `reports/phase6/pipeline/acceptance_v1.json`. All accepted Phase 5 and Phase 6 Subphase 0/1/2 outputs remain unchanged.','',
        '## Full training results','',
        'AP is tied-score-grouped average precision (noninterpolated PR area). BCE is unweighted at the restored selected model. Precision/recall/F1 use nominal probability 0.5 as training diagnostics, not calibrated operating thresholds or 1% FPR results.','',
        '| Organization | Hidden width | Selected epoch | TRAIN eligible | VAL eligible | TRAIN BCE | VAL BCE | VAL AP | VAL precision @ .5 | VAL recall @ .5 | VAL F1 @ .5 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in records:
        t,v=r['selected_model_train_metrics'],r['validation']
        lines.append(f"| {r['organization']} | {r['selected_candidate']['hidden_dim']} | {r['selected_epoch']} | {t['eligible']:,} | {v['eligible']:,} | {t['bce']:.8f} | {v['bce']:.8f} | {v['average_precision']:.8f} | {v['precision_at_0_5']:.8f} | {v['recall_at_0_5']:.8f} | {v['f1_at_0_5']:.8f} |")
    lines+=['','Every organization used all 171 TRAIN and all 171 VAL branches, all three campaign seeds and all six accepted grid times per branch: 1,026 TRAIN and 1,026 VAL grids each. This is the full controlled replay inventory, not continuous labeled coverage of the entire calendar ranges. All eligible User-time examples are retained. Ambiguous recent roots remain masked; older context-only roots are omitted from supervised forward passes but remain available as graph context. The final-ten-minute grid coverage gap is unchanged.','',
        '## Model and selection protocol','',
        'PyG `SAGEConv` supplies two mean-aggregation layers with root transforms, ReLU and 0.1 dropout between layers, followed by a linear User-node binary-logit head. Layer two consumes layer-one hidden states using accepted destination-prefix routing. It never resets to the second packet\'s raw inspection features. Unit tests compare sampled output with a full-graph reference and verify gradients through both layers. No node-ID embeddings exist.','',
        'The predeclared candidates were hidden widths 16 and 32. Adam used learning rate 0.003 and weight decay 0.0001, with gradient clipping at norm 5.0. Each local trial started from fresh seeded weights; seeds were 63030 through 63034. Class weights were computed only from that organization\'s eligible TRAIN negative/positive ratio. Epochs were capped at 12, with VAL AP early-stopping patience 3 and minimum improvement 1e-6. Candidate selection used VAL AP, then lower VAL BCE, then candidate ID. No optimizer step used VAL.','',
        'The same grid and selection rule were used in every organization. Selected local hidden widths may differ. Later federation must fix a common architecture before averaging; there is no averaging or global initialization in this local-only subphase. The configurable model/batch interface is reusable without changing the accepted features or graph design.','',
        'The accepted fanouts [15,10], batch size 256, sampler seed 60201, eight-feature allowlist and exact-grid labels were reused unchanged. Fixed sampled neighborhoods were cached on disk and reused across epochs. There is no fitted preprocessing. Inputs are processed branch-by-branch with chronological anchors and grids, without mixing alternative worlds into one event stream. All fitting occurs after the TRAIN cutoff; diagnostic TRAIN scores are in-sample, not historical deployment claims.','',
        '## Reproducibility and checkpoints','',
        'Each selected configuration was retrained from the identical initialization seed over the complete local corpus, including early stopping. Every organization reproduced the selected epoch, canonical weight digest and complete VAL prediction CSV exactly. Container file hashes and numerical state digests are recorded separately. Safe `weights_only=True` loading reproduced stored VAL logits. Exact replay does not measure uncertainty across different initialization seeds.','',
        '| Organization | Seed | Parameters | Selected checkpoint |', '|---|---:|---:|---|']
    for r in records:
        lines.append(f"| {r['organization']} | {r['initialization_seed']} | {r['model_parameters']:,} | `{r['checkpoint']}` |")
    lines+=['','Each component directory contains both candidate epoch logs/checkpoints, selected TRAIN metrics/predictions, VAL predictions with labels and masks, the exact repeat, full configuration snapshots, input/source hashes and cache manifests. Only tensors and primitive metadata are stored in model checkpoints. Raw local keys remain audit metadata outside model inputs.','',
        '## Resource measurements','',
        'CPU-only runs used two Torch threads per organization job. Up to five independent jobs overlapped under the recorded execution plan. Timings below include real concurrent host load; they are not exclusive-machine benchmarks. Selected trial time includes training, per-epoch validation, checkpointing and final validation export. All-trial time includes both candidates and the exact repeat; cache preparation is separate. RSS is whole-process memory, including runtime and residual caches.','',
        '| Organization | Cache prep seconds | Selected trial seconds | All trials seconds | Selected trial CPU seconds | Observed training RSS peak MiB |',
        '|---|---:|---:|---:|---:|---:|']
    for r in records:
        selected=next(t for t in r['trial_summaries'] if t['candidate']['id']==r['selected_candidate']['id'])
        lines.append(f"| {r['organization']} | {r['cache_build_seconds']:.3f} | {r['selected_run_seconds']:.3f} | {r['all_trials_seconds']:.3f} | {selected['process_cpu_seconds']:.3f} | {r['observed_training_rss_peak_bytes']/2**20:.3f} |")
    lines+=['','## Real inductive validation','',
        'An unseen User is absent from the union of all local TRAIN graph views. Unseen-IP context means at least one sampled root-neighbor IP was absent from that same TRAIN union. These flags are evaluator-only, never model inputs or fitting weights. IPs are context nodes, not classification targets. Missing subgroup AP means no positive labels, not a fabricated zero.','',
        '| Organization | Unseen-User eligible | Unseen-User AP | Unseen-IP-context eligible | Unseen-IP-context AP |', '|---|---:|---:|---:|---:|']
    for r in records:
        u=r['validation']['inductive_unseen_user'];ip=r['validation']['inductive_unseen_ip_context']
        fmt=lambda x:'N/A' if x is None else f'{x:.8f}'
        lines.append(f"| {r['organization']} | {u['eligible']:,} | {fmt(u['average_precision'])} | {ip['eligible']:,} | {fmt(ip['average_precision'])} |")
    lines+=['','## Tests, scope and execution history','',
        'The final automated non-TEST suite passed 96 tests, with one existing real-TEST-manifest test deliberately deselected (142 dependency warnings, 106.72 seconds). New TEST guards are tested before file access. The first attempt had 92 passes and three temporary-directory setup errors; a permitted rerun resolved the setup errors (95 passed). After warm-up reader buffers were released, both real TRAIN/VAL fork-equivalence tests passed again. A further regression test verifies that representative results cannot create a full acceptance report. Exact commands and the separate accepted-runtime self-test result are recorded in testing_results_v1.json.','',
        'The tiny optimizer/checkpoint test is a smoke test. `integration_v1` is representative training on one fixed TRAIN/VAL branch per organization, capped at three epochs; its results are not the full-data table above. Its development artifact manifest was corrected append-only because the final progress line was appended after the journal hash; numerical artifacts were unchanged.','',
        'The initial sequential full-data attempt was stopped during cache preparation, before any full-data model was trained, to change execution scheduling. Its partial cache is retained and is not accepted training evidence. The final execution plan uses queued isolated Org1/Org2 jobs and independent Org3-Org5 components; only the five verified full components supply this report. Redundant queued work is stopped after Org1/Org2 complete. No accepted artifact was overwritten.','',
        f'Final verification checked {cache_files:,} sampled cache files, all component artifact manifests, checkpoint/cache fingerprints, exact split/branch/grid coverage, independent model states, real inductive coverage, zero TEST branch inputs and {preserved} pre-existing accepted files. Shared raw organization sources were queried only for bounded past TRAIN/VAL warm-up and hashed for integrity; no TEST branch observations, labels or manifests were opened by training or model selection.','',
        '## Preservation and remaining limitations','',
        'Frozen protocol SHA256: `'+PROTOCOL_SHA256+'`. Splits, grid definitions, evaluation units and the primary 1% FPR target were not amended. A version-control commit remains required before final TEST evaluation. No threshold calibration, continuous alerting, indicator sharing, federated learning, DP or blockchain component was implemented.','',
        'Repeated background data and three temporal blocks per split remain dependent. Clean-negative candidates do not certify benignness. Validation is used for selection and is not final held-out performance. The search covers two modest architectures and one initialization seed per organization; exact repeats do not supply initialization confidence intervals. Actual training uses retained real graphs; the prior million-node synthetic smoke is not million-node training evidence. Nominal precision uses a zero result for no predicted positives; undefined empty-subgroup metrics are marked N/A.','',
        'The next exact action is user review and acceptance of Subphase 3. Only then proceed to Subphase 4 (6.2C), the non-graph local comparator. This report does not complete Phase 6.','']
    return '\n'.join(lines)


def run(output,plan_path):
    require(not output.exists(),'Final report directory exists; choose a new version')
    plan=load(plan_path)
    records,cache_files,preserved=verify_components(plan)
    output.mkdir(parents=True)
    (output/'models').mkdir()
    for record in records:
        destination=output/'models'/f'{record["organization"]}.pt'
        shutil.copyfile(record['checkpoint'],destination)
        require(sha(destination)==record['checkpoint_sha256'],'Copied checkpoint changed')
        record['original_checkpoint']=record['checkpoint'];record['checkpoint']=str(destination)
    result=dict(status='PASS_SUBPHASE3_FULL_FIVE_LOCAL_TRAINING_AWAITING_USER_ACCEPTANCE',organizations=5,
                protocol_sha256=PROTOCOL_SHA256,verified_cache_files=cache_files,accepted_files_preserved=preserved,
                models=records,test_branch_files_opened=0,version_control_before_final_test='REQUIRED_PENDING')
    dump_json(output/'summary.json',result)
    (output/'ACCEPTANCE_REPORT.md').write_text(report_text(records,cache_files,preserved),encoding='utf-8')
    dump_json(output/'artifact_sha256.json',{str(p.relative_to(output)):sha(p) for p in output.rglob('*') if p.is_file()})
    print(json.dumps({k:result[k] for k in ['status','organizations','verified_cache_files','accepted_files_preserved']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,default=ROOT/'reports/phase6/training/execution_plan_v3.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    torch.set_num_threads(2)
    run(args.output.resolve(),args.plan.resolve())
