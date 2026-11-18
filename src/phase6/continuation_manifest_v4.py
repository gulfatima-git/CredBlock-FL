"""Exact 171-instance mixed-origin ledger. Completion is never inferred from count alone."""
from pathlib import Path
import csv,json
from src.phase6.heldout_contract_v2 import ROOT,ORGS,digest,Scope
from src.phase6.continuation_contract_v4 import REGISTER,REGISTER_SHA,relative_path
from src.phase6.continuation_reader_v4 import sha
from src.phase6.heldout_barrier_v2 import Journal,write_once
from src.phase6.temporal_protocol import require

def frozen_rows(scope,fixture_rows=None):
    scope.assert_ready()
    if scope.synthetic_only:
        require(fixture_rows is not None,'Fixture register missing');rows=fixture_rows
    else:
        require(fixture_rows is None and sha(ROOT/REGISTER)==REGISTER_SHA,'Frozen register changed')
        with (ROOT/REGISTER).open(newline='',encoding='utf-8-sig') as f:rows=[r for r in csv.DictReader(f) if r['split']=='TEST']
    require(len(rows)==171 and len({r['variant_id'] for r in rows})==171,'Full manifest requires exactly 171 unique instances')
    require(all(r.get('split')=='TEST' and r['variant_id'].endswith('_TEST') for r in rows),'Non-TEST register entry')
    require({int(r['seed']) for r in rows}=={1001,1002,1003} and all(sum(int(r['seed'])==s for r in rows)==57 for s in (1001,1002,1003)),'Frozen seed coverage differs')
    return sorted(rows,key=lambda r:r['variant_id'])

def verify_completion(directory,row,catalog,allowed_adapters):
    directory=Path(directory).resolve();p=directory/'completion.json';require(p.is_file(),'No completion manifest')
    c=json.loads(p.read_bytes());identity=c['identity']
    require(c['status']=='COMPLETE_VALIDATED' and c.get('independent_reconciliation')=='PASS' and identity['variant']==row['variant_id'] and identity['catalog']==catalog.identity and identity['register_row_sha256']==digest(row) and identity['adapter'] in allowed_adapters,'Completion identity/register mismatch')
    for rel,h in c['files_sha256'].items():require(sha(relative_path(directory,rel))==h,'Completed artifact changed: '+rel)
    seal=json.loads((directory/'score_seal.json').read_bytes());bindings=json.loads((directory/'bindings.json').read_bytes())
    require(seal['status']=='SCORES_SEALED_BEFORE_LABELS' and seal['identity']==identity and set(bindings)==set(ORGS),'Invalid completed score seal/coverage')
    require(c['files_sha256']['score_seal.json']==sha(directory/'score_seal.json'),'Unpinned score seal')
    from src.phase6.heldout_contract_v2 import Branch
    from src.phase6.heldout_grid_v2 import EvaluationContext
    from datetime import datetime,timedelta
    times=[datetime.fromisoformat(t) for t in seal['completed_barriers']]
    require(times==sorted(set(times)) and times,'Invalid completed barrier coverage')
    for org,b in bindings.items():
        branch=Branch(**b);branch.validate(catalog);require(branch.variant==row['variant_id'] and branch.organization==org,'Wrong completed branch')
        require(times[-1]==branch.stop-timedelta(microseconds=1) and all(branch.start<=t<branch.stop for t in times) and all(t in times for t in branch.grid),'Missing primary/final coverage')
        require(seal['branches'][org]==branch.identity,'Unsealed completed branch')
        ctx=EvaluationContext.bind(catalog,branch)
        for t in branch.grid:
            for detector in ('graphsage','tabular_mlp'):
                rel=f'{org}/private/grid_{t.minute:02d}_{detector}.json';require(rel in c['files_sha256'],'Missing primary grid')
                raw=json.loads((directory/rel).read_bytes());s=ctx.seal(detector)
                require(raw['context_identity']==ctx.identity and raw['adapter_identity'] in allowed_adapters and raw['asof']==t.isoformat() and raw['organization']==org and raw['variant_id']==branch.variant and raw['detector']==detector and raw['model_identity']==json.loads(s.identity_json) and raw['model_state_digest']==s.state_digest and raw['threshold']==json.loads(s.threshold_json),'Completed raw identity/model mismatch')
                require(digest(raw) in seal['raw_score_digests'] and rel in seal['files_sha256'] and seal['files_sha256'][rel]==c['files_sha256'][rel],'Raw not in original pre-label seal')
        for name in ('eligible_graphsage.json','eligible_tabular_mlp.json','campaign_user_results.json','alert_attribution.json'):
            require(f'{org}/private/{name}' in c['files_sha256'],'Missing completed private evaluation evidence')
    return dict(directory=str(directory),completion_sha256=sha(p),origin_identity=identity,files=len(c['files_sha256']))

class FullRunManifest:
    def __init__(self,scope,rows,directory):
        scope.assert_ready();self.scope=scope;self.rows=frozen_rows(scope,rows if scope.synthetic_only else None)
        require(rows==self.rows or sorted(rows,key=lambda r:r['variant_id'])==self.rows,'Register mutation')
        self.by_id={r['variant_id']:r for r in self.rows};self.root=Path(directory)
        if scope.certificate_path:
            expected=scope.certificate()['body'].get('register_rows_digest')
            require(expected is not None and expected==digest(self.rows),'Full manifest not bound to certified register')
        scope.check_output(self.root)
        self.log=Journal(self.root/'progress',dict(format='phase6-mixed-run-wal-v4',executor=scope.adapter_identity,catalog=scope.catalog.identity,register_digest=digest(self.rows)))
        self.states={}
        for r in self.log.records:
            if r['body']['event']=='INSTANCE_COMPLETE':self._accept(r['body'])
    def _accept(self,b):
        require(b['variant_id'] in self.by_id and b['variant_id'] not in self.states,'Duplicate/unregistered full-run result')
        require(b['kind'] in ('REUSED_COMPLETE_V2','CONTINUED_V2_PREFIX_UNDER_WAL_V4','NEW_COMPLETE_WAL_V4'),'Unrecognized execution provenance')
        cert=self.scope.certificate() if self.scope.certificate_path else None
        origin=cert['body']['origin']['adapter'] if cert else Scope.current_adapter_identity()
        expected_dir=self.scope.output_root/b['variant_id']
        allowed={self.scope.adapter_identity}
        if b['kind']=='REUSED_COMPLETE_V2':
            require(cert and b['certificate_id'] is None,'Uncertified original run reference')
            expected_dir=Path(cert['body']['source_root']).parent/b['variant_id'];allowed={origin}
            require(cert['body']['completed_origins'].get(b['variant_id'])==b['proof'],'Original completion not pinned by predecessor certificate')
        elif b['kind']=='CONTINUED_V2_PREFIX_UNDER_WAL_V4':
            require(cert and b['certificate_id']==cert['certificate_id'] and b['variant_id']==cert['body']['origin']['variant'],'Uncertified continuation result');allowed={origin,self.scope.adapter_identity}
            c=json.loads((expected_dir/'completion.json').read_bytes())
            require(c.get('execution_provenance',{}).get('certificate_id')==cert['certificate_id'] and c['execution_provenance']['effective_executor']==self.scope.adapter_identity,'Missing continuation provenance')
        else:require(b['certificate_id'] is None,'New result misattributed to predecessor')
        require(Path(b['proof']['directory']).resolve()==expected_dir.resolve(),'Unapproved completion root')
        expected=verify_completion(expected_dir,self.by_id[b['variant_id']],self.scope.catalog,allowed)
        require(expected==b['proof'],'Completion proof changed')
        self.states[b['variant_id']]=b
    def commit(self,row,directory,kind,certificate_id=None):
        self.scope.assert_ready();require(row==self.by_id.get(row['variant_id']),'Foreign inventory row')
        cert=self.scope.certificate() if self.scope.certificate_path else None
        origin=cert['body']['origin']['adapter'] if cert else Scope.current_adapter_identity()
        proof=verify_completion(directory,row,self.scope.catalog,{origin,self.scope.adapter_identity})
        if kind=='REUSED_COMPLETE_V2':require(proof['origin_identity']['adapter']==origin and certificate_id is None,'Wrong reuse provenance')
        elif kind=='CONTINUED_V2_PREFIX_UNDER_WAL_V4':
            require(cert and certificate_id==cert['certificate_id'] and row['variant_id']==cert['body']['origin']['variant'],'Wrong continuation certificate')
            c=json.loads((Path(directory)/'completion.json').read_bytes());require(c.get('execution_provenance',{}).get('certificate_id')==certificate_id and c['execution_provenance']['effective_executor']==self.scope.adapter_identity,'Missing mixed-origin completion provenance')
        else:require(kind=='NEW_COMPLETE_WAL_V4' and proof['origin_identity']['adapter']==self.scope.adapter_identity and certificate_id is None,'Wrong new-result origin')
        body=dict(event='INSTANCE_COMPLETE',variant_id=row['variant_id'],kind=kind,certificate_id=certificate_id,proof=proof)
        if row['variant_id'] in self.states:require(self.states[row['variant_id']]==body,'Changed completion registration');return
        # Validate before committing so rejected proofs cannot poison the ledger.
        self._accept(body)
        try:self.log.append(body)
        except BaseException:
            self.states.pop(row['variant_id'],None);raise
    def seal(self):
        self.scope.assert_ready();require(set(self.states)==set(self.by_id),'Incomplete 171-instance run cannot be sealed')
        for state in self.states.values():
            row=self.by_id[state['variant_id']];require(verify_completion(state['proof']['directory'],row,self.scope.catalog,{state['proof']['origin_identity']['adapter'],self.scope.adapter_identity})==state['proof'],'Final original proof changed')
        value=dict(status='COMPLETE_171_MIXED_ORIGIN_TECHNICAL_REVIEW_REQUIRED',required=171,completed=171,organization_branches=855,
            register_digest=digest(self.rows),executor=self.scope.adapter_identity,ledger_chain_sha256=self.log.last,
            instances=[self.states[r['variant_id']] for r in self.rows],USER_ACCEPTED=False,phase7_started=False)
        write_once(self.root/'full_run_completion.json',value);return value
