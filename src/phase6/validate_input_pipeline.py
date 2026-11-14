"""TRAIN-only input validation, independent SQL oracle and resource benchmark.

python -B -m src.phase6.validate_input_pipeline --output reports/phase6/pipeline/v1
No predictions, training, calibration or learned preprocessing are performed.
"""
import argparse
from datetime import datetime,timedelta
import gc
import json
from pathlib import Path
import platform
from time import perf_counter

import numpy as np
import psutil
import torch

from src.organization.rolling_graph_v1 import GraphView
from src.phase6.input_pipeline import BranchPipeline,PinnedInputs,TemporalNeighborSampler,PROTOCOL_SHA256
from src.phase6.readiness import ROOT,REPLAY,load,sha
from src.phase6.temporal_protocol import require
from validate_phase5_graph_retention_v1 import sql_snapshot_check


def save(path,value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,default=str)
        stream.write('\n')


def batch_bytes(batch):
    return sum(p.x.numel()*p.x.element_size()+p.edge_index.numel()*p.edge_index.element_size() for p in batch.packets)


def check_batch(batch,sampler):
    require((sampler.view.x[batch.root_rows,7]==0).all(),'IP target')
    require(batch.supervision.y.shape==batch.supervision.eligible_mask.shape==(len(batch.root_rows),),'Invalid root supervision shape')
    require(torch.equal(batch.supervision.eligible_mask,batch.supervision.y!=-1),'Incorrect mask')
    require(len(batch.packets)==len(sampler.fanouts),'Layer count mismatch')
    for layer,(packet,routing) in enumerate(zip(batch.packets,batch.routing)):
        require(set(packet.keys())=={'x','edge_index','num_nodes'},'Model packet leak')
        require(packet.validate(raise_on_error=False),'Invalid PyG packet')
        require(torch.isfinite(packet.x).all().item(),'Nonfinite features')
        require(np.array_equal(routing.source_rows[:len(routing.destination_rows)],routing.destination_rows),'Broken destination prefix')
        if layer+1<len(batch.packets):
            require(np.array_equal(routing.destination_rows,batch.routing[layer+1].source_rows),'Broken block chaining')
        degree=np.bincount(packet.edge_index[1].numpy(),minlength=len(routing.destination_rows))
        require((degree<=sampler.fanouts[layer]).all(),'Fanout exceeded')
        for source,destination in packet.edge_index.T.tolist():
            u=int(routing.source_rows[source]); v=int(routing.destination_rows[destination])
            require(u in sampler.neighbors[sampler.indptr[v]:sampler.indptr[v+1]],'Non-retained sampled edge')


def save_example(folder,batch,sampler,pins):
    folder.mkdir()
    tensors={}
    mapping=[]
    for i,(packet,route) in enumerate(zip(batch.packets,batch.routing)):
        tensors[f'layer{i}_x']=packet.x.numpy()
        tensors[f'layer{i}_edge_index']=packet.edge_index.numpy()
        tensors[f'layer{i}_num_nodes']=np.asarray(packet.num_nodes,dtype=np.int64)
        mapping.append(dict(layer=i,destination_count=len(route.destination_rows),
                            source_rows=route.source_rows.tolist(),destination_rows=route.destination_rows.tolist(),
                            private_keys=[sampler.view.private_keys[n] for n in route.source_rows]))
    np.savez_compressed(folder/'model_packets.npz',**tensors)
    np.savez_compressed(folder/'supervision.npz',y=batch.supervision.y.numpy(),eligible_mask=batch.supervision.eligible_mask.numpy())
    save(folder/'private_routing.json',mapping)
    save(folder/'provenance.json',dict(**batch.provenance,protocol_sha256=PROTOCOL_SHA256,
        feature_schema_sha256=sha(pins.schema_path),sampler_config_sha256=sha(pins.sampler_path),
        preprocessing=pins.schema['preprocessing'],model_training_performed=False))


def oracle_table(pipeline):
    import duckdb
    pins=pipeline.pins
    manifest=load(pipeline.folder/'replay_manifest.json')
    branch=next(b for b in manifest['branches'] if b['organization']==pipeline.organization)
    ref=load(pins.root/REPLAY/branch['history_reference'])
    files=[str(pins.root/f) for f in ref['source_files_relative_to_root']]
    db=duckdb.connect(':memory:',config={'threads':2})
    schema={r[0] for r in db.execute('DESCRIBE SELECT * FROM read_parquet(?)',[files]).fetchall()}
    success='LoginSuccessful' if 'LoginSuccessful' in schema else 'Login Successful'
    db.execute(f'''CREATE TABLE oracle_events AS SELECT CAST("Login Timestamp" AS TIMESTAMP) ts,
        CAST("User ID" AS BIGINT) uid,CAST("IP Address" AS VARCHAR) ip,CAST("{success}" AS BOOLEAN) success
        FROM read_parquet(?) WHERE CAST("Login Timestamp" AS TIMESTAMP)>=? AND CAST("Login Timestamp" AS TIMESTAMP)<?
        UNION ALL SELECT "Login Timestamp","User ID","IP Address",LoginSuccessful FROM read_parquet(?)''',
        [files,pipeline.anchor-timedelta(days=7),pipeline.anchor,str(pipeline.folder/f'{pipeline.organization}_observations.parquet')])
    return db


def scale_smoke(nodes=1_020_000):
    require(nodes%2==0,'Synthetic scale must be even')
    start=perf_counter()
    half=nodes//2
    users=np.arange(half,dtype=np.int64)
    u=np.concatenate((users,users))
    ip=half+np.concatenate((users,(users+1)%half))
    edges=np.vstack((np.concatenate((u,ip)),np.concatenate((ip,u))))
    x=np.zeros((nodes,8),dtype=np.float32)
    x[:,:3]=[np.log1p(2),0,np.log1p(2)]
    x[:,3]=1
    x[:,4]=np.log1p(2)
    x[half:,7]=1
    x.setflags(write=False);edges.setflags(write=False)
    keys=tuple([('U',int(i)) for i in users]+[('I',f'synthetic-ip-{i:09}') for i in users])
    view=GraphView('Org1',datetime(2020,3,1,13),keys,x,edges)
    built=perf_counter()
    sampler=TemporalNeighborSampler(view,'SYNTHETIC_SCALE_FIXTURE','TRAIN',(15,10),60201)
    indexed=perf_counter()
    batch=sampler.sample(users[:256])
    elapsed=perf_counter()-indexed
    check_batch(batch,sampler)
    process=psutil.Process()
    memory=process.memory_info()
    return dict(kind='synthetic structural capacity smoke, not real graph or detector performance',nodes=nodes,
        directed_edges=edges.shape[1],fixture_build_seconds=built-start,csr_build_seconds=indexed-built,
        sample_256_seconds=elapsed,full_tensor_bytes=x.nbytes+edges.nbytes,
        csr_bytes=sampler.neighbors.nbytes+sampler.indptr.nbytes,model_batch_tensor_bytes=batch_bytes(batch),
        sampled_source_nodes=[p.num_nodes for p in batch.packets],sampled_edges=[p.num_edges for p in batch.packets],
        rss_bytes=memory.rss,process_peak_rss_bytes=getattr(memory,'peak_wset',memory.rss),status='PASS')


def run(output):
    require(not output.exists(),'Refusing to overwrite pipeline evidence')
    output.mkdir(parents=True)
    pins=PinnedInputs(ROOT)
    config= pins.sampler_config
    results=[]
    print('Validating TRAIN seed1001 representative branch for all five organizations',flush=True)
    for org in pins.protocol['organizations']:
        start=perf_counter()
        with BranchPipeline(pins,'CFV1_SO_CS_027_SEED1001_TRAIN',org,purpose='integrity_audit') as pipeline:
            initialized=perf_counter()
            oracle=oracle_table(pipeline)
            identity=id(pipeline.runtime)
            for t in pipeline.grid:
                sampling_start=perf_counter()
                sampler=pipeline.sampler(t)
                indexed=perf_counter()
                states=pipeline.supervision_at(t)
                # Observable recent activity selects a demonstration batch, never the labels.
                recent=sampler.user_rows[sampler.view.x[sampler.user_rows,5]>0]
                roots=recent[:config['batch_size']]
                if not len(roots):
                    roots=sampler.user_rows[:config['batch_size']]
                batch=sampler.sample(roots,states,pins.protocol)
                sampled=perf_counter()
                check_batch(batch,sampler)
                again=sampler.sample(roots,states,pins.protocol)
                require(all(torch.equal(a.edge_index,b.edge_index) and torch.equal(a.x,b.x)
                            for a,b in zip(batch.packets,again.packets)),'Nondeterministic repeat')
                nodes,undirected=sql_snapshot_check(oracle,pipeline.runtime.graph,sampler.view)
                require(id(pipeline.runtime)==identity and pipeline.runtime.training_view() is pipeline.runtime.detection_view(),
                        'Persistent shared runtime replaced')
                if t==pipeline.grid[1]:
                    save_example(output/org,batch,sampler,pins)
                results.append(dict(organization=org,asof=t.isoformat(),nodes=nodes,directed_edges=2*undirected,
                    active_user_candidates=len(sampler.user_rows),demo_user_roots=len(roots),
                    eligible_demo_roots=int(batch.supervision.eligible_mask.sum()),
                    positive_demo_roots=int((batch.supervision.y==1).sum()),
                    snapshot_and_csr_seconds=indexed-sampling_start,batch_and_supervision_seconds=sampled-indexed,
                    history_initialization_seconds=initialized-start,
                    process_rss_bytes=psutil.Process().memory_info().rss,
                    retained_events=len(pipeline.runtime.graph.history_events),
                    full_view_tensor_bytes=sampler.view.x.nbytes+sampler.view.edge_index.nbytes,
                    model_batch_tensor_bytes=batch_bytes(batch),csr_bytes=sampler.neighbors.nbytes+sampler.indptr.nbytes,
                    oracle='PASS_INDEPENDENT_SQL_FEATURES_EDGES',sampling='PASS'))
            oracle.close()
        print(f'{org}: six grids passed; initialization {initialized-start:.3f}s',flush=True)
    save(output/'representative_checks.json',results)
    gc.collect()
    print('Running 1,020,000-node synthetic CSR/batch capacity smoke',flush=True)
    scale=scale_smoke()
    save(output/'scale_smoke.json',scale)
    pins.verify_unchanged()
    baseline=load(ROOT/'reports/phase6/pipeline/accepted_inputs_before_subphase2_v1.json')
    for name,digest in baseline.items():
        require(sha(ROOT/name)==digest,'Accepted Subphase 0/1 or runtime evidence changed: '+name)
    sources={}
    for name in ['CredBlock_Implementation_Plan.pdf','CredBlock-FL_Final_Framework_Explained.pdf',
                 'CredBlock-FL-detection-mechanism.png','CredBlock-FL-workflow.png','CredBlock_FL_Phase6_Implementation_Roadmap.md']:
        path=Path('C:/Users/Gulso/Downloads')/name
        sources[str(path)]=sha(path)
    save(output/'input_provenance.json',dict(frozen_inputs=pins.checked,configuration_hashes=pins.configuration_hashes,
        pipeline_source_sha256=sha(ROOT/'src/phase6/input_pipeline.py'),
        validator_source_sha256=sha(ROOT/'src/phase6/validate_input_pipeline.py'),
        architecture_sources=sources,accepted_evidence_hashes_preserved=len(baseline)))
    summary=dict(status='PASS_SUBPHASE2_TECHNICAL_GATE_AWAITING_USER_ACCEPTANCE',organizations=5,
        representative_branch='CFV1_SO_CS_027_SEED1001_TRAIN',grid_checks=len(results),
        independent_sql_feature_edge_checks=len(results),separate_example_batches=5,
        synthetic_scale_nodes=scale['nodes'],protocol_sha256=PROTOCOL_SHA256,
        feature_schema_sha256=sha(pins.schema_path),sampling_config_sha256=sha(pins.sampler_path),
        accepted_evidence_hashes_preserved=len(baseline),model_training_performed=False,test_outcome_access=False,
        preprocessing=pins.schema['preprocessing'],numpy_version=np.__version__,torch_version=torch.__version__,
        platform=platform.platform(),fanouts_model_order=config['fanouts_model_order'],seed=config['seed'],batch_size=config['batch_size'],
        limitations=['Real validation covers one TRAIN branch and six grids per organization, not all 2565 branches.',
                    'Synthetic scale fixture has degree two; does not establish real million-node traffic throughput.',
                    'Input inductivity is tested without trained model predictions; predictive inductive performance remains Subphase 3.',
                    'Frozen protocol must be in version control before later final TEST evaluation.'])
    save(output/'summary.json',summary)
    save(output/'output_sha256.json',{str(p.relative_to(output)):sha(p) for p in sorted(output.rglob('*')) if p.is_file()})
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.output.resolve())
