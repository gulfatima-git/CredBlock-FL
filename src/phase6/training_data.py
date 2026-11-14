"""TRAIN/VAL-only disk cache adapter around the unchanged accepted pipeline.

Warm-up reuse only forks accepted RollingGraph state before replay. All replay,
as-of exports, sampling and exact supervision use original BranchPipeline methods.
"""
import copy
from datetime import datetime
import json
from pathlib import Path

import numpy as np
import torch
from torch_geometric.data import Data

from src.organization.rolling_graph_v1 import OBSERVABLE,OrganizationGraphRuntime
from src.phase6.input_pipeline import BranchPipeline,ModelBatch,Routing,Supervision
from src.phase6.readiness import REPLAY,load,sha
from src.phase6.temporal_protocol import require,require_use,validate_branch


def guarded_split(protocol,split):
    require(split in {'TRAIN','VAL'},'Training subsystem never opens TEST')
    require_use(protocol,split,'fit' if split=='TRAIN' else 'model_selection')


def dump_json(path,data):
    with Path(path).open('x',encoding='utf-8') as stream:
        json.dump(data,stream,indent=2,default=str)
        stream.write('\n')


class WarmupForks:
    """Additive cache of causal warm-up prototypes; no accepted source is changed."""
    def __init__(self,pins,organization,split):
        guarded_split(pins.protocol,split)
        self.pins,self.organization,self.split=pins,organization,split
        self.prototypes={}
        self.parent_hashes={}
        self.forks=0

    def open(self,variant_id):
        import duckdb
        require(variant_id.endswith('_'+self.split),'Wrong split branch requested')
        pins=self.pins
        folder=pins.root/REPLAY/variant_id
        manifest=load(pins.check(folder/'replay_manifest.json'))
        require(manifest['split']==self.split and manifest['variant_id']==variant_id,'Manifest identity mismatch')
        seed=manifest['seed']
        purpose='fit' if self.split=='TRAIN' else 'model_selection'
        if seed not in self.prototypes:
            proto=BranchPipeline(pins,variant_id,self.organization,purpose=purpose)
            self.prototypes[seed]=proto
            self.parent_hashes[seed]=__import__('hashlib').sha256(proto.runtime.graph.checkpoint_bytes()).hexdigest()
            # Warm-up prototypes retain only accepted graph state. Replay clones
            # open owned readers below; keeping source-query buffers is unnecessary.
            proto.close()
        proto=self.prototypes[seed]
        require(proto._ordinal==0 and proto._last_requested is None,'Warm-up prototype mutated')
        require(manifest['anchor']==proto.anchor.isoformat() and manifest['end_exclusive']==proto.end.isoformat(),
                'Warm-up temporal lineage mismatch')
        branch=next(b for b in manifest['branches'] if b['organization']==self.organization)
        reference=load(pins.check(pins.root/REPLAY/branch['history_reference']))
        require(reference['organization']==self.organization and reference['block']==f'{self.split}_SEED{seed}',
                'Warm-up organization/block mismatch')
        validate_branch(pins.protocol,self.split,proto.anchor,proto.end,
                        datetime.fromisoformat(reference['history_start_inclusive']),datetime.fromisoformat(reference['history_end_exclusive']))
        require(reference['history_event_count']==proto._history_count,'Warm-up event count mismatch')
        for source in reference['source_files_relative_to_root']:
            pins.check(pins.root/source)
        observations=pins.check(folder/f'{self.organization}_observations.parquet')
        labels=pins.check(folder/f'{self.organization}_labels.parquet')
        require(sha(observations)==branch['observations_parquet_sha256'] and sha(labels)==branch['labels_parquet_sha256'],
                'Frozen branch source mismatch')
        # Preserve all original replay and supervision methods; replace only owned
        # cursor/connection/branch metadata and supply an isolated accepted graph fork.
        result=copy.copy(proto)
        result.variant_id=variant_id
        result.folder=folder
        result.labels=labels
        result.runtime=OrganizationGraphRuntime(self.organization,proto.runtime.graph.fork())
        result.db=duckdb.connect(':memory:',config={'threads':2})
        columns={r[0] for r in result.db.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(observations)]).fetchall()}
        require(columns==set(OBSERVABLE),'Observable allowlist mismatch')
        result.cursor=result.db.cursor()
        result.cursor.execute('''SELECT organization,"Login Timestamp","User ID","IP Address",LoginSuccessful
            FROM read_parquet(?) ORDER BY "Login Timestamp","User ID","IP Address",LoginSuccessful''',[str(observations)])
        result._events=iter(result._rows(result.cursor))
        result._next=next(result._events,None)
        result._ordinal=0
        result._last_requested=None
        self.forks+=1
        return result

    def close(self):
        for seed,proto in self.prototypes.items():
            require(__import__('hashlib').sha256(proto.runtime.graph.checkpoint_bytes()).hexdigest()==self.parent_hashes[seed],
                    'Shared warm-up prototype changed during branch replay')
            proto.close()


def serialize_batch(batch,view,train_seen=None):
    layers=[]
    for packet,route in zip(batch.packets,batch.routing):
        layers.append(dict(x=packet.x,edge_index=packet.edge_index,num_nodes=int(packet.num_nodes),
                           source_rows=torch.from_numpy(route.source_rows.copy()),
                           destination_rows=torch.from_numpy(route.destination_rows.copy())))
    roots=batch.root_rows
    user_ids=[view.private_keys[int(row)][1] for row in roots]
    unseen_users=[uid not in train_seen['users'] if train_seen is not None else False for uid in user_ids]
    unseen_ips=[False]*len(roots)
    if train_seen is not None:
        route=batch.routing[-1]
        for source,target in batch.packets[-1].edge_index.T.tolist():
            kind,key=view.private_keys[int(route.source_rows[source])]
            if kind=='I' and key not in train_seen['ips']:
                unseen_ips[target]=True
    return dict(layers=layers,y=batch.supervision.y,mask=batch.supervision.eligible_mask,provenance=batch.provenance,
                user_ids=torch.tensor(user_ids,dtype=torch.int64),
                unseen_user=torch.tensor(unseen_users,dtype=torch.bool),unseen_ip=torch.tensor(unseen_ips,dtype=torch.bool))


def deserialize_batch(payload):
    packets=[];routing=[]
    for layer in payload['layers']:
        packets.append(Data(x=layer['x'],edge_index=layer['edge_index'],num_nodes=layer['num_nodes']))
        src,dst=layer['source_rows'].numpy(),layer['destination_rows'].numpy()
        src.setflags(write=False);dst.setflags(write=False)
        routing.append(Routing(src,dst))
    return ModelBatch(tuple(packets),tuple(routing),Supervision(payload['y'],payload['mask']),payload['provenance'])


def build_cache(pins,organization,split,output,expected_variants=171,train_seen=None,journal=None,limit=None):
    guarded_split(pins.protocol,split)
    require(not output.exists(),'Cache output exists; select a new run')
    output.mkdir(parents=True)
    manifests=sorted((pins.root/REPLAY).glob(f'CFV1*_{split}/replay_manifest.json'))
    jobs=[]
    # Glob filters TRAIN/VAL before opening any branch file; TEST is never opened.
    for path in manifests:
        m=load(pins.check(path))
        require(m['split']==split,'Unexpected split')
        jobs.append(m)
    jobs.sort(key=lambda m:(m['anchor'],m['variant_id']))
    require(len(jobs)==expected_variants,'Unexpected split inventory')
    if limit is not None:
        jobs=[m for m in jobs if m['variant_id'].startswith('CFV1_SO_CS_027_')][:limit]
        require(len(jobs)==limit,'Representative integration branch selection incomplete')
    factory=WarmupForks(pins,organization,split)
    records=[];positive=negative=masked=graph_context=0
    users=set();ips=set()
    try:
        for number,m in enumerate(jobs,1):
            with factory.open(m['variant_id']) as pipeline:
                for grid_index,t in enumerate(pipeline.grid):
                    sampler=pipeline.sampler(t)
                    states=pipeline.supervision_at(t)
                    view=sampler.view
                    for kind,key in view.private_keys:
                        (users if kind=='U' else ips).add(key)
                    roots=sampler.user_rows[view.x[sampler.user_rows,5]>0]
                    graph_context+=int(len(sampler.user_rows)-len(roots))
                    observable_users={view.private_keys[int(row)][1] for row in roots}
                    require(all(row['User ID'] in observable_users for row in states if row['supervision_eligible']),
                            'Eligible exact-grid User omitted from cache')
                    chunks=[]
                    for start in range(0,len(roots),pins.sampler_config['batch_size']):
                        batch=sampler.sample(roots[start:start+pins.sampler_config['batch_size']],states,pins.protocol)
                        y,mask=batch.supervision.y,batch.supervision.eligible_mask
                        positive+=int((y[mask]==1).sum());negative+=int((y[mask]==0).sum());masked+=int((~mask).sum())
                        chunks.append(serialize_batch(batch,view,train_seen))
                    expected_positive=sum(s['node_label']==1 for s in states)
                    expected_negative=sum(s['node_label']==0 for s in states)
                    require(sum(int((c['y'][c['mask']]==1).sum()) for c in chunks)==expected_positive and
                            sum(int((c['y'][c['mask']]==0).sum()) for c in chunks)==expected_negative,
                            'Exact-grid eligible census mismatch')
                    path=output/f'{m["variant_id"]}_grid{grid_index}.pt'
                    torch.save(chunks,path)
                    records.append(dict(path=path.name,sha256=sha(path),variant_id=m['variant_id'],asof=t.isoformat(),
                                        split=split,organization=organization,batches=len(chunks),recent_user_roots=len(roots)))
            if journal is not None and (number%6==0 or number==len(jobs)):
                journal(dict(event='cache_progress',organization=organization,split=split,branches_done=number,
                             branches_total=len(jobs),eligible_so_far=positive+negative))
    finally:
        factory.close()
    require(positive>0 and negative>0,'Training/validation split lacks both classes')
    manifest=dict(version='phase6-training-cache-v1',organization=organization,split=split,
        scope='FULL' if limit is None else 'REPRESENTATIVE_INTEGRATION',variants=len(jobs),grids=len(records),
        positive=positive,negative=negative,masked_recent_roots=masked,older_context_only_roots_not_forwarded=graph_context,
        seen_graph_users=len(users),seen_graph_ips=len(ips),warmup_prototypes=len(factory.prototypes),isolated_forks=factory.forks,
        sampler_config_sha256=sha(pins.sampler_path),feature_schema_sha256=sha(pins.schema_path),files=records)
    dump_json(output/'manifest.json',manifest)
    return manifest,dict(users=users,ips=ips)


def cached_batches(directory,protocol,split,organization,verify_files=False):
    guarded_split(protocol,split)
    manifest=load(directory/'manifest.json')
    require(manifest['split']==split and manifest['organization']==organization,'Cross-organization/split cache')
    for entry in manifest['files']:
        require(entry['split']==split and entry['organization']==organization,'Cache entry provenance mismatch')
        path=directory/entry['path']
        if verify_files:
            require(sha(path)==entry['sha256'],'Cached batch changed')
        for payload in torch.load(path,map_location='cpu',weights_only=True):
            provenance=payload['provenance']
            require(provenance['split']==split and provenance['organization']==organization and
                    provenance['variant_id']==entry['variant_id'] and provenance['asof']==entry['asof'],
                    'Cached batch temporal lineage mismatch')
            yield deserialize_batch(payload),payload
