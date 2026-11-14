"""Organization-local event-to-alert service over the unchanged rolling graph.

Complete timestamp batches, no labels, no optimizer. SQLite commits commands and
decisions together; accepted graph checkpoints plus committed journal enable recovery.
"""
from datetime import datetime,timedelta
import hashlib,json,math,sqlite3,time,threading
from pathlib import Path
import numpy as np
import torch
from src.organization.rolling_graph_v1 import RollingGraph,OrganizationGraphRuntime,OBSERVABLE,HISTORY,RECENT
from src.phase6.input_pipeline import TemporalNeighborSampler
from src.phase6.temporal_protocol import require,bounds
from src.phase6.fpr_calibration import decisions,canonical_digest

def closure(adjacency,nodes,hops=2):
    seen=set(nodes);front=set(nodes)
    for _ in range(hops):
        front={other for node in front for other in adjacency.get(node,())}-seen;seen.update(front)
    return {key[1] for key in seen if key[0]=='U'}

def adjacent(graph):
    result={}
    for user,ip in graph.retained.edges:
        u,i=('U',user),('I',ip);result.setdefault(u,set()).add(i);result.setdefault(i,set()).add(u)
    return result

class LocalInference:
    def __init__(self,db_path,organization,stream_id,registry,config,initial_graph=None,split='VAL',source_identity=None):
        require(split=='VAL','Subphase 6 proof accepts VAL only; TEST scoring is sealed')
        require(registry.organization==organization,'Nonlocal registry')
        self.organization,self.stream_id,self.registry,self.config,self.split=organization,stream_id,registry,config,split
        self.bundle=registry.current;self.lock=threading.RLock();self.faulted=False;self.recovered_commands=0
        require(isinstance(stream_id,str) and stream_id,'Missing private stream namespace')
        db_path=Path(db_path);db_path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(db_path));self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS commands(seq INTEGER PRIMARY KEY,asof TEXT NOT NULL,trigger TEXT NOT NULL,payload TEXT NOT NULL,event_offset INTEGER NOT NULL,view_digest TEXT NOT NULL,timings TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS event_tokens(token TEXT PRIMARY KEY,seq INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS scores(seq INTEGER NOT NULL,user_id INTEGER NOT NULL,asof TEXT NOT NULL,trigger TEXT NOT NULL,logit REAL NOT NULL,logit_hex TEXT NOT NULL,probability REAL NOT NULL,threshold_hex TEXT,decision TEXT NOT NULL,alert_id TEXT,model_sha256 TEXT NOT NULL,threshold_sha256 TEXT NOT NULL,schema_sha256 TEXT NOT NULL,processing_status TEXT NOT NULL,inference_seconds REAL NOT NULL,PRIMARY KEY(seq,user_id));
          CREATE TABLE IF NOT EXISTS checkpoints(seq INTEGER PRIMARY KEY,graph BLOB NOT NULL,sha256 TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS failures(id INTEGER PRIMARY KEY,asof TEXT,phase TEXT NOT NULL,error_type TEXT NOT NULL,message TEXT NOT NULL,requires_restart INTEGER NOT NULL);''')
        identity=dict(format='phase6-local-inference-store-v1',organization=organization,stream_id=stream_id,split=split,
                      bundle=self.bundle.identity,config_sha256=canonical_digest(config),source_identity=source_identity)
        row=self.db.execute("SELECT value FROM meta WHERE key='identity'").fetchone()
        if row is None:
            require(initial_graph is not None and initial_graph.organization==organization,'New store needs local causal warm-up graph')
            blob=initial_graph.checkpoint_bytes()
            with self.db:
                self.db.execute('INSERT INTO meta VALUES (?,?)',('identity',json.dumps(identity,sort_keys=True)))
                self.db.execute('INSERT INTO checkpoints VALUES (?,?,?)',(0,blob,hashlib.sha256(blob).hexdigest()))
            graph=initial_graph;self.seq=0;self.input_offset=0
        else:
            require(json.loads(row[0])==identity,'Restart bundle/organization/schema/config/source identity mismatch')
            cp=self.db.execute('SELECT seq,graph,sha256 FROM checkpoints ORDER BY seq DESC LIMIT 1').fetchone()
            require(cp is not None and hashlib.sha256(cp[1]).hexdigest()==cp[2],'Graph checkpoint integrity failure')
            graph=RollingGraph.from_checkpoint_bytes(cp[1]);require(graph.organization==organization,'Cross-organization checkpoint')
            for _,asof,payload in self.db.execute('SELECT seq,asof,payload FROM commands WHERE seq>? ORDER BY seq',(cp[0],)):
                command=json.loads(payload);t=datetime.fromisoformat(asof)
                if command['observations']:
                    rows=[dict(r,**{'Login Timestamp':datetime.fromisoformat(r['Login Timestamp'])}) for r in command['observations']]
                    graph.ingest_batch(t,rows,command['tokens'])
                else:graph.advance(t)
                self.recovered_commands+=1
            last=self.db.execute('SELECT seq,event_offset,view_digest FROM commands ORDER BY seq DESC LIMIT 1').fetchone()
            self.seq,self.input_offset=(last[0],last[1]) if last else (0,0)
            if last:require(graph.view().digest()==last[2],'Recovered committed state digest differs')
        self.runtime=OrganizationGraphRuntime(organization,graph);self.adjacency=adjacent(graph);self.graph_object_id=id(graph)
        self.last_time=graph.clock

    def _failure(self,asof,phase,error):
        if self.db.in_transaction:self.db.rollback()
        with self.db:self.db.execute('INSERT INTO failures(asof,phase,error_type,message,requires_restart) VALUES (?,?,?,?,?)',
            (asof.isoformat() if isinstance(asof,datetime) else None,phase,type(error).__name__,str(error),int(self.faulted)))

    def _preflight(self,t,rows,tokens):
        require(not self.faulted,'Client faulted; restart from committed state before further input')
        require(isinstance(t,datetime) and t.tzinfo is None,'Expected naive source timestamp')
        lo,hi=bounds(self.bundle.protocol,self.split);require(lo<=t<hi,'Scoring outside authorized VAL interval')
        require(self.runtime.graph.clock is None or t>self.runtime.graph.clock,'Out-of-order or closed timestamp batch')
        require(len(rows)==len(tokens) and len(set(tokens))==len(tokens),'Mismatched or duplicate tokens')
        for r,token in zip(rows,tokens):
            require(set(r)==set(OBSERVABLE),'Only observable authentication columns are accepted')
            require(r['organization']==self.organization and r['Login Timestamp']==t,'Nonlocal/mixed timestamp batch')
            require(type(r['User ID'])is int and isinstance(r['IP Address'],str) and r['IP Address'] and type(r['LoginSuccessful'])is bool,'Invalid observable event')
            require(isinstance(token,str) and token and token not in self.runtime.graph.seen,'Duplicate/invalid ingestion token')
            require(self.db.execute('SELECT 1 FROM event_tokens WHERE token=?',(token,)).fetchone() is None,'Duplicate committed event token')

    def _changed(self,t,rows):
        changed={};pairs=set()
        def add(user,ip):changed[('U',user)]=True;changed[('I',ip)]=True;pairs.add((user,ip))
        for r in rows:add(r['User ID'],r['IP Address'])
        for events,duration in [(self.runtime.graph.recent_events,RECENT),(self.runtime.graph.history_events,HISTORY)]:
            for event in events:
                if event.time>t-duration:break
                add(event.user,event.ip)
        return set(changed),pairs

    def _refresh_index(self,pairs):
        for user,ip in pairs:
            u,i=('U',user),('I',ip)
            if (user,ip) in self.runtime.graph.retained.edges:
                self.adjacency.setdefault(u,set()).add(i);self.adjacency.setdefault(i,set()).add(u)
            else:
                for a,b in [(u,i),(i,u)]:
                    if a in self.adjacency:
                        self.adjacency[a].discard(b)
                        if not self.adjacency[a]:del self.adjacency[a]

    def _predict(self,view,users):
        if not users:return [],0.
        cfg=self.bundle.sampler
        sampler=TemporalNeighborSampler(view,self.stream_id,self.split,tuple(cfg['fanouts_model_order']),cfg['seed'],self.bundle.protocol)
        index={key:i for i,key in enumerate(view.private_keys)}
        roots=np.asarray([index[('U',u)] for u in users],dtype=np.int64)
        values=[];start=time.perf_counter()
        with torch.inference_mode():
            for a in range(0,len(roots),cfg['batch_size']):
                batch=sampler.sample(roots[a:a+cfg['batch_size']]) # all supervision masked; no label input
                values.extend(self.bundle.model(batch).numpy().tolist())
        return values,time.perf_counter()-start

    def process_batch(self,t,observations,tokens,heartbeat=False,final=False):
        if not observations:
            error=ValueError('Use tick() for a clock-only command')
            with self.lock:self._failure(t,'preflight',error)
            raise error
        return self._process(t,observations,tokens,heartbeat,final)

    def tick(self,t,final=False):return self._process(t,[],[],True,final)

    def _process(self,t,rows,tokens,heartbeat,final):
        with self.lock:
            started=time.perf_counter();dirty=False;phase='preflight'
            try:
                self._preflight(t,rows,tokens)
                changed,pairs=self._changed(t,rows);users=closure(self.adjacency,changed)
                phase='graph_update';clock=time.perf_counter()
                if rows:self.runtime.apply_timestamp_batch(t,rows,tokens)
                else:self.runtime.advance(t)
                dirty=True;graph_seconds=time.perf_counter()-clock
                self._refresh_index(pairs);users|=closure(self.adjacency,changed)
                users={u for u in users if ('U',u) in self.runtime.graph.retained.nodes}
                if heartbeat:users.update(key[1] for key in self.runtime.graph.recent.nodes if key[0]=='U')
                users=sorted(users);phase='features_and_scoring';clock=time.perf_counter()
                view=self.runtime.detection_view();require(view.asof==t,'Noncausal feature view')
                logits,scoring_seconds=self._predict(view,users)
                require(len(logits)==len(users) and np.isfinite(logits).all(),'Invalid scoring output')
                feature_seconds=time.perf_counter()-clock-scoring_seconds
                alerts=decisions(np.asarray(logits,dtype=np.float64),self.bundle.threshold)
                trigger='final' if final else 'event_and_heartbeat' if rows and heartbeat else 'event' if rows else 'heartbeat'
                seq=self.seq+1;offset=self.input_offset+len(rows);identity=self.bundle.identity
                score_rows=[]
                for user,logit,alert in zip(users,logits,alerts):
                    logit=float(logit);probability=1/(1+math.exp(-max(-700.,min(700.,logit))))
                    alert_id=hashlib.sha256(json.dumps([self.organization,self.stream_id,t.isoformat(),user,self.bundle.fingerprint]).encode()).hexdigest() if alert else None
                    score_rows.append((seq,user,t.isoformat(),trigger,logit,logit.hex(),probability,self.bundle.threshold['hex'],'ALERT' if alert else 'NO_ALERT',alert_id,identity['model_sha256'],identity['threshold_sha256'],identity['feature_schema_sha256'],'OK',scoring_seconds))
                payload=dict(observations=[dict(r,**{'Login Timestamp':r['Login Timestamp'].isoformat()}) for r in rows],tokens=tokens,heartbeat=heartbeat,final=final)
                timings=dict(graph_update_seconds=graph_seconds,feature_and_sampler_seconds=feature_seconds,model_scoring_seconds=scoring_seconds,precommit_processing_seconds=time.perf_counter()-started,scored_users=len(users),input_events=len(rows))
                phase='atomic_persistence';self.db.execute('BEGIN IMMEDIATE')
                self.db.execute('INSERT INTO commands VALUES (?,?,?,?,?,?,?)',(seq,t.isoformat(),trigger,json.dumps(payload,separators=(',',':')),offset,view.digest(),json.dumps(timings)))
                self.db.executemany('INSERT INTO event_tokens VALUES (?,?)',[(token,seq) for token in tokens])
                self.db.executemany('INSERT INTO scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',score_rows)
                if seq%self.config['persistence']['checkpoint_every_commits']==0 or final:
                    blob=self.runtime.graph.checkpoint_bytes();self.db.execute('INSERT INTO checkpoints VALUES (?,?,?)',(seq,blob,hashlib.sha256(blob).hexdigest()))
                self.db.commit();self.seq=seq;self.input_offset=offset;self.last_time=t
                require(id(self.runtime.graph)==self.graph_object_id,'Persistent graph was replaced during processing')
                return dict(seq=seq,asof=t.isoformat(),trigger=trigger,input_events=len(rows),scored_users=len(users),alerts=int(alerts.sum()),
                    no_alerts=len(users)-int(alerts.sum()),elapsed_seconds=time.perf_counter()-started,**{k:v for k,v in timings.items() if k not in {'scored_users','input_events'}})
            except Exception as error:
                self.faulted=self.faulted or dirty;self._failure(t,phase,error);raise

    def try_model_candidate(self,candidate):
        with self.lock:
            result=self.registry.try_candidate(candidate)
            if result['status'].startswith('REJECTED'):
                self._failure(self.last_time,'model_registry',ValueError(result['message']))
            else:self.bundle=self.registry.current
            return result

    def decision_digest(self):
        h=hashlib.sha256()
        for row in self.db.execute('SELECT seq,user_id,asof,trigger,logit_hex,threshold_hex,decision,alert_id,model_sha256,threshold_sha256,schema_sha256,processing_status FROM scores ORDER BY seq,user_id'):
            h.update((json.dumps(row,separators=(',',':'))+'\n').encode())
        return h.hexdigest()

    def close(self):self.db.close()
