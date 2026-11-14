"""Memory-bounded launcher of isolated organization jobs; no model aggregation."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

import psutil

from src.phase6.readiness import ROOT,load,sha
from src.phase6.temporal_protocol import require


def dump_json(path,data):
    with Path(path).open('x',encoding='utf-8') as stream:
        json.dump(data,stream,indent=2)
        stream.write('\n')


def aggregate(directory):
    config=load(ROOT/'configs/phase6/local_training_v1.json')
    children=[]
    for org in config['organizations']:
        child=load(directory/'organizations'/org/'summary.json')
        require(child['mode']=='full' and child['organizations']==[org] and
                child['status']=='PASS_FULL_SINGLE_ORGANIZATION_TRAINING_COMPONENT','Unverified organization job')
        require(len(child['models'])==len(child['coverage'])==1,'Invalid component coverage')
        coverage=child['coverage'][0]
        require(coverage['train_variants']==171 and coverage['val_variants']==171 and
                coverage['train_grids']==1026 and coverage['val_grids']==1026,'Incomplete full dataset coverage')
        model=child['models'][0]
        require(model['exact_repeat_state_and_validation_scores'],'No exact training repeat')
        require(model['validation']['inductive_unseen_user']['eligible']>0 and
                model['validation']['inductive_unseen_ip_context']['eligible']>0,'No real inductive coverage')
        require(child['test_inputs_opened']==0,'TEST file accessed')
        for name,digest in load(directory/'organizations'/org/'artifact_sha256.json').items():
            require(sha(directory/'organizations'/org/name)==digest,'Organization artifact changed: '+name)
        children.append(child)
    require(len({c['protocol_sha256'] for c in children})==1,'Protocol differs between organizations')
    result=dict(version='phase6-full-five-local-training-v2',status='PASS_FULL_FIVE_ORGANIZATION_TRAINING_AWAITING_USER_ACCEPTANCE',
        full_five_organization_evidence=True,mode='full',organizations=config['organizations'],
        models=[c['models'][0] for c in children],coverage=[c['coverage'][0] for c in children],
        protocol_sha256=children[0]['protocol_sha256'],training_split='TRAIN',selection_split='VAL',test_inputs_opened=0,
        accepted_files_preserved=children[0]['accepted_files_preserved'],environment=children[0]['environment'],
        limitations=children[0]['limitations'],execution='Two isolated CPU jobs; raw graphs/models are not combined or averaged')
    return result


def run(directory,workers=2):
    require(workers in (1,2),'Resource plan permits at most two workers')
    require(not directory.exists(),'Parallel run exists; choose a new version')
    directory.mkdir(parents=True)
    config=load(ROOT/'configs/phase6/local_training_v1.json')
    dump_json(directory/'config_snapshot.json',config)
    pending=list(config['organizations']);running={};start=time.perf_counter()
    config_digest=sha(ROOT/'configs/phase6/local_training_v1.json')
    def journal(event):
        item=dict(timestamp_local_host=datetime.now().isoformat(),elapsed_seconds=time.perf_counter()-start,**event)
        with (directory/'execution.jsonl').open('a',encoding='utf-8') as stream: stream.write(json.dumps(item)+'\n')
        print(json.dumps(item),flush=True)
    try:
        while pending or running:
            # Leave at least 768 MiB available before starting an additional job.
            while pending and len(running)<workers and (not running or psutil.virtual_memory().available>768*2**20):
                org=pending.pop(0);out=directory/'organizations'/org
                logs=directory/f'{org}_console.log'
                stream=logs.open('x',encoding='utf-8')
                process=subprocess.Popen([sys.executable,'-B','-m','src.phase6.run_local_training','--mode','full',
                    '--organizations',org,'--output',str(out)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
                running[org]=(process,stream)
                journal(dict(event='organization_job_started',organization=org,pid=process.pid,free_ram_bytes=psutil.virtual_memory().available))
            for org,(process,stream) in list(running.items()):
                result=process.poll()
                if result is not None:
                    stream.close();del running[org]
                    require(result==0,f'{org} failed; inspect {org}_console.log')
                    journal(dict(event='organization_job_finished',organization=org,exit_code=result))
            if running: time.sleep(2)
        require(sha(ROOT/'configs/phase6/local_training_v1.json')==config_digest,'Training protocol changed')
        summary=aggregate(directory)
        summary['wall_seconds']=time.perf_counter()-start
        summary['worker_limit']=workers
        dump_json(directory/'summary.json',summary)
        journal(dict(event='full_training_verified',organizations=5,status=summary['status']))
        dump_json(directory/'artifact_sha256.json',{str(p.relative_to(directory)):sha(p) for p in sorted(directory.rglob('*'))
            if p.is_file() and 'cache' not in p.relative_to(directory).parts})
    except BaseException:
        for process,stream in running.values():
            if process.poll() is None: process.terminate()
            stream.close()
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args()
    run(args.output.resolve(),args.workers)
