"""Versioned organization-local rolling User-IP graph; no training or truth inputs.

Entity keys are stable; dense tensor row indices are local to an exported view.
Only active seven-day nodes are exported. Orphans and expired dedup tokens leave
the runtime. Both training_view and detection_view read the SAME persistent state.
"""
from __future__ import annotations
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import math
from functools import cached_property
from pathlib import Path

VERSION = 'rolling-user-ip-graph-v1'
HISTORY = timedelta(days=7)
RECENT = timedelta(minutes=10)
OBSERVABLE = ('organization', 'Login Timestamp', 'User ID', 'IP Address', 'LoginSuccessful')
FEATURES = ('total_logins', 'successful_logins', 'failed_logins', 'failure_ratio',
            'distinct_neighbors', 'recent_logins_10min', 'recent_distinct_neighbors_10min', 'node_type')


def require(ok, message):
    if not ok:
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class Event:
    token: str
    time: datetime
    user: int
    ip: str
    success: bool


class Window:
    def __init__(self):
        self.nodes = {}  # private (node type, local entity key) -> [attempts, successes]
        self.edges = Counter()
        self.degree = Counter()

    def add(self, e):
        u, ip, edge = ('U', e.user), ('I', e.ip), (e.user, e.ip)
        if not self.edges[edge]:
            self.degree[u] += 1
            self.degree[ip] += 1
        self.edges[edge] += 1
        for key in (u, ip):
            counts = self.nodes.setdefault(key, [0, 0])
            counts[0] += 1
            counts[1] += int(e.success)

    def remove(self, e):
        u, ip, edge = ('U', e.user), ('I', e.ip), (e.user, e.ip)
        require(self.edges[edge] > 0, 'Retention counter underflow')
        self.edges[edge] -= 1
        if not self.edges[edge]:
            del self.edges[edge]
            for key in (u, ip):
                self.degree[key] -= 1
                if not self.degree[key]:
                    del self.degree[key]
        for key in (u, ip):
            counts = self.nodes[key]
            counts[0] -= 1
            counts[1] -= int(e.success)
            require(0 <= counts[1] <= counts[0], 'Node counter underflow')
            if not counts[0]:
                del self.nodes[key]

    def fork(self):
        w = Window()
        w.nodes = {k: list(v) for k, v in self.nodes.items()}
        w.edges, w.degree = self.edges.copy(), self.degree.copy()
        return w


@dataclass(frozen=True)
class GraphView:
    organization: str
    asof: datetime
    private_keys: tuple
    x: object
    edge_index: object

    @cached_property
    def _content_digest(self):
        h = hashlib.sha256()
        h.update(json.dumps([self.organization, self.asof.isoformat(), self.private_keys],
                            separators=(',', ':')).encode())
        h.update(self.x.tobytes())
        h.update(self.edge_index.tobytes())
        return h.hexdigest()

    def digest(self):
        return self._content_digest

    def to_pyg(self):
        import torch
        from torch_geometric.data import Data
        data = Data(x=torch.from_numpy(self.x.copy()),
                    edge_index=torch.from_numpy(self.edge_index.copy()), num_nodes=len(self.private_keys))
        require(data.validate(raise_on_error=False), 'PyG view validation failed')
        require(set(data.keys()) == {'x', 'edge_index', 'num_nodes'}, 'Unexpected model packet fields')
        return data

    def supervision(self, states):
        """Evaluator join only. Neither labels nor masks become model features."""
        import numpy as np
        y = np.full(len(self.private_keys), -1, dtype=np.int64)
        lookup = {}
        active_users = {key for kind, key in self.private_keys if kind == 'U'}
        for row in states:
            require(row['organization'] == self.organization, 'Cross-organization supervision')
            require(row['label_time'] == self.asof, 'Supervision time must equal graph as-of time')
            uid = row['User ID']
            require(uid not in lookup, 'Duplicate User/time supervision')
            require(row['node_label'] in (-1, 0, 1), 'Invalid target label')
            require(row['node_label'] == -1 or uid in active_users, 'Supervised User missing from as-of graph')
            lookup[uid] = row['node_label']
        for i, (kind, key) in enumerate(self.private_keys):
            if kind == 'U':
                y[i] = lookup.get(key, -1)
        return y, y != -1


class RollingGraph:
    def __init__(self, organization):
        require(organization in {f'Org{i}' for i in range(1, 6)}, 'Unknown organization')
        self.organization = organization
        self.clock = None
        self.history_events, self.recent_events = deque(), deque()
        self.retained, self.recent = Window(), Window()
        self.seen = set()  # bounded to retained events, not a permanent identity index
        self._view_cache = None

    def advance(self, time):
        require(isinstance(time, datetime) and time.tzinfo is None, 'Expected naive source timestamp')
        require(self.clock is None or time >= self.clock, 'Cannot rewind graph state')
        while self.recent_events and self.recent_events[0].time <= time - RECENT:
            self.recent.remove(self.recent_events.popleft())
        while self.history_events and self.history_events[0].time <= time - HISTORY:
            e = self.history_events.popleft()
            self.retained.remove(e)
            self.seen.remove(e.token)
        self.clock = time
        self._view_cache = None

    def ingest_batch(self, time, observations, tokens):
        """Atomic timestamp batch. Duplicate IDs/out-of-order data fail before mutation.

        Token is a private ingestion identifier, never a feature. All equal-time
        events must arrive together; a later batch cannot append to a closed time.
        """
        require(self.clock is None or time > self.clock, 'Late/repeated timestamp batch')
        require(len(observations) == len(tokens) and len(observations) > 0, 'Empty/mismatched batch')
        require(len(set(tokens)) == len(tokens) and not self.seen.intersection(tokens), 'Duplicate event token')
        parsed = []
        for row, token in zip(observations, tokens):
            require(set(row) == set(OBSERVABLE), 'Only observable columns may enter graph state')
            require(row['organization'] == self.organization, 'Cross-organization event')
            require(row['Login Timestamp'] == time, 'Batch contains another timestamp')
            require(type(row['User ID']) is int, 'User ID must be an integer graph key')
            require(isinstance(row['IP Address'], str) and row['IP Address'], 'Missing IP graph key')
            require(type(row['LoginSuccessful']) is bool, 'Unknown login outcome')
            require(isinstance(token, str) and token, 'Missing ingestion token')
            parsed.append(Event(token, time, row['User ID'], row['IP Address'], row['LoginSuccessful']))
        self.advance(time)
        for e in parsed:
            self.retained.add(e)
            self.recent.add(e)
            self.history_events.append(e)
            self.recent_events.append(e)
            self.seen.add(e.token)

    def fork(self):
        child = RollingGraph(self.organization)
        child.clock = self.clock
        child.history_events, child.recent_events = deque(self.history_events), deque(self.recent_events)
        child.retained, child.recent = self.retained.fork(), self.recent.fork()
        child.seen = self.seen.copy()
        child._view_cache = self._view_cache
        return child

    def view(self):
        import numpy as np
        require(self.clock is not None, 'Graph clock not initialized')
        if self._view_cache is not None:
            return self._view_cache
        # Stable entity keys; bounded active tensors. No lifetime orphan registry.
        keys = tuple(sorted(self.retained.nodes, key=lambda k: (0 if k[0] == 'U' else 1, k[1])))
        index = {key: i for i, key in enumerate(keys)}
        x = np.zeros((len(keys), len(FEATURES)), dtype=np.float32)
        if keys:
            counts = np.asarray([self.retained.nodes[k] for k in keys], dtype=np.float64)
            n, successful = counts[:,0], counts[:,1]
            degree = np.fromiter((self.retained.degree[k] for k in keys), dtype=np.float64)
            recent = np.fromiter((self.recent.nodes.get(k,(0,0))[0] for k in keys), dtype=np.float64)
            recent_degree = np.fromiter((self.recent.degree[k] for k in keys), dtype=np.float64)
            x[:] = np.column_stack((np.log1p(n),np.log1p(successful),np.log1p(n-successful),
                (n-successful)/n,np.log1p(degree),np.log1p(recent),np.log1p(recent_degree),
                np.fromiter((0 if k[0]=='U' else 1 for k in keys),dtype=np.float64)))
        edges = [(index[('U', u)], index[('I', ip)]) for u, ip in sorted(self.retained.edges)]
        directed = edges + [(b, a) for a, b in edges]
        edge_index = np.array(directed, dtype=np.int64).T if directed else np.empty((2, 0), dtype=np.int64)
        require(np.isfinite(x).all(), 'Non-finite observable features')
        # Immutable byte-backed arrays make cached model views safe from accidental
        # caller mutation. Updating the graph invalidates this cache.
        x = np.frombuffer(x.tobytes(),dtype=np.float32).reshape(x.shape)
        edge_index = np.frombuffer(edge_index.tobytes(),dtype=np.int64).reshape(edge_index.shape)
        self._view_cache = GraphView(self.organization, self.clock, keys, x, edge_index)
        return self._view_cache

    def checkpoint_bytes(self):
        require(self.clock is not None, 'Cannot checkpoint an uninitialized graph')
        payload = {'version': VERSION, 'organization': self.organization, 'clock': self.clock.isoformat(),
            'events': [[e.token, e.time.isoformat(), e.user, e.ip, e.success] for e in self.history_events]}
        body = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
        wrapper = {'payload': payload, 'sha256': hashlib.sha256(body).hexdigest()}
        return gzip.compress(json.dumps(wrapper, separators=(',', ':')).encode(), mtime=0)

    @classmethod
    def from_checkpoint_bytes(cls, data):
        from itertools import groupby
        wrapper = json.loads(gzip.decompress(data))
        payload = wrapper['payload']
        body = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
        require(hashlib.sha256(body).hexdigest() == wrapper['sha256'], 'Checkpoint content hash mismatch')
        require(payload['version'] == VERSION, 'Checkpoint schema version mismatch')
        graph = cls(payload['organization'])
        clock = datetime.fromisoformat(payload['clock'])
        for timestamp, group in groupby(payload['events'], key=lambda r: r[1]):
            rows = list(group); t = datetime.fromisoformat(timestamp)
            require(clock-HISTORY < t <= clock, 'Checkpoint contains expired/future events')
            obs = [dict(zip(OBSERVABLE, [graph.organization, t, r[2], r[3], r[4]])) for r in rows]
            graph.ingest_batch(t, obs, [r[0] for r in rows])
        graph.advance(clock)
        return graph


class OrganizationGraphRuntime:
    """Accepted versioned graph integration API for later model implementation.

    The legacy cumulative builder/updater are not called. The detector and future
    trainer share one RollingGraph instance; exporting a tensor view does not
    rebuild independent temporal graph states or perform per-event retraining.
    """
    def __init__(self, organization, graph=None):
        self.graph = graph or RollingGraph(organization)
        require(self.graph.organization == organization, 'Runtime organization mismatch')

    def apply_timestamp_batch(self, time, observations, tokens):
        self.graph.ingest_batch(time, observations, tokens)

    def advance(self, time):
        self.graph.advance(time)

    def detection_view(self):
        return self.graph.view()

    def training_view(self):
        return self.graph.view()
