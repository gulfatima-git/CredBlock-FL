"""Independent sklearn/stdlib comparison from saved TRAIN/VAL scores, no model calls."""
from pathlib import Path
import json,csv,sys,math,hashlib
import numpy as np
from sklearn.metrics import average_precision_score,roc_auc_score,log_loss,confusion_matrix
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');OUT=ROOT/'reports/phase6/final/v1';cfg=json.loads((ROOT/'configs/phase6/final_reporting_v1.json').read_text())
def csvread(p):
 with Path(p).open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
metrics=csvread(OUT/'tables/fixed_grid_metrics.csv');proof=[]
for item in cfg['predictions']:
 assert item['split'] in ['TRAIN','VAL'] and '_TEST' not in item['path']
 rows=csvread(item['path']);eligible=[r for r in rows if r['eligible_mask']=='True'];y=np.array([int(r['node_label']) for r in eligible]);z=np.array([float(r['logit']) for r in eligible],dtype=np.float64)
 art=json.loads(Path(item['threshold_path']).read_text());th=art['calibration']['threshold'];p=z>=float.fromhex(th['hex']) if th['kind']=='finite' else np.zeros(len(y),dtype=bool)
 tn,fp,fn,tp=confusion_matrix(y,p,labels=[0,1]).ravel();probs=np.empty_like(z);pos=z>=0;probs[pos]=1/(1+np.exp(-z[pos]));exp=np.exp(z[~pos]);probs[~pos]=exp/(1+exp)
 actual=next(r for r in metrics if (r['organization'],r['split'],r['detector'])==(item['organization'],item['split'],item['detector']))
 for k,v in dict(tp=tp,fp=fp,tn=tn,fn=fn).items():assert int(actual[k])==v,(item,k)
 ap=float(average_precision_score(y,z));auc=float(roc_auc_score(y,z))
 assert abs(float(actual['average_precision'])-ap)<1e-12
 assert abs(float(actual['roc_auc'])-auc)<1e-12
 # Stable standard-library logit loss: independent implementation avoids sigmoid clipping.
 bce=math.fsum(max(float(s),0)-float(s)*int(t)+math.log1p(math.exp(-abs(float(s)))) for t,s in zip(y,z))/len(y)
 assert abs(float(actual['bce'])-bce)<1e-12
 proof.append(dict(organization=item['organization'],split=item['split'],detector=item['detector'],eligible=len(y),tp=int(tp),fp=int(fp),tn=int(tn),fn=int(fn),independent_ap=ap,independent_roc_auc=auc,independent_bce=bce,status='PASS'))
baseline=json.loads((OUT/'preservation_metadata_before.json').read_text());changed=[]
for p,s in baseline.items():
 st=(ROOT/p).stat()
 if (st.st_size,st.st_mtime_ns)!=(s['size'],s['mtime_ns']):changed.append(p)
assert not changed,changed
result=dict(status='PASS_INDEPENDENT_SAVED_SCORE_RECONCILIATION',components=proof,independent_metric_oracles=['sklearn.average_precision_score','sklearn.roc_auc_score','sklearn.confusion_matrix','stdlib stable logit loss via math.fsum'],preexisting_paths_metadata_unchanged=len(baseline),test_payloads_opened=0,original_evaluator_called=False,model_inference=False)
with (OUT/'independent_reconciliation.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
print(json.dumps(dict(status=result['status'],components=len(proof),preserved_metadata_paths=len(baseline))))
