import csv,json,hashlib
from pathlib import Path
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');R=ROOT/'reports/phase6/final/v1';T=R/'tables';B=ROOT/'reports/phase6/detectability/technical_review_v2';HERE=Path(__file__).parent/'excel_all_phases_v1'
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def val(x):
 if x in [None,'']:return None
 if x in ['True','False']:return x=='True'
 if isinstance(x,(dict,list)):return json.dumps(x)
 if not isinstance(x,str):return x
 try:return int(x)
 except ValueError:
  try:return float(x)
  except ValueError:return x
def data(p):
 with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
tabs=[]
def tab(name,p):
 rs=data(p);headers=list(rs[0]);tabs.append(dict(name=name,source=str(p),headers=headers,rows=[[val(r[k]) for k in headers] for r in rs]))
for name,file in [('Fixed grid','fixed_grid_metrics'),('Calibration','calibration'),('Prevalence','prevalence_and_masks'),('Inductive','inductive_subgroups'),('Seeds','seed_metrics'),('Grid factors','fixed_grid_factor_metrics'),('Histories','training_histories'),('Training resources','training_resources'),('Campaign context','campaign_context_v2'),('Detection times','time_to_detection')]:tab(name,T/(file+'.csv'))
for name,p in [('Campaigns',B/'continuation_00004/campaign_results.csv'),('Organization trials',B/'continuation_00004/organization_results.csv'),('Operational factors',B/'final_v1/factor_results.csv'),('Factor seed coverage',B/'continuation_00004/factor_seed_results.csv'),('Inference resources',B/'final_v1/resource_summary.csv')]:tab(name,p)
a=load(R/'research_alignment.json');headers=['id','kind','original','designed','implemented','evidence','unsupported','subsequent_phases','paper_can_claim','paper_cannot_claim','status'];tabs.insert(0,dict(name='RQ and contributions',source=str(R/'research_alignment.json'),headers=headers,rows=[[r[k] for k in headers] for r in a['rows']]))
aggregates=load(T/'aggregation.json');headers=list(dict.fromkeys(k for row in aggregates for k in row));tabs.insert(2,dict(name='Aggregation',source=str(T/'aggregation.json'),headers=headers,rows=[[val(r.get(k)) for k in headers] for r in aggregates]))
hashes=load(T/'input_sha256.json');hashes.update(load(R/'additional_source_sha256.json'))
for t in tabs:
 p=Path(t['source'])
 with p.open('rb') as f:hashes[str(p)]=hashlib.file_digest(f,'sha256').hexdigest()
tabs.append(dict(name='Sources',source='Frozen reporting and additional input SHA256 inventories',headers=['Source path','SHA256'],rows=[[k,v] for k,v in sorted(hashes.items())]))
payload=dict(tabs=tabs,scope='OPTION_A_TRAIN_VAL_ONLY',phase6_complete=False,test_access=False,aggregate=load(T/'aggregation.json'),operational=load(B/'final_v1/summary.json'),alignment=a)
with (HERE/'subphase9_workbook_inputs_v2.json').open('x',encoding='utf-8') as f:json.dump(payload,f)
print('Workbook inputs prepared:',len(tabs)+1,'sheets')
