"""Plot measured selected-trial curves after the five-model gate passes."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

ROOT=Path(__file__).resolve().parents[3]
result=json.loads((ROOT/'reports/phase6/training/final_v1/summary.json').read_text())
if result['organizations']!=5 or not result['status'].startswith('PASS_SUBPHASE3_FULL_FIVE'):
    raise ValueError('Full five-model verification required')
destination=ROOT/'outputs/phase6_subphase3_v1'
destination.mkdir(parents=True,exist_ok=True)
file=destination/'selected_training_curves_v1.png'
if file.exists(): raise FileExistsError('Refusing to overwrite training curves')
fig,axes=plt.subplots(5,2,figsize=(12,17),constrained_layout=False)
for row,record in enumerate(result['models']):
    org=record['organization']
    directory=Path(record['component_directory'])/'models'/org/record['selected_candidate']['id']
    data=[json.loads(line) for line in (directory/'epochs.jsonl').read_text().splitlines()]
    epochs=[r['epoch'] for r in data]
    left,right=axes[row]
    left.plot(epochs,[r['train_weighted_bce'] for r in data],label='TRAIN weighted BCE',color='#28643B',marker='o',markersize=3)
    left.plot(epochs,[r['validation']['bce'] for r in data],label='VAL unweighted BCE',color='#9E4D65',marker='s',markersize=3)
    left.set_ylabel('BCE loss');left.set_ylim(bottom=0)
    right.plot(epochs,[r['validation']['average_precision'] for r in data],label='VAL average precision',color='#24598A',marker='o',markersize=3)
    right.set_ylabel('Average precision');right.set_ylim(0,1.02)
    for axis in [left,right]:
        axis.axvline(record['selected_epoch'],linestyle='--',color='#777777',linewidth=1,label='Selected epoch')
        axis.set_title(f"{org} | hidden width {record['selected_candidate']['hidden_dim']} | seed {record['initialization_seed']}",fontsize=10)
        axis.set_xlabel('Epoch');axis.xaxis.set_major_locator(MaxNLocator(integer=True))
        axis.grid(alpha=0.2);axis.spines[['top','right']].set_visible(False)
        axis.legend(fontsize=8,loc='best')
fig.suptitle('Five independent local GraphSAGE models: full TRAIN / VAL inventory',fontsize=14,y=0.99)
fig.text(0.5,0.012,'Validation was used for selection. Fixed sampled inputs; dependent controlled branches. No TEST or calibrated-FPR results.',ha='center',fontsize=9)
fig.tight_layout(rect=[0,0.03,1,0.97],h_pad=1.7)
fig.savefig(file,dpi=160)
print(file)
