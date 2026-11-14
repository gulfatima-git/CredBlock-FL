"""Separate comparison baseline. Wire messages never contain local identities/features."""
from dataclasses import dataclass,asdict
from datetime import datetime,timedelta
import hashlib,json
from src.phase6.temporal_protocol import require

WIRE={'indicator_id','ip','issuer','issued_at','available_at','expires_at','policy_version','status'}
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))
def identity(issuer,ip,t,version):return hashlib.sha256(canonical([version,issuer,ip,t.isoformat()]).encode()).hexdigest()

@dataclass(frozen=True)
class Indicator:
    indicator_id:str
    ip:str
    issuer:str
    issued_at:str
    available_at:str
    expires_at:str
    policy_version:str
    status:str

    @classmethod
    def create(cls,config,issuer,ip,t):
        require(issuer in config['organizations'] and isinstance(ip,str) and bool(ip),'Invalid issuer/IP')
        require(isinstance(t,datetime) and t.tzinfo is None,'Expected naive source time')
        return cls(identity(issuer,ip,t,config['version']),ip,issuer,t.isoformat(),t.isoformat(),(t+timedelta(seconds=config['ttl_seconds'])).isoformat(),config['version'],config['status'])

    @classmethod
    def parse(cls,config,payload):
        require(set(payload)==WIRE,'Only allowlisted indicator fields may cross boundary')
        value=cls(**payload);t=datetime.fromisoformat(value.issued_at)
        require(value==cls.create(config,value.issuer,value.ip,t),'Indicator identity, policy, time or lifetime mismatch')
        return value

    def live(self,t):return datetime.fromisoformat(self.available_at)<=t<datetime.fromisoformat(self.expires_at)
    def payload(self):return asdict(self)

class Issuer:
    """Local state only. Caller supplies original local ALERT rows and its own graph."""
    def __init__(self,organization,config):
        require(organization in config['organizations'],'Unknown issuer')
        self.organization,self.config=organization,config;self.until={};self.clock=None
        self.suppressed=0;self.without_evidence=0;self.provenance=[]

    def attribute(self,t,graph,alerts):
        require(graph.organization==self.organization and graph.clock==t,'Local graph must already be updated to alert time')
        require(self.clock is None or t>self.clock,'Closed issuer timestamp');self.clock=t
        by_user={}
        for event in graph.recent_events:
            require(t-timedelta(seconds=self.config['attribution_window_seconds'])<event.time<=t,'Noncausal recent evidence')
            by_user.setdefault(event.user,set()).add(event.ip)
        result=[]
        for row in sorted(alerts,key=lambda r:(r['user_id'],r['alert_id'])):
            require(set(row)=={'user_id','alert_id','decision'} and row['decision']=='ALERT' and bool(row['alert_id']),'Only original local alerts may issue indicators')
            ips=by_user.get(row['user_id'],set())
            if not ips:self.without_evidence+=1
            for ip in sorted(ips):
                if self.until.get(ip,datetime.min)>t:self.suppressed+=1;continue
                value=Indicator.create(self.config,self.organization,ip,t);self.until[ip]=datetime.fromisoformat(value.expires_at)
                self.provenance.append(dict(indicator_id=value.indicator_id,source_alert_id=row['alert_id'],user_id=row['user_id'],ip=ip,issued_at=t.isoformat()))
                result.append(value.payload())
        return result

class Recipient:
    def __init__(self,organization,config):
        require(organization in config['organizations'],'Unknown recipient')
        self.organization,self.config=organization,config;self.records={};self.expired=set();self.clock=None;self.log=[]

    def advance(self,t):
        require(self.clock is None or t>=self.clock,'Recipient time moved backwards');self.clock=t
        for key,value in sorted(self.records.items()):
            expiry=datetime.fromisoformat(value.expires_at)
            if expiry<=t and key not in self.expired:
                self.log.append(dict(event='expiry',organization=self.organization,indicator_id=key,at=expiry.isoformat()));self.expired.add(key)

    def receive(self,payload,t):
        value=Indicator.parse(self.config,payload)
        require(value.issuer!=self.organization,'Issuer cannot receive its own broadcast')
        require(datetime.fromisoformat(value.available_at)==t,'Zero-delay receipt must occur at issue time')
        self.advance(t)
        if value.indicator_id in self.records:
            require(self.records[value.indicator_id]==value,'Conflicting duplicate indicator')
            self.log.append(dict(event='duplicate_receipt',organization=self.organization,indicator_id=value.indicator_id,at=t.isoformat()));return False
        self.records[value.indicator_id]=value
        self.log.append(dict(event='receipt',organization=self.organization,indicator_id=value.indicator_id,at=t.isoformat()));return True

    def match(self,ips,t):
        self.advance(t)
        return sorted(key for key,value in self.records.items() if value.ip in ips and value.live(t))

class Network:
    """Zero simulated propagation delay, not a realistic transport or FL coordinator."""
    def __init__(self,config,recipients):
        require(set(recipients)==set(config['organizations']),'All isolated receivers required')
        self.config,self.recipients=config,recipients;self.log=[];self.created={};self.expired=set();self.clock=None

    def advance(self,t):
        require(self.clock is None or t>=self.clock,'Network time moved backwards');self.clock=t
        for key,value in sorted(self.created.items()):
            expiry=datetime.fromisoformat(value['expires_at'])
            if expiry<=t and key not in self.expired:
                self.log.append(dict(event='expiry',indicator_id=key,at=expiry.isoformat()));self.expired.add(key)
        for receiver in self.recipients.values():receiver.advance(t)

    def publish(self,payloads,t):
        self.advance(t)
        # Validate the entire publication barrier before any delivery.
        values=[Indicator.parse(self.config,p) for p in payloads]
        require(all(v.issued_at==t.isoformat() for v in values),'Future/backdated issuance')
        for value in sorted(values,key=lambda v:(v.issuer,v.ip,v.indicator_id)):
            p=value.payload();key=value.indicator_id
            if key in self.created:
                require(self.created[key]==p,'Conflicting publication');self.log.append(dict(event='duplicate_publication',indicator_id=key,at=t.isoformat()));continue
            self.created[key]=p;self.log.append(dict(event='creation',**p))
            targets=sorted(o for o in self.recipients if o!=value.issuer)
            self.log.append(dict(event='broadcast',indicator_id=key,at=t.isoformat(),receivers=targets,simulated_delay_seconds=0))
            for org in targets:self.recipients[org].receive(p,t)

    def next_expiry(self):
        times=[datetime.fromisoformat(v['expires_at']) for k,v in self.created.items() if k not in self.expired]
        return min(times) if times else None

def combine(local_alert,current_ips,recipient,t):
    """Only current authentication evidence may utilize an indicator; no feedback."""
    require(type(local_alert)is bool,'Local-only decision must remain explicit')
    hits=recipient.match(set(current_ips),t)
    return local_alert or bool(hits),hits
