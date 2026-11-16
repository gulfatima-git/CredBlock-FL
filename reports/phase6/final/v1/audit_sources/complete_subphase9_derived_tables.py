from pathlib import Path
import json,csv,hashlib,statistics
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');OUT=ROOT/'reports/phase6/final/v1';BASE=ROOT/'reports/phase6/detectability';TAB=OUT/'tables'
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def rows(p):
 with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def writecsv(p,rs):
 with p.open('x',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
sources={};context=[]
for r in load(BASE/'required_val_inventory_v1.json'):
 p=ROOT/'data/phase5/controlled_replay_labels_all_orgs_causal_v1'/r['variant_id']/'replay_manifest.json';h=sha(p);assert h==r['manifest_sha256'];sources[str(p)]=h;m=load(p);branches=m['branches'];synthetic=sum(b['synthetic_events'] for b in branches);background=sum(b['background_events'] for b in branches);targetbg=sum(b['background_events'] for b in branches if b['organization'] in r['targeted_organizations'])
 context.append(dict(variant_id=r['variant_id'],seed=r['seed'],design_family=r['factors']['family'],RIP=r['factors']['RIP_target'],Raccount=r['factors']['Raccount_target'],Sorg=r['factors']['Sorg_target'],synthetic_attempts=synthetic,background_events_all_five=background,background_events_targeted=targetbg,attack_to_targeted_background_ratio=synthetic/targetbg if targetbg else None,attempts_per_minute=synthetic/60,targeted_local_user_occurrences=sum(b['targeted_users'] for b in branches),targeted_organizations='|'.join(r['targeted_organizations']),anchor=r['start'],end_exclusive=r['end_exclusive']))
writecsv(TAB/'campaign_context_v2.csv',context)
campaigns=rows(BASE/'technical_review_v2/continuation_00004/campaign_results.csv');orgs=rows(BASE/'technical_review_v2/continuation_00004/organization_results.csv');userspath=BASE/'technical_review_v2/continuation_00004/user_occurrence_statistics_no_ids.json';users=load(userspath);sources[str(userspath)]=sha(userspath)
ttd=[]
for f in ['local_only','local_plus_indicator']:
 for name,rs,field,famkey,origin in [('campaign',[r for r in campaigns if r['detector_family']==f],'event_time_seconds','detector_family','actual_global_campaign_onset'),('targeted_organization_trial',[r for r in orgs if r['detector_family']==f],'event_time_seconds','detector_family','actual_global_campaign_onset'),('local_target_User_occurrence',[r for r in users if r['family']==f],'event_time_seconds','family','first_local_User_positive_exposure')]:
  times=[float(r[field]) for r in rs if r[field] not in [None,'']];assert all(t>=0 for t in times)
  ttd.append(dict(policy=f,unit=name,denominator=len(rs),detected=len(times),right_censored=len(rs)-len(times),median_detected_delay_seconds=statistics.median(times) if times else None,min_detected_delay_seconds=min(times) if times else None,max_detected_delay_seconds=max(times) if times else None,time_origin=origin,note='Detected-only descriptive delays; censored observations never receive finite detection time; no IID CI'))
writecsv(TAB/'time_to_detection.csv',ttd)
alignment=load(OUT/'research_alignment.json');writecsv(TAB/'research_alignment.csv',alignment['rows'])
with (OUT/'additional_source_sha256.json').open('x',encoding='utf-8') as f:json.dump(sources,f,indent=2)
# Correct only figure presentation conventions; keep original draft PNG/PDF files intact.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'pdf.fonttype':42,'savefig.bbox':'tight'})
curves=load(TAB/'validation_curves.json');fixed=rows(TAB/'fixed_grid_metrics.csv');manifest=load(OUT/'figure_manifest.json');colors={'graphsage':'#24537B','tabular_mlp':'#C45A83'};orgnames=['Org1','Org2','Org3','Org4','Org5'];dest=ROOT/'outputs/phase6_final_v1/figures'
for typ,name,old in [('PR','03_val_pr_final','03_val_pr'),('ROC','04_val_roc_final','04_val_roc')]:
 fig,axs=plt.subplots(2,3,figsize=(12,7));axs=axs.ravel()
 for ax,o in zip(axs,orgnames):
  for d in colors:
   rs=[r for r in curves if r['organization']==o and r['detector']==d];x=[0]+[r['recall' if typ=='PR' else 'fpr'] for r in rs];y=[1 if typ=='PR' else 0]+[r['precision' if typ=='PR' else 'recall'] for r in rs]
   if typ=='PR':ax.step(x,y,where='pre',color=colors[d],label=d)
   else:ax.plot(x,y,color=colors[d],label=d)
   r=next(r for r in fixed if r['organization']==o and r['detector']==d and r['split']=='VAL');ax.scatter([float(r['recall' if typ=='PR' else 'fpr'])],[float(r['precision' if typ=='PR' else 'recall'])],color=colors[d],s=30)
  ax.set_title(o);ax.set_xlim(0,1);ax.set_ylim(0,1.02);ax.set_xlabel('Recall' if typ=='PR' else 'FPR');ax.set_ylabel('Precision' if typ=='PR' else 'Recall');ax.legend(fontsize=7)
 axs[-1].axis('off');fig.tight_layout()
 for ext in ['png','pdf']:fig.savefig(dest/(name+'.'+ext),dpi=220)
 plt.close(fig)
 for r in manifest['figures']:
  if r['figure']==old:r.update(figure=name,png='figures/'+name+'.png',pdf='figures/'+name+'.pdf')
manifest['drafts_preserved']=['03_val_pr.png/pdf','04_val_roc.png/pdf'];manifest['presentation_correction']='PR staircase uses endpoint precision for each recall increment, consistent with noninterpolated AP; ROC uses linear interpolation consistent with trapezoidal ROC-AUC. Numerical source curves and metrics unchanged.'
with (OUT/'figure_manifest_v2.json').open('x',encoding='utf-8') as f:json.dump(manifest,f,indent=2)
print('Complete context, TTD, alignment tables and final PR/ROC figures created additively')
