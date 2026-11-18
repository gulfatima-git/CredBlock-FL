"""All checkpoint blobs and latest-checkpoint recovery, on forensic views only."""
from pathlib import Path
from datetime import datetime,timedelta
import gzip,hashlib,json,sqlite3,sys
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');sys.path.insert(0,str(ROOT))
REPORT=Path(__file__).resolve().parent
from src.organization.rolling_graph_v1 import RollingGraph,VERSION

def main():
    meta=json.loads((REPORT/'database_derivations.json').read_text());run=Path(meta['run']).resolve()
    assert run in {ROOT/'reports/phase6/v2_forensic_v1/physical',ROOT/'reports/phase6/v2_verify_v1'}
    reports=[]
    for item in meta['sets']:
        relative=item['database'];path=run/relative;org=relative.split('/')[1]
        assert not Path(str(path)+'-wal').exists() or Path(str(path)+'-wal').stat().st_size==0
        db=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)
        try:
            rows=db.execute('SELECT seq,graph,sha256 FROM checkpoints ORDER BY seq').fetchall();commands={seq:(at,digest) for seq,at,digest in db.execute('SELECT seq,asof,view_digest FROM commands')}
            assert rows and rows[0][0]==0
            for seq,blob,h in rows:
                assert hashlib.sha256(blob).hexdigest()==h
                wrapper=json.loads(gzip.decompress(blob));payload=wrapper['payload']
                raw=json.dumps(payload,separators=(',',':'),sort_keys=True).encode()
                assert hashlib.sha256(raw).hexdigest()==wrapper['sha256'] and payload['version']==VERSION and payload['organization']==org
                clock=datetime.fromisoformat(payload['clock'])
                assert all(clock-timedelta(days=7)<datetime.fromisoformat(e[1])<=clock for e in payload['events'])
                assert seq==0 or seq in commands and payload['clock']==commands[seq][0]
            seq,blob,h=rows[-1];graph=RollingGraph.from_checkpoint_bytes(blob);replayed=0
            if seq:assert graph.view().digest()==commands[seq][1]
            for n,at,payload,digest in db.execute('SELECT seq,asof,payload,view_digest FROM commands WHERE seq>? ORDER BY seq',(seq,)):
                p=json.loads(payload);t=datetime.fromisoformat(at)
                if p['observations']:graph.ingest_batch(t,[dict(r,**{'Login Timestamp':datetime.fromisoformat(r['Login Timestamp'])}) for r in p['observations']],p['tokens'])
                else:graph.advance(t)
                assert graph.view().digest()==digest;replayed+=1
            if commands:assert graph.clock.isoformat()==commands[max(commands)][0] and graph.view().digest()==commands[max(commands)][1]
            reports.append(dict(database=relative,status='PASS_ALL_CHECKPOINTS_AND_LATEST_RECOVERY',checkpoints=len(rows),last_checkpoint_seq=seq,committed_commands=len(commands),graph_commands_replayed=replayed,GNN_forwards=0))
            print(json.dumps(dict(event='checkpoint_set_verified',database=relative,sets=len(reports))),flush=True)
        finally:db.close()
    with (REPORT/'checkpoint_recovery_verification.json').open('x') as f:json.dump(dict(status='PASS_ALL_CHECKPOINTS_AND_GRAPH_RECOVERY',sets=reports,GNN_forwards=0),f,indent=2)
if __name__=='__main__':
    try:main()
    except BaseException as e:
        with (REPORT/('checkpoint_failure_'+datetime.now().strftime('%H%M%S%f')+'.json')).open('x') as f:json.dump(dict(status='STOP',type=type(e).__name__,message=str(e)),f,indent=2)
        raise
