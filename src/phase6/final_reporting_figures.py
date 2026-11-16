"""Publication figures from saved reporting tables only; no inference or evaluation."""
import json,csv,hashlib
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def build(root):
 root=Path(root);report=root/'reports/phase6/final/v1';tables=report/'tables';dest=root/'outputs/phase6_final_v1';dest.mkdir(exist_ok=False);figdir=dest/'figures';figdir.mkdir()
 def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
 def csvread(p):
  with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
 sources={}
 def pin(p,h=None):
  with p.open('rb') as f:got=hashlib.file_digest(f,'sha256').hexdigest()
  if h:assert got==h
  sources[str(p)]=got;return p
 plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.bbox':'tight','pdf.fonttype':42})
 orgs=['Org1','Org2','Org3','Org4','Org5'];colors={'graphsage':'#24537B','tabular_mlp':'#C45A83','local_only':'#24537B','local_plus_indicator':'#47856A'};records=[]
 def savefig(fig,name,caption,source):
  for ext in ['png','pdf']:fig.savefig(figdir/f'{name}.{ext}',dpi=220)
  plt.close(fig);records.append(dict(figure=name,caption=caption,source=source,png=f'figures/{name}.png',pdf=f'figures/{name}.pdf'))
 prevalence=csvread(pin(tables/'prevalence_and_masks.csv'));fixed=csvread(pin(tables/'fixed_grid_metrics.csv'));history=csvread(pin(tables/'training_histories.csv'));curves=read(pin(tables/'validation_curves.json'))
 fig,axs=plt.subplots(1,2,figsize=(11,4))
 for ax,split in zip(axs,['TRAIN','VAL']):
  rs=[r for r in prevalence if r['split']==split];bottom=np.zeros(5)
  for field,label,color in [('negative','Eligible negative','#AABCD0'),('positive','Eligible positive','#C45A83'),('masked_recent_roots','Masked recent root','#D7D9DC')]:
   val=np.array([int(r[field]) for r in rs]);ax.bar(orgs,val,bottom=bottom,label=label,color=color);bottom+=val
  ax.set_title(split);ax.set_ylabel('Saved root User-time rows');ax.ticklabel_format(axis='y',style='sci',scilimits=(0,0))
 axs[0].legend(fontsize=8);fig.tight_layout();savefig(fig,'01_prevalence_masks','Eligible and masked saved roots; older context nodes are not negative examples.','prevalence_and_masks.csv')
 fig,axs=plt.subplots(5,2,figsize=(12,14))
 for i,o in enumerate(orgs):
  for d in colors.keys() & {'graphsage','tabular_mlp'}:
   for candidate in ['hidden16','hidden32']:
    rs=[r for r in history if r['organization']==o and r['detector']==d and r['candidate']==candidate];style='-' if candidate=='hidden16' else '--';x=[int(r['epoch']) for r in rs]
    axs[i,0].plot(x,[float(r['train_weighted_bce']) for r in rs],style,color=colors[d],label=d+' '+candidate)
    axs[i,1].plot(x,[float(r['validation_ap']) for r in rs],style,color=colors[d],label=d+' '+candidate)
    if rs and rs[0]['selected_candidate']=='True':
     e=int(rs[0]['selected_epoch']);r=next(t for t in rs if int(t['epoch'])==e);axs[i,1].scatter([e],[float(r['validation_ap'])],color=colors[d],marker='*',s=90,zorder=5)
  axs[i,0].set_ylabel(o+' weighted TRAIN BCE');axs[i,1].set_ylabel(o+' VAL AP');axs[i,0].set_xlabel('Epoch');axs[i,1].set_xlabel('Epoch')
 axs[0,0].legend(fontsize=7);axs[0,1].set_title('Stars: selected checkpoints');fig.tight_layout();savefig(fig,'02_learning_curves','Saved candidate histories; weighted TRAIN loss and VAL AP are different quantities.','training_histories.csv')
 for typ in ['PR','ROC']:
  fig,axs=plt.subplots(2,3,figsize=(12,7));axs=axs.ravel()
  for ax,o in zip(axs,orgs):
   for d in ['graphsage','tabular_mlp']:
    rs=[r for r in curves if r['organization']==o and r['detector']==d];x=[0]+[r['recall' if typ=='PR' else 'fpr'] for r in rs];y=[1 if typ=='PR' else 0]+[r['precision' if typ=='PR' else 'recall'] for r in rs]
    ax.step(x,y,where='post' if typ=='PR' else 'pre',color=colors[d],label=d)
    row=next(r for r in fixed if r['organization']==o and r['detector']==d and r['split']=='VAL');ax.scatter([float(row['recall' if typ=='PR' else 'fpr'])],[float(row['precision' if typ=='PR' else 'recall'])],color=colors[d],s=35)
   ax.set_title(o);ax.set_xlim(0,1);ax.set_ylim(0,1.02);ax.set_xlabel('Recall' if typ=='PR' else 'FPR');ax.set_ylabel('Precision' if typ=='PR' else 'Recall');ax.legend(fontsize=7)
  axs[-1].axis('off');fig.tight_layout();savefig(fig,'03_val_pr' if typ=='PR' else '04_val_roc','VAL '+typ+' curves with frozen-threshold markers. AP uses tied-score noninterpolated groups; curves do not tune thresholds.','validation_curves.json; fixed_grid_metrics.csv')
 fig,axs=plt.subplots(1,3,figsize=(13,4));x=np.arange(5)
 for ax,field,title in zip(axs,['average_precision','recall','fpr'],['VAL AP','Recall at frozen threshold','Achieved VAL FPR']):
  for j,d in enumerate(['graphsage','tabular_mlp']):
   rs=[next(r for r in fixed if r['organization']==o and r['detector']==d and r['split']=='VAL') for o in orgs];ax.bar(x+(j-.5)*.36,[float(r[field]) for r in rs],.36,label=d,color=colors[d])
  ax.set_xticks(x,orgs);ax.set_title(title);ax.set_ylim(bottom=0)
 axs[0].legend(fontsize=8);axs[2].axhline(.01,color='black',ls=':',label='VAL target');fig.tight_layout();savefig(fig,'05_fixed_grid_comparison','Both detector families on identical eligible VAL grid examples; no detector re-selection.','fixed_grid_metrics.csv')
 base=root/'reports/phase6/detectability/technical_review_v2';ops=read(pin(base/'final_v1/summary.json'));orgrows=csvread(pin(base/'final_v1/per_organization_results.csv'))
 fig,axs=plt.subplots(1,2,figsize=(12,4))
 for j,f in enumerate(['local_only','local_plus_indicator']):
  rs=[next(r for r in orgrows if r['organization']==o and r['detector_family']==f) for o in orgs]
  axs[0].bar(x+(j-.5)*.36,[float(r['detected_user_percent']) for r in rs],.36,label=f,color=colors[f]);axs[1].bar(x+(j-.5)*.36,[int(r['detected_org_campaign_trials'])/int(r['targeted_org_campaign_trials']) for r in rs],.36,label=f,color=colors[f])
 for ax in axs:ax.set_xticks(x,orgs);ax.legend(fontsize=7)
 axs[0].set_ylabel('Detected target-User occurrences (%)');axs[1].set_ylabel('Detected targeted-organization trials / total');axs[1].set_ylim(0,1.05);fig.tight_layout();savefig(fig,'06_operational_coverage','Operational coverage; not fixed-grid FPR/recall. Org5 missed trial remains visible.','per_organization_results.csv')
 factors=csvread(pin(base/'final_v1/factor_results.csv'))
 fig,axs=plt.subplots(1,3,figsize=(13,4))
 for ax,factor,family in zip(axs,['RIP_target','Raccount_target','Sorg_target'],['Raccount_fixed_per_org_attempts','Raccount_fixed_per_org_attempts','Sorg_fixed_per_org_attempts']):
  for f in ['local_only','local_plus_indicator']:
   rs=sorted([r for r in factors if r['factor']==factor and r['design_family']==family and r['detector_family']==f],key=lambda r:float(r['level']));ax.plot([float(r['level']) for r in rs],[float(r['detected_user_percent']) for r in rs],marker='o',label=f,color=colors[f])
  ax.set_xlabel(factor);ax.set_title(family.replace('_fixed_per_org_attempts',''));ax.set_ylabel('Detected target-User occurrences (%)');ax.legend(fontsize=7)
 fig.tight_layout();savefig(fig,'07_factor_user_coverage','Descriptive marginal factor summaries within specified families; no IID or causal factor-effect claim. Full tables retain other family strata.','factor_results.csv')
 cells=csvread(pin(base/'continuation_00004/factor_seed_results.csv'));fig,ax=plt.subplots(figsize=(10,4));groups={}
 for r in cells:
  key=(r['detector_family'],r['family']);n,u=groups.get(key,(0,0));groups[key]=(n+int(r['evaluated_complete_campaigns']),u+int(r['undetected_campaigns']))
 for i,(key,(n,u)) in enumerate(sorted(groups.items())):
  ax.scatter(i,u/n,color=colors[key[0]],s=65);ax.annotate(f'{u}/{n}',(i,u/n),xytext=(0,8),textcoords='offset points',ha='center')
 ax.set_xticks(range(len(groups)),[k[1].replace('_fixed_per_org_attempts','')+'\n'+k[0] for k in sorted(groups)],fontsize=8);ax.set_ylim(-.03,.2);ax.set_ylabel('Wholly undetected campaign fraction');ax.set_title('Zero observed wholly undetected VAL campaigns; no fitted boundary curve');fig.tight_layout();savefig(fig,'08_zero_undetected_boundary','Explicit numerator/denominator for the empty non-detection subset, separated by design family and policy.','factor_seed_results.csv')
 campaigns=csvread(pin(base/'continuation_00004/campaign_results.csv'));orgtime=csvread(pin(base/'continuation_00004/organization_results.csv'));fig,axs=plt.subplots(1,2,figsize=(11,4))
 for f in ['local_only','local_plus_indicator']:
  for ax,rs in [(axs[0],[r for r in campaigns if r['detector_family']==f]),(axs[1],[r for r in orgtime if r['detector_family']==f])]:
   times=sorted(float(r['event_time_seconds']) for r in rs if r['event_time_seconds']);ax.step(times,np.arange(1,len(times)+1)/len(rs),where='post',color=colors[f],label=f)
 axs[0].set_title('Campaign: 0 censored / 171 per policy');axs[1].set_title('Targeted org trial: 1 censored / 549 per policy')
 for ax in axs:ax.set_xlabel('Seconds from actual global onset');ax.set_ylabel('Observed detected fraction of all trials');ax.legend(fontsize=8);ax.set_ylim(0,1.02)
 fig.tight_layout();savefig(fig,'09_detection_time','Descriptive observed cumulative detections; censored trials remain in denominator, not assigned finite event times. This is not an IID survival estimate.','campaign_results.csv; organization_results.csv')
 resource=csvread(pin(base/'final_v1/resource_summary.csv'));trainres=csvread(pin(tables/'training_resources.csv'));fig,axs=plt.subplots(1,2,figsize=(11,4))
 med=np.array([float(r['median_replay_p95_timestamp_latency_seconds']) for r in resource]);lo=np.array([float(r['minimum_replay_p95_timestamp_latency_seconds']) for r in resource]);hi=np.array([float(r['maximum_replay_p95_timestamp_latency_seconds']) for r in resource]);axs[0].errorbar(x,med,yerr=[med-lo,hi-med],fmt='o',capsize=4,color=colors['graphsage']);axs[0].set_xticks(x,orgs);axs[0].set_ylabel('Per-replay p95 timestamp latency (s)');axs[0].set_title('Median and range across saved replays, not CI')
 for j,d in enumerate(['graphsage','tabular_mlp']):
  rr=[next(r for r in trainres if r['organization']==o and r['detector']==d) for o in orgs];axs[1].bar(x+(j-.5)*.36,[float(r['observed_training_rss_mib']) for r in rr],.36,color=colors[d],label=d)
 axs[1].set_xticks(x,orgs);axs[1].set_ylabel('Observed training-process RSS (MiB)');axs[1].legend(fontsize=8);fig.tight_layout();savefig(fig,'10_resource_scope','Original CPU measurements; no new inference benchmark. Latency includes graph/features/journal work; no production real-time SLA established.','resource_summary.csv; training_resources.csv')
 sub=csvread(pin(tables/'inductive_subgroups.csv'));fig,axs=plt.subplots(1,2,figsize=(11,4))
 for ax,g in zip(axs,['unseen_user','unseen_ip_context']):
  for j,d in enumerate(['graphsage','tabular_mlp']):
   rr=[next(r for r in sub if r['organization']==o and r['detector']==d and r['subgroup']==g) for o in orgs];ax.bar(x+(j-.5)*.36,[float(r['recall']) for r in rr],.36,color=colors[d],label=d)
  ax.set_xticks(x,orgs);ax.set_ylabel('VAL recall at frozen local threshold');ax.set_title(g);ax.legend(fontsize=8)
 fig.tight_layout();savefig(fig,'11_inductive_subgroups','Accepted TRAIN-unseen flags reused; IPs remain context nodes, not classification targets.','inductive_subgroups.csv')
 # Existing campaign metadata only, no replay/labels or new campaign evaluation.
 inventory=read(pin(root/'reports/phase6/detectability/required_val_inventory_v1.json'));context=[]
 for r in inventory:
  v=r['variant_id'];p=root/'data/phase5/controlled_replay_labels_all_orgs_causal_v1'/v/'replay_manifest.json';m=read(pin(p,r['manifest_sha256']));branches=m['branches'];targets=set(r['targeted_organizations']);synthetic=sum(b['synthetic_events'] for b in branches)
  # Manifest event field is inspected explicitly rather than guessing a new source schema.
  context.append(dict(variant_id=v,seed=r['seed'],design_family=r['factors']['family'],RIP=r['factors']['RIP_target'],Raccount=r['factors']['Raccount_target'],Sorg=r['factors']['Sorg_target'],synthetic_attempts=synthetic,duration_seconds=3600,synthetic_attempts_per_minute=synthetic/60,targeted_organizations='|'.join(r['targeted_organizations'])))
 with (tables/'campaign_context.csv').open('x',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=list(context[0]));w.writeheader();w.writerows(context)
 with (report/'figure_manifest.json').open('x',encoding='utf-8') as f:json.dump(dict(status='PASS_FIGURES_FROM_SAVED_EVIDENCE',figures=records,source_sha256=sources,matplotlib_version=matplotlib.__version__,test_outcomes_accessed=False),f,indent=2)
 print('Created',len(records),'publication figures in PNG/PDF; no model execution')

if __name__=='__main__':build(Path(__file__).resolve().parents[2])
