"""Gated observable-only TEST loader. Labels are never opened by this loader."""
from datetime import datetime,timedelta
from itertools import groupby
import hashlib
from pathlib import Path
from src.organization.rolling_graph_v1 import OBSERVABLE,OrganizationGraphRuntime
from src.phase6.readiness import REPLAY,load,sha
from src.phase6.temporal_protocol import require,validate_branch,bounds

def load_stream(pins,variant_id,organization,split='TEST',*,scope):
    scope.assert_ready()
    require(Path(pins.root).resolve()==scope.root,'Scope/root mismatch')
    require(split=='TEST' and variant_id.endswith('_TEST') and Path(variant_id).name==variant_id,'Held-out loader accepts TEST only')
    require(organization in pins.protocol['organizations'],'Unknown organization')
    import duckdb
    scope.check_variant(variant_id,organization)
    class ScopedPins:
        def __init__(self,base):self.base=base;self.root=base.root;self.protocol=base.protocol
        def check(self,path):
            scope.check_input(path,variant_id,organization)
            return self.base.check(path)
    pins=ScopedPins(pins)
    folder=pins.root/REPLAY/variant_id
    manifest=load(pins.check(folder/'replay_manifest.json'))
    require(manifest['split']=='TEST' and manifest['variant_id']==variant_id,'Wrong replay identity')
    branches=[b for b in manifest['branches'] if b['organization']==organization]
    require(len(branches)==1,'Missing or duplicate organization branch')
    branch=branches[0]
    anchor=datetime.fromisoformat(manifest['anchor']);end=datetime.fromisoformat(manifest['end_exclusive'])
    ref_path=pins.check(pins.root/REPLAY/branch['history_reference']);reference=load(ref_path)
    require(reference['organization']==organization and reference['block']==f"TEST_SEED{manifest['seed']}",'History isolation failure')
    validate_branch(pins.protocol,'TEST',anchor,end,datetime.fromisoformat(reference['history_start_inclusive']),datetime.fromisoformat(reference['history_end_exclusive']))
    require(anchor-timedelta(days=7)>=bounds(pins.protocol,'TEST')[0],'TEST warm-up would read another split')
    observation_path=pins.check(folder/f'{organization}_observations.parquet')
    require(sha(observation_path)==branch['observations_parquet_sha256'],'Observation hash mismatch')
    authorized=[(pins.root/path).resolve() for path in reference['source_files_relative_to_root']]
    source_files=[]
    for path in authorized:
        require(path.is_relative_to((pins.root/'data/organizations'/f'organization={organization}').resolve()),'Cross-organization warm-up file')
        scope.check_history_source(path,authorized)
        source_files.append(pins.base.check(path).as_posix())
    db=duckdb.connect(':memory:',config={'threads':2});runtime=OrganizationGraphRuntime(organization);ordinal=0
    try:
        cols={r[0] for r in db.execute('DESCRIBE SELECT * FROM read_parquet(?)',[source_files]).fetchall()}
        success='LoginSuccessful' if 'LoginSuccessful' in cols else 'Login Successful'
        cursor=db.execute(f'''SELECT CAST("Login Timestamp" AS TIMESTAMP),CAST("User ID" AS BIGINT),CAST("IP Address" AS VARCHAR),CAST("{success}" AS BOOLEAN)
          FROM read_parquet(?) WHERE CAST("Login Timestamp" AS TIMESTAMP)>=? AND CAST("Login Timestamp" AS TIMESTAMP)<? ORDER BY 1,2,3,4''',[source_files,anchor-timedelta(days=7),anchor])
        def rows(cursor):
            while True:
                chunk=cursor.fetchmany(4096)
                if not chunk:return
                yield from chunk
        for t,group in groupby(rows(cursor),key=lambda row:row[0]):
            require(bounds(pins.protocol,'TEST')[0]<=t<anchor,'Non-TEST warm-up row')
            events=list(group);observations=[dict(zip(OBSERVABLE,[organization,t,*r[1:]])) for r in events]
            runtime.apply_timestamp_batch(t,observations,[f'H_{ordinal+i}' for i in range(len(events))]);ordinal+=len(events)
        require(ordinal==reference['history_event_count'],'Warm-up census mismatch')
        cols={r[0] for r in db.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(observation_path)]).fetchall()}
        require(cols==set(OBSERVABLE),'Unpermitted replay columns')
        events=db.execute('''SELECT organization,"Login Timestamp","User ID","IP Address",LoginSuccessful FROM read_parquet(?) ORDER BY 2,3,4,5''',[str(observation_path)]).fetchall()
        require(all(r[0]==organization and anchor<=r[1]<end for r in events),'Nonlocal or out-of-hour observation')
    finally:db.close()
    schedule={};offset=0
    for t,group in groupby(events,key=lambda row:row[1]):
        batch=list(group);schedule[t]=dict(observations=[dict(zip(OBSERVABLE,row)) for row in batch],tokens=[f'R_{offset+i}' for i in range(len(batch))],heartbeat=False,final=False);offset+=len(batch)
    for minutes in [0,10,20,30,40,50]:
        item=schedule.setdefault(anchor+timedelta(minutes=minutes),dict(observations=[],tokens=[],heartbeat=False,final=False));item['heartbeat']=True
    final=end-timedelta(microseconds=1)
    item=schedule.setdefault(final,dict(observations=[],tokens=[],heartbeat=True,final=True));item['heartbeat']=True;item['final']=True
    source_identity=dict(variant_id=variant_id,organization=organization,split='TEST',observations_sha256=sha(observation_path),history_reference_sha256=sha(ref_path),
                         anchor=anchor.isoformat(),end_exclusive=end.isoformat(),events=len(events),warmup_events=ordinal)
    return runtime.graph,sorted(schedule.items()),source_identity
