#!/usr/bin/env python3
"""Close the Phase 5 graph gate using verified reports; preserve the v1 freeze."""
from pathlib import Path
import argparse
import hashlib
import json


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()


def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def require(ok,message='Phase 5 acceptance condition failed'):
    if not ok:raise ValueError(message)


def save(p,value):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2,default=str);f.write('\n')


def run(root,graph_report,freeze_dir,output):
    import pandas as pd
    require(not output.exists(),'Output exists; refusing overwrite')
    g=read(graph_report/'summary.json');d=read(freeze_dir/'summary.json')
    require(g['status']=='PASS_PHASE5_GRAPH_RETENTION_REPRESENTATIVE_INTEGRATION')
    require(g['all_read_input_hashes_unchanged'] and g['all_five_organizations_validated'])
    require(g['unit_tests_passed']==20 and g['representative_attack_branches']==45)
    require(g['pure_background_controls']==45 and g['asof_feature_edge_label_checks']==315)
    require(g['frozen_dataset_manifest_sha256']==sha(freeze_dir/'dataset_freeze_manifest.json'))
    for rel,h in g['accepted_graph_code_sha256'].items():
        require(sha(Path(__file__).resolve().parent/rel)==h,'Graph code changed after validation')
    cases=pd.read_csv(graph_report/'branches.csv')
    require(len(cases)==45 and (cases['status']=='PASS_GRAPH_INTEGRATION').all())
    require(all(set(group['organization'])=={f'Org{i}' for i in range(1,6)}
                for _,group in cases.groupby('variant_id')))
    require(cases.groupby('split').size().to_dict()=={'TEST':15,'TRAIN':15,'VAL':15})
    register=pd.read_csv(freeze_dir/'campaign_register.csv')
    expected=register[(register['family']=='Sorg_fixed_per_org_attempts') &
        (register['Sorg_target']==5) & (register['RIP_target']==.5) & (register['Raccount_target']==.5)]
    require(set(cases['variant_id'])==set(expected['variant_id']) and len(expected)==9)
    frozen=read(freeze_dir/'dataset_freeze_manifest.json')
    hashes={str(root/r['path_relative_to_project']):r['sha256'] for r in frozen['files']}
    replay=root/'data/phase5/controlled_replay_labels_all_orgs_causal_v1'
    replay_summary=read(replay/'summary.json');inventory=Path(replay_summary['inventory_input'])
    checked={}
    for vid in expected['variant_id']:
        for p in [inventory/vid/'manifest.json',replay/vid/'replay_manifest.json']:
            actual=sha(p);require(actual==hashes[str(p)],'Frozen representative protocol metadata changed')
            checked[str(p)]=actual
    output.mkdir(parents=True,exist_ok=False)
    import sys,platform
    from importlib.metadata import version
    save(output/'validation_environment.json',{'python':sys.version,'platform':platform.platform(),
        'packages':{name:version(name) for name in ['numpy','pandas','duckdb','torch','torch-geometric']}})
    register['graph_edge_retention_integration']='PASS_SHARED_ROLLING_RUNTIME_V1'
    register['graph_features_executed_for_this_instance']=register['variant_id'].isin(set(expected['variant_id']))
    register['graph_validation_scope']='Representative runtime validation; see per-instance execution flag'
    register.to_csv(output/'campaign_register_v2.csv',index=False,na_rep='N/A')
    runtime_manifest={'version':'phase5-graph-runtime-manifest-v1',
        'entrypoint':'src.organization.rolling_graph_v1.OrganizationGraphRuntime',
        'legacy_cumulative_builder_and_updater_accepted_for_new_training':False,
        'code_sha256':g['accepted_graph_code_sha256'],
        'dataset_freeze_manifest_sha256':g['frozen_dataset_manifest_sha256'],
        'feature_schema':read(graph_report/'graph_runtime_contract.json')['features'],
        'schema_count_scope':'retained7d_recent10m',
        'installation':'Add new files; retain old modules for historical reproduction'}
    save(output/'phase5_graph_runtime_manifest_v1.json',runtime_manifest)
    final={'version':'phase5-final-acceptance-v2','status':'PASS_PHASE5_DATA_AND_ROLLING_GRAPH_VALIDATION',
        'phase5_validation_complete':True,'ready_for_phase6_implementation':True,
        'source_installation_required':True,'main_project_existing_modules_modified':False,
        'dataset_freeze_preserved':True,'frozen_files':d['frozen_file_count'],
        'instances':513,'replay_branches':2565,'oracle_checked_label_states':d['oracle_checked_label_states'],
        'graph_unit_tests':20,'representative_graph_attack_branches':45,'graph_background_controls':45,
        'graph_asof_feature_edge_label_checks':315,'expired_real_events_exercised':g['expired_events_exercised'],
        'graph_code':g['accepted_graph_code_sha256'],
        'dataset_freeze_manifest_sha256':g['frozen_dataset_manifest_sha256'],
        'representative_protocol_metadata_sha256':checked,
        'graph_training_entrypoint':runtime_manifest['entrypoint'],
        'graphsage_implemented':False,'model_training_performed':False,
        'scope':'Full event/label validation plus fixed representative graph integration across every split/seed/org; not a graph-feature rerun of all 2565 branches',
        'open_phase5_validation_gates':[],
        'phase6_gates':['Adopt the new runtime source files before importing it in the main project.',
            'Implement GraphSAGE and train/validation/test orchestration.',
            'Fit any learned preprocessing on TRAIN only; tune thresholds/hyperparameters on VAL.',
            'Test actual model input construction, sampling and training/evaluation isolation before final evaluation.'],
        'later_phases':'Federation, formal user-level privacy, robustness and Fabric remain unimplemented.',
        'next_step':'Install new files once, then begin Phase 6 GraphSAGE implementation.'}
    save(output/'summary.json',final)
    report=f'''# CredBlock-FL Phase 5 final acceptance v2

**Phase 5 data and rolling-graph validation: PASS.** The earlier graph-retention
gate is resolved by the new versioned runtime. This supersedes the conditional
v1 acceptance decision; it does not alter the frozen dataset or old reports.

| Verified scope | Result |
|---|---:|
| Controlled instances, including descriptive references | 513 |
| All-organization replay branches | 2,565 |
| Previously oracle-checked User/time labels | {d['oracle_checked_label_states']:,} |
| New graph unit tests | 20/20 |
| Real graph attack branches | 45, across all splits/seeds/organizations |
| Pure-background feature controls | 45 |
| As-of feature/edge/label checks | 315 |
| Real events aged out during checked replay hours | {g['expired_events_exercised']:,} |

The accepted API is `src.organization.rolling_graph_v1.OrganizationGraphRuntime`.
It initializes from bounded past observations, expires seven-day events and
structural edges, removes orphan nodes from active tensors, maintains ten-minute
features and supports verified checkpoint restart/resume. Trainer and detector
views read the same persistent state. Evaluator labels/masks are separate from
the observable PyG model packet. Integer counts/edges match the independent SQL
oracle exactly; float32 feature transforms use the documented tolerance.

The graph protocol was fixed at Sorg-family Sorg5/RIP=.50/Raccount=.50 for every
split/seed and all five organizations. It validates the reusable implementation
on 45 real branches and 45 background controls. It is not a claim that graph
features were replayed for all 2,565 branches, and it is not model performance.

Legacy modules remain unchanged for reproducing historical results. The new
files must be installed in the main project to adopt this accepted path; its
future GraphSAGE code must not call the old cumulative graph updater.

The event/label freeze is unchanged. Raccount coverage/intensity, Sorg
composition/volume, repeated-background dependence and three temporal blocks per
split remain documented limitations. Source flags do not certify benignness.
Optional fixed-total sensitivity data is not claimed. External Sheets was not
updated.

**Progress:** all four handover closeout milestones are validated. One-time source
installation remains before using the new API from the main project. Next is
Phase 6 GraphSAGE implementation; no model training, federation, formal privacy,
poisoning robustness or Fabric result is claimed here.
'''
    (output/'FINAL_ACCEPTANCE_REPORT.md').write_text(report,encoding='utf-8')
    save(output/'output_sha256.json',{p.name:sha(p) for p in sorted(output.iterdir()) if p.is_file()})
    print(final['status']);print(output)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path.cwd())
    p.add_argument('--graph-report',type=Path)
    p.add_argument('--freeze-dir',type=Path)
    p.add_argument('--output',type=Path)
    a=p.parse_args();root=a.root.resolve()
    run(root,(a.graph_report or root/'reports/phase5_graph_retention_v1').resolve(),
        (a.freeze_dir or root/'reports/phase5_dataset_freeze_v1').resolve(),
        (a.output or root/'reports/phase5_final_acceptance_v2').resolve())
