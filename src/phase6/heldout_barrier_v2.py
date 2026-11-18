"""Append-only simulated sharing transaction log; no committed GNN reruns."""
from datetime import datetime
import hashlib,json,os,uuid
from pathlib import Path
from types import SimpleNamespace
from src.phase6.heldout_contract_v2 import canonical,digest,ORGS,verify_five_org_policy
from src.phase6.temporal_protocol import require
from src.phase6.indicator_sharing import Issuer,Recipient,Network,combine

def write_once(path,value):
    path=Path(path);data=(canonical(value)+'\n').encode();path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():require(path.read_bytes()==data,'Immutable output collision: '+str(path))
    else:
        # Publish complete bytes atomically. Crash fragments stay as separate
        # staging files and can never masquerade as completed artifacts.
        staging=path.with_name(path.name+'.writing.'+uuid.uuid4().hex)
        with staging.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        try:
            # Windows rename is atomic and refuses an existing destination;
            # sandboxed Windows disallows hardlinks. POSIX link is no-replace.
            if os.name=='nt':os.rename(staging,path)
            else:os.link(staging,path)
        except FileExistsError:require(path.read_bytes()==data,'Concurrent immutable output collision')
        # Staging files are deliberately preserved, never overwritten/deleted.
    return hashlib.sha256(data).hexdigest()

class Journal:
    """Hash-chained segments. Preserve incomplete crash tails; never truncate."""
    def __init__(self,directory,identity):
        self.root=Path(directory);self.root.mkdir(parents=True,exist_ok=True)
        self.records=[];self.last='0'*64;index=0;partial=None
        while (self.root/f'barriers.{index:06d}.jsonl').exists():
            data=(self.root/f'barriers.{index:06d}.jsonl').read_bytes();partial=None
            lines=data.splitlines(keepends=True)
            for line in lines:
                if not line.endswith(b'\n'):
                    partial=dict(segment=index,bytes=len(line),sha256=hashlib.sha256(line).hexdigest());break
                value=json.loads(line)
                require(value['seq']==len(self.records) and value['prev']==self.last and
                        digest(value['body'])==value['body_sha256'],'Journal sequence/content corruption')
                check=dict(value);checksum=check.pop('sha256')
                require(digest(check)==checksum,'Journal checksum corruption')
                self.records.append(value);self.last=checksum
            index+=1
        self.index=max(0,index-1) if partial is None else index
        if not self.records:self.append(dict(event='IDENTITY',identity=identity))
        require(self.records[0]['body']==dict(event='IDENTITY',identity=identity),'Journal identity mismatch')
        if partial:self.append(dict(event='PRESERVED_INCOMPLETE_TAIL',**partial))

    def append(self,body):
        value=dict(seq=len(self.records),prev=self.last,body=body,body_sha256=digest(body));value['sha256']=digest(value)
        with (self.root/f'barriers.{self.index:06d}.jsonl').open('ab') as f:
            f.write((canonical(value)+'\n').encode());f.flush();os.fsync(f.fileno())
        self.records.append(value);self.last=value['sha256'];return value
    def get(self,event,at,org=None,key=None):
        matches=[r['body'] for r in self.records if r['body'].get('event')==event and r['body'].get('at')==at and
                 r['body'].get('organization')==org and r['body'].get('key')==key]
        require(len(matches)<=1,'Duplicate committed journal stage');return matches[0] if matches else None

class Barrier:
    def __init__(self,scope,ports,directory):
        scope.assert_ready();scope.check_output(directory)
        self.scope,self.ports,self.root=scope,ports,Path(directory);self.faulted=False
        self.branches={o:p.branch for o,p in ports.items()}
        policy=scope.catalog.policy
        self.issuers={o:Issuer(o,json.loads(canonical(policy))) for o in ORGS}
        self.network=Network(json.loads(canonical(policy)),{o:Recipient(o,json.loads(canonical(policy))) for o in ORGS})
        self.validate()
        identity=dict(version='heldout-barrier-v2',adapter=scope.adapter_identity,catalog=scope.catalog.identity,branches={o:b.identity for o,b in self.branches.items()})
        self.journal=Journal(self.root/'progress',identity)
        for record in self.journal.records:
            b=record['body'];t=datetime.fromisoformat(b['at']) if 'at' in b else None
            if b['event']=='ISSUANCE':self._restore_issuer(b['organization'],self._read_ref(b)['delta'])
            if b['event']=='PUBLISHED':
                proof=self._read_ref(b);self.network.publish(proof['payloads'],t)
        self.validate()

    def validate(self):
        verify_five_org_policy(self.scope.catalog,self.branches,self.issuers,self.network)
        require(set(self.ports)==set(ORGS),'All five local ports required')
        for o,p in self.ports.items():
            require(p.organization==o and p.branch==self.branches[o],'Local port identity changed')
            self.scope.catalog.seal(o,'graphsage').validate(p.bundle('graphsage'))
    def _read_ref(self,body):
        p=(self.root/body['path']).resolve();require(p.is_relative_to(self.root.resolve()),'Journal reference escaped')
        data=p.read_bytes();require(hashlib.sha256(data).hexdigest()==body['sha256'],'Journal artifact changed');return json.loads(data)
    def _ref(self,event,at,org,value):
        key=digest([at,event,org])[:24]
        relative=(f'{org}/private/' if org else 'network/')+key+'.json'
        h=write_once(self.root/relative,value)
        body=dict(event=event,at=at,path=relative,sha256=h)
        if org:body['organization']=org
        self.journal.append(body);return body
    def _restore_issuer(self,org,delta):
        issuer=self.issuers[org]
        issuer.until.update({ip:datetime.fromisoformat(t) for ip,t in delta['until'].items()})
        issuer.clock=datetime.fromisoformat(delta['clock']);issuer.suppressed+=delta['suppressed'];issuer.without_evidence+=delta['without_evidence'];issuer.provenance.extend(delta['provenance'])

    def process(self,t,commands,fail=lambda stage:None):
        self.scope.assert_ready();require(not self.faulted,'Restart barrier after a failure');self.validate()
        require(set(commands)<=set(ORGS),'Unknown command organization')
        branch=self.branches['Org1'];require(branch.start<=t<branch.stop and t.tzinfo is None,'Barrier outside branch')
        at=t.isoformat();frames={o:self.ports[o].frame_identity(t,f) for o,f in commands.items()}
        begin=self.journal.get('BEGIN',at)
        if begin:require(begin['frames']==frames,'Changed interrupted input')
        else:
            pending=[r['body']['at'] for r in self.journal.records if r['body']['event']=='BEGIN' and not self.journal.get('COMPLETE',r['body']['at'])]
            require(not pending,'Finish interrupted barrier before advancing')
            times=[r['body']['at'] for r in self.journal.records if r['body']['event']=='BEGIN']
            require(not times or at>max(times),'Closed/out-of-order barrier')
            self.journal.append(dict(event='BEGIN',at=at,frames=frames))
        try:
            if self.journal.get('COMPLETE',at):
                return {o:self._read_ref(self.journal.get('PAIRED',at,o)) for o in commands}
            fail('after_begin');payloads=[];local={}
            for org in sorted(commands):
                record=self.journal.get('LOCAL',at,org)
                if record:local[org]=self._read_ref(record)
                else:
                    fail('before_local:'+org)
                    local[org]=self.ports[org].ensure_local(t,commands[org])
                    fail('after_local:'+org) # local SQLite may already be committed
                    self._ref('LOCAL',at,org,local[org]);fail('after_local_record:'+org)
                issue=self.journal.get('ISSUANCE',at,org)
                if issue:value=self._read_ref(issue)
                else:
                    issuer=self.issuers[org];before=dict(issuer.until);s,w,n=issuer.suppressed,issuer.without_evidence,len(issuer.provenance)
                    recent=[SimpleNamespace(time=datetime.fromisoformat(e[0]),user=e[1],ip=e[2]) for e in local[org]['recent']]
                    graph=SimpleNamespace(organization=org,clock=t,recent_events=recent)
                    alerts=[{k:r[k] for k in ('user_id','alert_id','decision')} for r in local[org]['scores'] if r['decision']=='ALERT']
                    issued=issuer.attribute(t,graph,alerts)
                    delta=dict(until={ip:end.isoformat() for ip,end in issuer.until.items() if before.get(ip)!=end},clock=at,
                               suppressed=issuer.suppressed-s,without_evidence=issuer.without_evidence-w,provenance=issuer.provenance[n:])
                    value=dict(payloads=issued,delta=delta);self._ref('ISSUANCE',at,org,value);fail('after_issuance:'+org)
                payloads.extend(value['payloads'])
            published=self.journal.get('PUBLISHED',at)
            if not published:
                # Original Network/Recipient semantics. Receipt observations are
                # durable idempotent markers, never a second model decision.
                for org,recipient in self.network.recipients.items():
                    original=recipient.receive
                    def receive(p,clock,org=org,original=original):
                        result=original(p,clock)
                        if not self.journal.get('RECEIPT',at,org,p['indicator_id']):
                            self.journal.append(dict(event='RECEIPT',at=at,organization=org,key=p['indicator_id']))
                        fail('after_receipt:'+org);return result
                    recipient.receive=receive
                network_start=len(self.network.log);receiver_start={o:len(r.log) for o,r in self.network.recipients.items()}
                self.network.publish(payloads,t);fail('after_network_memory')
                proof=dict(payloads=payloads,events=self.network.log[network_start:],
                           recipients={o:r.log[receiver_start[o]:] for o,r in self.network.recipients.items()})
                self._ref('PUBLICATION_PREPARED',at,None,proof) if not self.journal.get('PUBLICATION_PREPARED',at) else require(self._read_ref(self.journal.get('PUBLICATION_PREPARED',at))==proof,'Changed prepared publication')
                fail('after_publication_prepared')
                self._ref('PUBLISHED',at,None,proof);fail('after_published')
                # Undo only wrapper installation, not policy state.
                for recipient in self.network.recipients.values():recipient.receive=recipient.__class__.receive.__get__(recipient)
            result={}
            for org,value in local.items():
                paired=self.journal.get('PAIRED',at,org)
                if paired:result[org]=self._read_ref(paired);continue
                current={int(u):set(ips) for u,ips in value['current'].items()};rows=[];seen=set()
                for score in value['scores']:
                    u=score['user_id'];seen.add(u);flag,hits=combine(score['decision']=='ALERT',current.get(u,set()),self.network.recipients[org],t)
                    rows.append(dict(user_id=u,local_alert=score['decision']=='ALERT',local_plus_indicator_alert=flag,indicator_ids=hits,logit_hex=score['logit_hex'],threshold_hex=score['threshold_hex']))
                extra=[]
                for u in sorted(set(current)-seen):
                    flag,hits=combine(False,current[u],self.network.recipients[org],t)
                    extra.append(dict(user_id=u,local_status='NOT_SCORED',local_plus_indicator_alert=flag,indicator_ids=hits))
                result[org]=dict(organization=org,variant_id=branch.variant,at=at,paired=rows,additional_event_users=extra,
                    local_provenance=value['provenance'],policy_sha256=digest(self.scope.catalog.policy))
                self._ref('PAIRED',at,org,result[org]);fail('after_paired:'+org)
            fail('before_complete');self.journal.append(dict(event='COMPLETE',at=at,organizations=sorted(commands),frames=frames));fail('after_complete')
            return result
        except Exception as error:
            self.faulted=True
            self.journal.append(dict(event='FAILURE',at=at,error_type=type(error).__name__,message=str(error)[:2000]))
            raise
