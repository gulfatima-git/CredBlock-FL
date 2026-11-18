"""Independent allowlisted source and disposable-evidence audit. No live scopes."""
from pathlib import Path
from types import SimpleNamespace
import ast,hashlib,json,shutil,sqlite3,sys
from datetime import datetime
from src.phase6.heldout_contract_v2 import ROOT

RESEARCH=Path(r'C:\Users\Gulso\OneDrive\Documents\ChatGPT\research')
def h(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def allowed_fixture(root):
    root=Path(root).resolve()
    if not root.is_relative_to(RESEARCH) or not root.name.startswith('wal_v4_') or root.is_relative_to(ROOT):raise ValueError('Disposable WAL fixture namespace only')
    return root
def method(path,klass,name):
    tree=ast.parse(Path(path).read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==klass)
    return ast.dump(next(n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name),include_attributes=False)
def independent_journal(directory):
    records=[];previous='0'*64
    for path in sorted(Path(directory).glob('barriers.*.jsonl')):
        for line in path.read_bytes().splitlines(keepends=True):
            if not line.endswith(b'\n'):break
            r=json.loads(line);value=dict(r);checksum=value.pop('sha256')
            assert r['seq']==len(records) and r['prev']==previous and digest(value)==checksum and digest(r['body'])==r['body_sha256']
            records.append(r);previous=checksum
    assert records and records[0]['body']['event']=='IDENTITY'
    return records,previous

def audit(fixtures,output):
    fixtures=allowed_fixture(fixtures);output=Path(output).resolve()
    assert output.is_relative_to(ROOT/'reports/phase6/wal_continuation_v4_v1') and not output.exists()
    output.mkdir(parents=True)
    checks=[]
    def check(name,ok,**detail):checks.append(dict(check=name,PASS=bool(ok),**detail));assert ok,name
    baseline=json.loads((ROOT/'reports/phase6/wal_continuation_v4_v1/preservation_before.json').read_text())
    for path,expected in baseline.items():
        assert path.startswith(('src/phase6/','src/organization/','configs/phase6/'))
        check('Accepted source/configuration preserved: '+path,h(ROOT/path)==expected)
    for name in ('prepare','labels','truth','inventory','verify_register_row'):
        check('Production backend scientific path unchanged: '+name,method(ROOT/'src/phase6/continuation_driver_v3.py','ProductionBackend',name)==method(ROOT/'src/phase6/continuation_driver_v4.py','ProductionBackend',name))
    check('Indexed barrier transaction method unchanged',method(ROOT/'src/phase6/continuation_barrier_v3.py','ContinuationBarrier','process')==method(ROOT/'src/phase6/continuation_barrier_v4.py','ContinuationBarrier','process'))
    wal=ast.parse((ROOT/'src/phase6/continuation_wal_v4.py').read_text())
    calls=[n for n in ast.walk(wal) if isinstance(n,ast.Call)]
    sql=[n.value for n in ast.walk(wal) if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.startswith('PRAGMA')]
    check('WAL layer has only integrity-check PRAGMA',all(x=='PRAGMA integrity_check' for x in sql))
    check('No process control in recovery layer',not any(isinstance(n.func,ast.Attribute) and n.func.attr in ('kill','terminate','GenerateConsoleCtrlEvent','AttachConsole','Popen') for n in calls))
    connections=[ast.unparse(n) for n in calls if isinstance(n.func,ast.Attribute) and ast.unparse(n.func)=='sqlite3.connect']
    check('WAL layer never connects to physical source',all('source' not in x and ('oracle_db' in x or 'Path(path)' in x) for x in connections),connections=connections)
    sys.path.insert(0,str(ROOT/'tests/phase6'))
    from wal_fixture_worker_v4 import make_world
    from src.phase6.continuation_recovery_v3 import inspect_store as original_inspector
    _,old,bundles=make_world(fixtures/'audit_metadata')
    cases=sorted(fixtures.glob('test_five_org*/wal_v4_case/case_evidence.json'))
    check('All 27 requested crash stages present',len(cases)==27,found=len(cases))
    stats=[]
    for case in cases:
        evidence=json.loads(case.read_text());cert=json.loads((case.parent/'certificate_v4.json').read_text());body=cert['body']
        check('Case PASS and no committed prediction repeat: '+evidence['stage'],evidence['status']=='PASS' and evidence['extra_committed_model_calls']==0 and evidence['predecessor_model_calls']+evidence['continuation_model_calls']==evidence['reference_model_calls'])
        source=Path(body['source_root']);assert source.is_relative_to(fixtures)
        cap=Path(body['capture_root']);assert cap.is_relative_to(fixtures)
        for relative,desc in body['files'].items():
            p=source/relative;check('Physical original unchanged: '+evidence['stage']+'/'+relative,p.stat().st_size==desc['size'] and h(p)==desc['sha256'])
        for org,expected in body['stores'].items():
            derived=cap/org/'derived.sqlite'
            actual=original_inspector(derived,org,body['origin']['variant'],old.catalog,body['bindings'][org])['descriptor']
            check('Original independent inspector agrees: '+evidence['stage']+'/'+org,actual==expected)
            oracle=output/'oracles'/str(len(stats))/org;oracle.mkdir(parents=True)
            physical=source/org/'private/local.sqlite'
            for suffix in ('','-wal','-shm'):
                p=Path(str(physical)+suffix)
                if p.exists():shutil.copyfile(p,oracle/('local.sqlite'+suffix))
            a=sqlite3.connect((oracle/'local.sqlite').as_uri()+'?mode=ro',uri=True)
            b=sqlite3.connect(derived.as_uri()+'?mode=ro&immutable=1',uri=True)
            try:
                check('Independent WAL engine integrity: '+evidence['stage']+'/'+org,a.execute('PRAGMA integrity_check').fetchall()==[('ok',)])
                for table,order in [('commands','seq'),('scores','seq,user_id'),('event_tokens','token'),('checkpoints','seq'),('failures','id'),('meta','key')]:
                    check('Independent committed SQL rows: '+evidence['stage']+'/'+org+'/'+table,a.execute('SELECT * FROM '+table+' ORDER BY '+order).fetchall()==b.execute('SELECT * FROM '+table+' ORDER BY '+order).fetchall())
            finally:a.close();b.close()
        for directory,desc in body['journals'].items():
            rows,last=independent_journal(source/directory)
            check('Independent journal chain: '+evidence['stage']+'/'+directory,last==desc['last'])
            if directory!='sharing/progress':continue
            for record in rows:
                r=record['body']
                if r['event']!='LOCAL':continue
                value=json.loads((source/'sharing'/r['path']).read_bytes());org=r['organization']
                db=sqlite3.connect((cap/org/'derived.sqlite').as_uri()+'?mode=ro&immutable=1',uri=True)
                try:
                    saved=db.execute('SELECT user_id,logit_hex,threshold_hex,decision,alert_id,model_sha256,threshold_sha256 FROM scores WHERE seq=? ORDER BY user_id',(value['seq'],)).fetchall()
                    keys=('user_id','logit_hex','threshold_hex','decision','alert_id','model_sha256','threshold_sha256')
                    check('Independent LOCAL/SQL prediction join: '+evidence['stage']+'/'+org+'/'+r['at'],saved==[tuple(v[k] for k in keys) for v in value['scores']])
                finally:db.close()
        target=source if (source/'completion.json').exists() else case.parent/'continued/outputs'/body['origin']['variant']
        public=json.loads((target/'public_results.json').read_bytes());completion=json.loads((target/'completion.json').read_bytes())
        check('Independent completion status: '+evidence['stage'],completion['status']=='COMPLETE_VALIDATED' and completion['independent_reconciliation']=='PASS')
        for relative,expected in completion['files_sha256'].items():check('Independent sealed completion hash: '+evidence['stage']+'/'+relative,h(target/relative)==expected)
        for org in body['stores']:
            for detector in ('graphsage','tabular_mlp'):
                values=json.loads((target/org/'private'/('eligible_'+detector+'.json')).read_bytes());seen=set();counts=dict(tp=0,fp=0,fn=0,tn=0)
                for row in values:
                    key=(row['asof'],row['user_id']);assert key not in seen;seen.add(key)
                    threshold=row['threshold'];flag=threshold['kind']=='finite' and float.fromhex(row['logit_hex'])>=float.fromhex(threshold['hex'])
                    assert flag==row['alert'] and row['node_label'] in (0,1)
                    counts['tp' if flag and row['node_label']==1 else 'fp' if flag else 'fn' if row['node_label']==1 else 'tn']+=1
                reported=public['fixed_grid'][org][detector]
                check('Independent eligible-unit counts: '+evidence['stage']+'/'+org+'/'+detector,all(reported[k]==v for k,v in counts.items()))
            users=json.loads((target/org/'private/campaign_user_results.json').read_bytes())
            for user in users:
                censored=user['right_censored']
                check('Independent censoring: '+evidence['stage']+'/'+org+'/'+user['family'],
                      (censored and user['first_detection'] is None and user['event_time_seconds'] is None) or
                      (not censored and user['first_detection'] is not None and user['event_time_seconds']==(datetime.fromisoformat(user['first_detection'])-datetime.fromisoformat(user['first_exposure'])).total_seconds()))
        final_journal,_=independent_journal(target/'sharing/progress');local={};indicators={}
        for record in final_journal:
            b=record['body'];event=b['event']
            if event not in ('LOCAL','PUBLISHED','PAIRED'):continue
            value=json.loads((target/'sharing'/b['path']).read_bytes());at=datetime.fromisoformat(b['at'])
            if event=='LOCAL':local[b['at'],b['organization']]=value
            elif event=='PUBLISHED':
                for p in value['payloads']:
                    check('Independent zero-delay publication: '+evidence['stage']+'/'+p['indicator_id'],p['issued_at']==p['available_at']==b['at'] and datetime.fromisoformat(p['expires_at'])>at)
                    indicators[p['indicator_id']]=p
                for e in value['events']:
                    if e['event']=='expiry':check('Independent exclusive expiry: '+evidence['stage']+'/'+e['indicator_id'],e['at']==indicators[e['indicator_id']]['expires_at'] and datetime.fromisoformat(e['at'])<=at)
            else:
                org=b['organization'];original=local[b['at'],org];scores={r['user_id']:r for r in original['scores']}
                current={int(u):set(ips) for u,ips in original['current'].items()}
                for row in value['paired']:
                    s=scores[row['user_id']];hits=sorted(k for k,p in indicators.items() if p['issuer']!=org and p['ip'] in current.get(row['user_id'],set()) and datetime.fromisoformat(p['available_at'])<=at<datetime.fromisoformat(p['expires_at']))
                    flag=s['threshold_hex'] is not None and float.fromhex(s['logit_hex'])>=float.fromhex(s['threshold_hex'])
                    check('Independent paired binary64/indicator decision: '+evidence['stage']+'/'+org+'/'+b['at']+'/'+str(row['user_id']),row['logit_hex']==s['logit_hex'] and row['threshold_hex']==s['threshold_hex'] and row['local_alert']==flag and row['indicator_ids']==hits and row['local_plus_indicator_alert']==(flag or bool(hits)))
        stats.append(evidence)
    result=dict(status='PASS_INDEPENDENT_SOURCE_AND_SYNTHETIC_EVIDENCE_RECONCILIATION',checks=checks,cases=stats,
                limitations=['No actual TEST observations, model weights or live database accessed','Production behavior remains unverified','Source-level and separate-oracle audit, not a separate human review'])
    with (output/'summary.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(status=result['status'],checks=len(checks),cases=len(cases))))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--fixtures',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();audit(a.fixtures,a.output)
