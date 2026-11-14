"""Run only Subphase 3. Separate representative smoke and full dataset evidence.

python -B -m src.phase6.run_local_training --mode representative --output reports/phase6/training/integration_v1
python -B -m src.phase6.run_local_training --mode full --output reports/phase6/training/full_v1
"""
import argparse
import copy
from datetime import datetime
import json
import platform
from pathlib import Path
import time

import psutil
import torch
import torch_geometric

from src.phase6.input_pipeline import PinnedInputs,PROTOCOL_SHA256
from src.phase6.local_training import select_and_repeat
from src.phase6.readiness import ROOT,load,sha
from src.phase6.temporal_protocol import require
from src.phase6.training_data import build_cache,cached_batches,dump_json


def run(output,mode,organizations=None):
    require(mode in {'representative','full'},'Unknown run mode')
    require(not output.exists(),'Refusing to overwrite training run')
    output.mkdir(parents=True)
    config=load(ROOT/'configs/phase6/local_training_v1.json')
    config=copy.deepcopy(config)
    if mode=='representative':
        config['training']['max_epochs']=3
        config['training']['early_stopping_patience']=1
    if organizations is not None:
        require(all(org in config['organizations'] for org in organizations),'Unknown organization')
    active=organizations or config['organizations']
    require(len(set(active))==len(active),'Duplicate organization')
    torch.set_num_threads(config['training']['torch_threads'])
    torch.set_num_interop_threads(config['training']['torch_interop_threads'])
    torch.use_deterministic_algorithms(True)
    pins=PinnedInputs(ROOT)
    source_names=['src/phase6/local_graphsage.py','src/phase6/training_data.py','src/phase6/local_training.py',
                  'src/phase6/run_local_training.py','configs/phase6/local_training_v1.json']
    source_hashes={name:sha(ROOT/name) for name in source_names}
    dump_json(output/'source_hashes_before_training.json',source_hashes)
    start=time.perf_counter()
    def journal(event):
        item=dict(timestamp_local_host=datetime.now().isoformat(),elapsed_seconds=time.perf_counter()-start,**event)
        with (output/'progress.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(item)+'\n')
        print(json.dumps(item),flush=True)
    dump_json(output/'config_snapshot.json',config)
    for name,path in [('feature_schema.json',pins.schema_path),('sampling.json',pins.sampler_path),
                      ('split_protocol.json',ROOT/'configs/phase6/split_protocol_v1.json')]:
        dump_json(output/name,load(path))
    selections=[];coverage=[]
    limit=1 if mode=='representative' else None
    for org in active:
        org_start=time.perf_counter()
        train_dir=output/'cache'/org/'TRAIN';val_dir=output/'cache'/org/'VAL'
        journal(dict(event='organization_started',organization=org,mode=mode))
        train_manifest,seen=build_cache(pins,org,'TRAIN',train_dir,train_seen=None,journal=journal,limit=limit)
        # These keys are private local audit metadata, never model embeddings or shared identities.
        dump_json(output/'cache'/org/'train_seen_local_keys.json',dict(users=sorted(seen['users']),ips=sorted(seen['ips'])))
        val_manifest,_=build_cache(pins,org,'VAL',val_dir,train_seen=seen,journal=journal,limit=limit)
        del seen
        require(train_manifest['grids']==6*train_manifest['variants'] and val_manifest['grids']==6*val_manifest['variants'],'Grid coverage mismatch')
        # Verify every disk batch hash before any candidate fits or selects.
        for directory,split in [(train_dir,'TRAIN'),(val_dir,'VAL')]:
            for _ in cached_batches(directory,pins.protocol,split,org,verify_files=True): pass
        cache_seconds=time.perf_counter()-org_start
        journal(dict(event='cache_completed',organization=org,cache_seconds=cache_seconds,
                     train_eligible=train_manifest['positive']+train_manifest['negative'],
                     val_eligible=val_manifest['positive']+val_manifest['negative']))
        result=select_and_repeat(config,org,train_dir,val_dir,pins.protocol,output/'models'/org,journal)
        result['cache_build_seconds']=cache_seconds
        result['organization_total_seconds']=time.perf_counter()-org_start
        selections.append(result)
        coverage.append(dict(organization=org,train_variants=train_manifest['variants'],val_variants=val_manifest['variants'],
            train_grids=train_manifest['grids'],val_grids=val_manifest['grids'],train_positive=train_manifest['positive'],
            train_negative=train_manifest['negative'],val_positive=val_manifest['positive'],val_negative=val_manifest['negative'],
            train_masked_recent=train_manifest['masked_recent_roots'],val_masked_recent=val_manifest['masked_recent_roots']))
        journal(dict(event='organization_verified',organization=org,selected_candidate=result['selected_candidate'],
                     selected_epoch=result['selected_epoch'],val_ap=result['validation']['average_precision'],
                     repeat_exact=result['exact_repeat_state_and_validation_scores']))
    require(all('_TEST' not in name and '/TEST/' not in name for name in pins.checked),'TEST input opened')
    pins.verify_unchanged()
    baseline=load(ROOT/'reports/phase6/training/accepted_inputs_before_subphase3_v1.json')
    for name,digest in baseline.items():
        require(sha(ROOT/name)==digest,'Accepted output changed: '+name)
    for name,digest in source_hashes.items():
        require(sha(ROOT/name)==digest,'Training source/config changed during run: '+name)
    is_full=mode=='full' and active==config['organizations']
    if is_full:
        require(len(selections)==5 and all(r['train_variants']==171 and r['val_variants']==171 for r in coverage),
                'Full five-organization coverage not achieved')
        require(all(s['validation']['inductive_unseen_user']['eligible']>0 and
                    s['validation']['inductive_unseen_ip_context']['eligible']>0 for s in selections),'No real inductive validation coverage')
    status=('PASS_FULL_FIVE_ORGANIZATION_TRAINING_AWAITING_USER_ACCEPTANCE' if is_full else
            'PASS_FULL_SINGLE_ORGANIZATION_TRAINING_COMPONENT' if mode=='full' else 'PASS_REPRESENTATIVE_INTEGRATION_ONLY')
    summary=dict(version='phase6-local-training-results-v1',
        status=status,
        mode=mode,full_five_organization_evidence=is_full,organizations=active,coverage=coverage,models=selections,
        protocol_sha256=PROTOCOL_SHA256,test_inputs_opened=0,training_split='TRAIN',selection_split='VAL',
        accepted_files_preserved=len(baseline),total_seconds=time.perf_counter()-start,
        environment=dict(python=platform.python_version(),torch=torch.__version__,pyg=torch_geometric.__version__,
            numpy=__import__('numpy').__version__,device='cpu',torch_threads=torch.get_num_threads(),
            total_ram_bytes=psutil.virtual_memory().total),
        limitations=['Fixed sampled neighborhoods are reused across epochs; no sampling-variance uncertainty is measured.',
                    'Exact initialization repeats verify replay, not variation across independent initialization seeds.',
                    'Repeated backgrounds and three temporal blocks per split remain dependent.',
                    'Diagnostic precision/recall use nominal .5, not calibrated 1% FPR thresholds.',
                    'Final TEST evaluation remains unopened and requires protocol version control and later gates.'])
    dump_json(output/'input_sha256.json',dict(frozen_inputs=pins.checked,accepted_configuration_hashes=pins.configuration_hashes,
        source_sha256=source_hashes))
    dump_json(output/'summary.json',summary)
    journal(dict(event='run_verified',status=summary['status'],organizations=len(selections)))
    dump_json(output/'artifact_sha256.json',{str(p.relative_to(output)):sha(p) for p in sorted(output.rglob('*'))
                                           if p.is_file() and 'cache' not in p.relative_to(output).parts})
    print('TRAINING_RUN_COMPLETE',str(output/'summary.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['representative','full'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--organizations',nargs='+')
    args=parser.parse_args()
    run(args.output.resolve(),args.mode,args.organizations)
