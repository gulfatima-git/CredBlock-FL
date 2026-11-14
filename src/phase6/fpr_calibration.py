"""Negative-only fixed-FPR calibration and sealed threshold loading; no fitting API."""
import hashlib,json,math
from pathlib import Path
import numpy as np
from src.phase6.temporal_protocol import require,require_use

def require_val(protocol,split):
    require(split=='VAL','Calibration accepts VAL only; TRAIN and TEST are forbidden')
    require_use(protocol,split,'threshold_calibration')

def fp_budget(n):
    require(type(n)is int and n>0,'No eligible negatives')
    return n//100

def decisions(scores,threshold):
    """Explicit promotion prevents float32 scalar downcast from re-including boundary ties."""
    z=np.asarray(scores,dtype=np.float64)
    require(z.ndim==1 and np.isfinite(z).all(),'Expected finite one-dimensional logits')
    require(threshold['kind'] in {'finite','no_alert'},'Unknown threshold kind')
    if threshold['kind']=='no_alert':return np.zeros(len(z),dtype=bool)
    value=float.fromhex(threshold['hex'])
    require(math.isfinite(value) and value==threshold['value'],'Threshold encoding mismatch')
    return z>=value

def calibrate_negatives(negative_scores,protocol,split='VAL'):
    require_val(protocol,split)
    require(protocol['fpr']['target']==.01 and protocol['fpr']['decision']=='score >= threshold','Unexpected frozen FPR policy')
    z=np.asarray(negative_scores,dtype=np.float64)
    require(z.ndim==1 and np.isfinite(z).all(),'Expected finite one-dimensional negative logits')
    n=len(z);budget=fp_budget(n)
    boundary=float(np.sort(z)[::-1][budget])
    with np.errstate(over='ignore'):threshold=float(np.nextafter(np.float64(boundary),np.float64(np.inf)))
    encoded=dict(kind='finite',value=threshold,hex=threshold.hex()) if math.isfinite(threshold) else dict(kind='no_alert',value=None,hex=None)
    predicted=decisions(z,encoded);fp=int(predicted.sum())
    require(fp<=budget,'Validation FP budget exceeded')
    # The immediately lower representable threshold equals the blocked score and
    # necessarily admits the full tied group, exceeding the integer budget.
    blocked=int((z>=boundary).sum());require(blocked>budget,'Threshold not maximally permissive')
    return dict(threshold=encoded,negative_count=n,fp_budget=budget,achieved_fp=fp,achieved_fpr=fp/n,
        resolution=1/n,sample_size_status='ZERO_FP_BUDGET_N_LT_100' if n<100 else 'RESOLVABLE_1_PERCENT_BUDGET',
        boundary_logit=boundary,boundary_hex=boundary.hex(),boundary_tie_count=int((z==boundary).sum()),
        fp_if_threshold_lowered_one_ulp=blocked,unused_fp_budget=budget-fp,calibration_split='VAL')

def threshold_metrics(y,mask,scores,threshold):
    y=np.asarray(y);mask=np.asarray(mask)
    require(y.ndim==mask.ndim==1 and y.shape==mask.shape and mask.dtype==np.bool_,'Invalid supervision shape/type')
    require(np.isin(y,[-1,0,1]).all() and np.array_equal(mask,y!=-1),'Invalid labels/masks')
    predicted=decisions(scores,threshold);require(predicted.shape==y.shape,'Score/target shape mismatch')
    target=y[mask];p=predicted[mask]
    tp=int((p&(target==1)).sum());fp=int((p&(target==0)).sum());fn=int((~p&(target==1)).sum());tn=int((~p&(target==0)).sum())
    positives=tp+fn;negatives=fp+tn
    return dict(eligible=len(target),positive=positives,negative=negatives,masked=int((~mask).sum()),
        tp=tp,fp=fp,tn=tn,fn=fn,fpr=fp/negatives if negatives else None,
        recall=tp/positives if positives else None,precision=tp/(tp+fp) if tp+fp else None,
        f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
        specificity=tn/negatives if negatives else None,accuracy=(tp+tn)/len(target) if len(target) else None,
        alert_count=tp+fp,alert_fraction=(tp+fp)/len(target) if len(target) else None)

def canonical_digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def seal_threshold(payload):
    require(payload['calibration_split']=='VAL','Only VAL artifacts can be frozen')
    require('seal_sha256' not in payload,'Payload already sealed')
    return dict(**payload,seal_sha256=canonical_digest(payload))

def load_frozen_threshold(path,*,organization,detector,model_sha256,protocol_sha256,configuration_sha256):
    """Loads only. No prediction-source, split, labels or recalibration arguments exist."""
    artifact=json.loads(Path(path).read_text(encoding='utf-8'))
    seal=artifact.pop('seal_sha256')
    require(canonical_digest(artifact)==seal,'Threshold seal mismatch')
    require(artifact['status']=='FROZEN_VAL_THRESHOLD' and artifact['calibration_split']=='VAL','Not a frozen VAL threshold')
    for name,expected in [('organization',organization),('detector',detector),('model_sha256',model_sha256),('protocol_sha256',protocol_sha256),('configuration_sha256',configuration_sha256)]:
        require(artifact[name]==expected,'Threshold identity mismatch: '+name)
    c=artifact['calibration'];require(c['negative_count']>0 and c['fp_budget']==fp_budget(c['negative_count']) and c['achieved_fp']<=c['fp_budget'],'Invalid frozen budget')
    decisions(np.array([],dtype=np.float64),c['threshold'])
    return dict(**artifact,seal_sha256=seal)
