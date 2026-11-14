"""Versioned as-of GraphSAGE input pipeline. No model, optimizer or fitting.

Layer packets contain only the accepted observable tensor fields. Routing,
private identities, temporal provenance and root supervision stay separate.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
from itertools import groupby
import json
from pathlib import Path

import numpy as np

from src.organization.rolling_graph_v1 import FEATURES, OBSERVABLE, OrganizationGraphRuntime
from src.phase6.readiness import FREEZE, REPLAY, load, sha
from src.phase6.temporal_protocol import bounds, require, require_use, scoring_times, validate_branch, validate_target

PROTOCOL_SHA256 = '9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b'


class PinnedInputs:
    """One run's read-only hash cache; verify again at run close for preservation."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.protocol = load(self.root / 'configs/phase6/split_protocol_v1.json')
        require(sha(self.root / 'configs/phase6/split_protocol_v1.json') == PROTOCOL_SHA256, 'Frozen protocol changed')
        require(sha(self.root / self.protocol['data_contract']) == self.protocol['data_contract_sha256'], 'Accepted contract changed')
        require(sha(self.root / FREEZE) == self.protocol['dataset_freeze_sha256'], 'Dataset freeze changed')
        self.schema_path = self.root / 'configs/phase6/feature_allowlist_v1.json'
        self.sampler_path = self.root / 'configs/phase6/neighbor_sampling_v1.json'
        self.schema, self.sampler_config = load(self.schema_path), load(self.sampler_path)
        require(tuple(f['name'] for f in self.schema['features']) == FEATURES, 'Feature order differs from accepted runtime')
        require(sha(self.root / 'src/organization/rolling_graph_v1.py') == self.schema['runtime_sha256'], 'Accepted runtime changed')
        require(self.sampler_config['num_layers'] == len(self.sampler_config['fanouts_model_order']), 'Layer/fanout mismatch')
        self.frozen = {Path(f['path_relative_to_project']).as_posix(): f for f in load(self.root / FREEZE)['files']}
        self.checked = {}
        self.configuration_hashes = {p.relative_to(self.root).as_posix(): sha(p) for p in [
            self.schema_path, self.sampler_path, self.root/'configs/phase6/split_protocol_v1.json',
            self.root/'src/phase6/temporal_protocol.py', self.root/'src/organization/rolling_graph_v1.py']}

    def check(self, path):
        path = Path(path).resolve()
        require(path.is_relative_to(self.root), 'Input path outside project')
        key = path.relative_to(self.root).as_posix()
        if key not in self.checked:
            entry = self.frozen.get(key)
            require(entry is not None, 'Input absent from frozen inventory: ' + key)
            digest = sha(path)
            require(digest == entry['sha256'] and path.stat().st_size == entry['size_bytes'], 'Frozen input changed: ' + key)
            self.checked[key] = digest
        return path

    def verify_unchanged(self):
        for key, digest in {**self.configuration_hashes, **self.checked}.items():
            require(sha(self.root/key) == digest, 'Input/config changed during run: ' + key)


@dataclass(frozen=True)
class Routing:
    source_rows: np.ndarray  # Private dense rows in this immutable view, never input embeddings.
    destination_rows: np.ndarray


@dataclass(frozen=True)
class Supervision:
    y: object
    eligible_mask: object


@dataclass(frozen=True)
class ModelBatch:
    packets: tuple  # PyG Data, one observable-only packet per model layer.
    routing: tuple
    supervision: Supervision
    provenance: dict

    @property
    def root_rows(self):
        return self.routing[-1].destination_rows


class TemporalNeighborSampler:
    """Deterministic CSR sampling over one immutable, as-of bipartite view."""
    def __init__(self, view, variant_id, split, fanouts=(15, 10), seed=60201, protocol=None):
        require(view.organization in {f'Org{i}' for i in range(1,6)}, 'Unknown organization')
        require(split in {'TRAIN','VAL','TEST'} and isinstance(variant_id,str) and variant_id, 'Missing branch provenance')
        require(isinstance(view.asof,datetime) and view.asof.tzinfo is None, 'Expected naive as-of timestamp')
        protocol=protocol or load(Path(__file__).resolve().parents[2]/'configs/phase6/split_protocol_v1.json')
        lo,hi=bounds(protocol,split)
        require(lo<=view.asof<hi,'Snapshot outside chronological split')
        require(type(seed) is int and seed >= 0, 'Invalid sampler seed')
        require(len(fanouts)>0 and all(type(n) is int and n>0 for n in fanouts), 'Fanouts must be positive integers')
        x, edges, n = view.x, view.edge_index, len(view.private_keys)
        require(x.dtype == np.float32 and x.shape == (n,len(FEATURES)) and np.isfinite(x).all(), 'Invalid feature schema/dtype')
        require(edges.dtype == np.int64 and edges.ndim==2 and edges.shape[0]==2, 'Invalid edge tensor')
        require(not x.flags.writeable and not edges.flags.writeable, 'Snapshot tensors must be immutable')
        kinds = np.fromiter((0 if k[0]=='U' else 1 if k[0]=='I' else -1 for k in view.private_keys), dtype=np.int8, count=n)
        require(np.array_equal(x[:,7], kinds) and (kinds>=0).all(), 'Node-type/schema mismatch')
        require(len(set(view.private_keys)) == n, 'Duplicate private node keys')
        if edges.size:
            require(edges.min()>=0 and edges.max()<n, 'Edge index outside graph')
            require((kinds[edges[0]] != kinds[edges[1]]).all(), 'Non-bipartite edge')
            encoded = np.sort(edges[0]*n+edges[1])
            require(not (encoded[1:]==encoded[:-1]).any(), 'Duplicate adjacency')
            require(np.array_equal(encoded, np.sort(edges[1]*n+edges[0])), 'Missing reverse User-IP edge')
        self.view, self.variant_id, self.split = view, variant_id, split
        self.fanouts, self.seed = tuple(fanouts), seed
        order = np.lexsort((edges[0],edges[1]))
        self.neighbors = edges[0,order]
        self.indptr = np.empty(n+1,dtype=np.int64)
        self.indptr[0]=0
        np.cumsum(np.bincount(edges[1],minlength=n),out=self.indptr[1:])
        self.user_rows = np.flatnonzero(kinds==0)

    def _neighbors(self, node, layer):
        neighbors = self.neighbors[self.indptr[node]:self.indptr[node+1]]
        count = self.fanouts[layer]
        if len(neighbors)<=count:
            return neighbors
        payload = [self.view.organization,self.variant_id,self.view.asof.isoformat(),self.seed,layer,self.view.private_keys[node]]
        digest = hashlib.sha256(json.dumps(payload,separators=(',',':')).encode()).digest()
        rng = np.random.Generator(np.random.PCG64(int.from_bytes(digest[:16],'little')))
        return np.sort(rng.choice(neighbors,size=count,replace=False))

    def _supervision(self, states, protocol):
        states=list(states)
        if states:
            require(protocol is not None, 'Supervision requires split protocol')
            for row in states:
                validate_target(protocol,row,self.view.organization,self.split,self.view.asof)
                require(row.get('variant_id',self.variant_id)==self.variant_id, 'Cross-branch supervision')
        y,mask = self.view.supervision(states)
        if states:
            require(all(row['supervision_eligible']==(row['node_label']!=-1) for row in states), 'Mask mismatch')
        return y,mask

    def sample(self, roots, states=(), protocol=None):
        return self._sample(roots,*self._supervision(states,protocol))

    def _sample(self, roots, y, mask):
        import torch
        from torch_geometric.data import Data
        roots = np.asarray(roots)
        require(roots.ndim==1 and roots.dtype.kind in 'iu' and len(roots)>0 and len(np.unique(roots))==len(roots), 'Empty, noninteger or duplicate User roots')
        require(roots.min()>=0 and roots.max()<len(self.view.private_keys), 'Root outside graph')
        roots=roots.astype(np.int64,copy=False)
        require((self.view.x[roots,7]==0).all(), 'Only User nodes may be targets')
        # No label or mask affects root expansion or neighbor selection.
        destination=roots.copy()
        blocks=[]
        for layer in reversed(range(len(self.fanouts))):
            choices=[self._neighbors(int(node),layer) for node in destination]
            sampled=np.concatenate(choices) if choices else np.empty(0,dtype=np.int64)
            extra=np.setdiff1d(np.unique(sampled),destination,assume_unique=False)
            source=np.concatenate((destination,extra))
            index={int(node):i for i,node in enumerate(source)}
            source_indices=[index[int(node)] for neighbors in choices for node in neighbors]
            target_indices=np.repeat(np.arange(len(destination),dtype=np.int64),[len(a) for a in choices])
            edge_index=np.vstack((np.asarray(source_indices,dtype=np.int64),target_indices))
            packet=Data(x=torch.from_numpy(self.view.x[source].copy()),
                        edge_index=torch.from_numpy(edge_index),num_nodes=len(source))
            require(set(packet.keys())=={'x','edge_index','num_nodes'}, 'Model packet metadata leak')
            source.setflags(write=False); destination.setflags(write=False)
            blocks.append((packet,Routing(source,destination)))
            destination=source
        blocks.reverse()
        return ModelBatch(tuple(p for p,r in blocks),tuple(r for p,r in blocks),
            Supervision(torch.from_numpy(y[roots].copy()),torch.from_numpy(mask[roots].copy())),
            dict(organization=self.view.organization,variant_id=self.variant_id,split=self.split,
                 asof=self.view.asof.isoformat(),retained_interval='(t-7 days,t]',recent_interval='(t-10 minutes,t]',
                 seed=self.seed,fanouts_model_order=list(self.fanouts),numpy_version=np.__version__))

    def batches(self, batch_size=256, states=(), protocol=None):
        require(type(batch_size) is int and batch_size>0, 'Invalid batch size')
        y,mask=self._supervision(states,protocol)
        for start in range(0,len(self.user_rows),batch_size):
            yield self._sample(self.user_rows[start:start+batch_size],y,mask)


class BranchPipeline:
    """Chronological cursor into one frozen branch and one persistent local runtime."""
    def __init__(self, pins, variant_id, organization, purpose='integrity_audit'):
        import duckdb
        require(organization in pins.protocol['organizations'], 'Unknown organization')
        require(isinstance(variant_id,str) and Path(variant_id).name==variant_id, 'Invalid branch path')
        self.pins, self.variant_id, self.organization = pins, variant_id, organization
        self.folder=pins.root/REPLAY/variant_id
        manifest=load(pins.check(self.folder/'replay_manifest.json'))
        require(manifest['variant_id']==variant_id, 'Branch identity mismatch')
        self.split, self.purpose=manifest['split'],purpose
        require_use(pins.protocol,self.split,purpose)
        branches=[b for b in manifest['branches'] if b['organization']==organization]
        require(len(branches)==1, 'Missing/duplicate organization branch')
        branch=branches[0]
        self.anchor=datetime.fromisoformat(manifest['anchor'])
        self.end=datetime.fromisoformat(manifest['end_exclusive'])
        self.grid=scoring_times(pins.protocol,self.anchor)
        ref=load(pins.check(pins.root/REPLAY/branch['history_reference']))
        require(ref['organization']==organization and ref['block']==f"{self.split}_SEED{manifest['seed']}", 'History provenance mismatch')
        validate_branch(pins.protocol,self.split,self.anchor,self.end,
                        datetime.fromisoformat(ref['history_start_inclusive']),datetime.fromisoformat(ref['history_end_exclusive']))
        observations=pins.check(self.folder/f'{organization}_observations.parquet')
        self.labels=pins.check(self.folder/f'{organization}_labels.parquet')
        require(sha(observations)==branch['observations_parquet_sha256'] and sha(self.labels)==branch['labels_parquet_sha256'], 'Branch tensor source mismatch')
        self.db=duckdb.connect(':memory:',config={'threads':2})
        self.runtime=OrganizationGraphRuntime(organization)
        files=[pins.check(pins.root/f).as_posix() for f in ref['source_files_relative_to_root']]
        columns={r[0] for r in self.db.execute('DESCRIBE SELECT * FROM read_parquet(?)',[files]).fetchall()}
        success='LoginSuccessful' if 'LoginSuccessful' in columns else 'Login Successful'
        history=self.db.execute(f'''SELECT CAST("Login Timestamp" AS TIMESTAMP),CAST("User ID" AS BIGINT),
            CAST("IP Address" AS VARCHAR),CAST("{success}" AS BOOLEAN) FROM read_parquet(?)
            WHERE CAST("Login Timestamp" AS TIMESTAMP)>=? AND CAST("Login Timestamp" AS TIMESTAMP)<? ORDER BY 1,2,3,4''',
            [files,self.anchor-timedelta(days=7),self.anchor])
        self._history_count=0
        for t,group in groupby(self._rows(history),key=lambda r:r[0]):
            rows=list(group)
            obs=[dict(zip(OBSERVABLE,[organization,t,*r[1:]])) for r in rows]
            tokens=[f'H_{self._history_count+i}' for i in range(len(rows))]
            self.runtime.apply_timestamp_batch(t,obs,tokens)
            self._history_count+=len(rows)
        require(self._history_count==ref['history_event_count'], 'Historical context count changed')
        schema={r[0] for r in self.db.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(observations)]).fetchall()}
        require(schema==set(OBSERVABLE), 'Observation column allowlist violated')
        # A separate cursor prevents exact-label queries from disturbing the event stream.
        self.cursor=self.db.cursor()
        self.cursor.execute('''SELECT organization,"Login Timestamp","User ID","IP Address",LoginSuccessful
            FROM read_parquet(?) ORDER BY "Login Timestamp","User ID","IP Address",LoginSuccessful''',[str(observations)])
        self._events=iter(self._rows(self.cursor))
        self._next=next(self._events,None)
        self._ordinal=0
        self._last_requested=None

    @staticmethod
    def _rows(cursor):
        while True:
            rows=cursor.fetchmany(4096)
            if not rows:
                return
            yield from rows

    def snapshot(self, t):
        require(t in self.grid, 'Scoring timestamp outside frozen grid')
        require(self._last_requested is None or t>=self._last_requested, 'Cannot rewind branch')
        while self._next is not None and self._next[1]<=t:
            time=self._next[1]
            require(self.anchor<=time<self.end, 'Replay event outside branch interval')
            batch=[]
            while self._next is not None and self._next[1]==time:
                batch.append(dict(zip(OBSERVABLE,self._next)))
                self._next=next(self._events,None)
            tokens=[f'R_{self._ordinal+i}' for i in range(len(batch))]
            self.runtime.apply_timestamp_batch(time,batch,tokens)
            self._ordinal+=len(batch)
        self.runtime.advance(t)
        self._last_requested=t
        return self.runtime.training_view()  # detection_view reads this same state.

    def supervision_at(self,t):
        require(t in self.grid and self.runtime.graph.clock==t, 'Labels must join current graph clock')
        cursor=self.db.execute('''SELECT * FROM read_parquet(?) WHERE label_time=?
            AND contains(query_kind,'grid_snapshot') ORDER BY "User ID"''',[str(self.labels),t])
        columns=[d[0] for d in cursor.description]
        rows=[dict(zip(columns,row)) for row in cursor.fetchall()]
        for row in rows:
            validate_target(self.pins.protocol,row,self.organization,self.split,t)
            require(row['variant_id']==self.variant_id, 'Cross-branch label')
        return rows

    def sampler(self,t,seed=None):
        view=self.snapshot(t)
        config=self.pins.sampler_config
        return TemporalNeighborSampler(view,self.variant_id,self.split,tuple(config['fanouts_model_order']),
                                       config['seed'] if seed is None else seed)

    def close(self):
        self.cursor.close()
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()
