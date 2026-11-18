"""Independent allowlisted metadata audit. Never import the failed audit runner.

All artifact reads, including hashing, go through MetadataReader. The reader
does not enumerate directories and rejects paths lexically before filesystem
resolution, stat, or open. This is an audit I/O policy, not a general OS sandbox.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET


class AccessDenied(ValueError):
    pass


class MetadataReader:
    def __init__(self, root, allowlist, forbidden=()):
        self.root=Path(os.path.abspath(root))
        self.allowed={self.key(p) for p in allowlist}
        self.forbidden={self.key(p) for p in forbidden}
        self.accesses=[]

    def key(self, path):
        raw=os.fspath(path).replace('\\','/')
        absolute=os.path.normpath(os.path.abspath(os.path.join(str(self.root),raw)))
        return os.path.normcase(absolute)

    def authorize(self,path):
        key=self.key(path)
        root=os.path.normcase(str(self.root))
        if os.path.commonpath([root,key])!=root:
            raise AccessDenied('Outside approved project root')
        relative=os.path.relpath(key,root).replace('\\','/')
        parts=relative.lower().split('/')
        blocked={'data','data2','raw','raw_data','campaign','campaigns','replay','replays',
                 'observation','observations','label','labels','prediction','predictions','private'}
        # Directory boundaries plus known raw/replay naming patterns. No
        # path is opened merely because it has a harmless-looking extension.
        excluded=any(p in blocked or p.startswith(('controlled_inventory','controlled_replay')) or
                     '_seed' in p and p.startswith(('train','val','test')) for p in parts[:-1])
        if key in self.forbidden or excluded or key not in self.allowed or Path(key).suffix.lower() not in {'.py','.json','.md','.xml','.txt'}:
            raise AccessDenied('Excluded or non-allowlisted audit artifact: '+relative)
        # Resolve only AFTER the lexical deny/allow decision. Approved symlinks
        # cannot turn a harmless source/report path into a data-tree read.
        candidate=Path(key)
        if os.path.normcase(str(candidate.resolve()))!=key:
            raise AccessDenied('Audit artifact redirects through a link')
        return candidate

    def read(self,path):
        candidate=self.authorize(path)
        value=candidate.read_bytes()
        self.accesses.append(dict(path=os.path.relpath(candidate,self.root).replace('\\','/'),
                                  size_bytes=len(value),sha256=hashlib.sha256(value).hexdigest()))
        return value

    def json(self,path):return json.loads(self.read(path))


def method_asts(data):
    cls=next(n for n in ast.parse(data).body if isinstance(n,ast.ClassDef))
    return {n.name:ast.dump(n,include_attributes=False) for n in cls.body if isinstance(n,ast.FunctionDef)}


def run(root, config, destination):
    """Config is a pre-reviewed allowlist object, never a Git/file-tree inventory."""
    root=Path(root);destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=False)
    reader=MetadataReader(root,config['allowlist'])
    affected=reader.json('reports/phase6/test_adapter_v1/scope_incident_v1/affected_paths_from_saved_metadata.json')
    reader.forbidden={reader.key(p) for p in affected['paths']}
    if reader.allowed & reader.forbidden:raise AccessDenied('Allowlist intersects original 722 excluded paths')
    checks=[]
    def check(name,ok,**detail):checks.append(dict(check=name,passed=bool(ok),**detail))
    cached={}
    for relative in config['allowlist']:
        cached[relative]=reader.read(relative)
        expected=config['expected_sha256'].get(relative)
        if expected:check('pinned_sha256:'+relative,hashlib.sha256(cached[relative]).hexdigest()==expected)
    original=method_asts(cached['src/phase6/local_inference.py'])
    additive=method_asts(cached['src/phase6/heldout_local_inference_v1.py'])
    neutral=set(original)-{'__init__','_preflight','try_model_candidate'}
    check('nine_neutral_methods_identical',len(neutral)==9 and all(original[n]==additive[n] for n in neutral))
    check('preflight_only_diagnostic_difference',original['_preflight'].replace('authorized VAL','authorized TEST')==additive['_preflight'])
    xml=ET.fromstring(cached['reports/phase6/test_adapter_v1/tests_final.xml'])
    suite=xml.find('testsuite');cases=list(suite.iter('testcase'))
    check('199_saved_tests_no_failure',int(suite.get('tests'))==len(cases)==199 and
          suite.get('failures')=='0' and suite.get('errors')=='0' and
          not any(c.find('failure') is not None or c.find('error') is not None or c.find('skipped') is not None for c in cases))
    names=[c.get('name') for c in cases]
    for name in ('test_original_val_and_new_test_synthetic_score_equivalence',
                 'test_high_degree_direct_accepted_sampler_and_masked_grid_batching',
                 'test_original_mlp_fixed_grid_pairing_and_exact_logits'):
        check('five_org_saved_equivalence:'+name,sum(n.startswith(name+'[') for n in names)==5)
    denied=[]
    for relative in affected['paths']:
        try:reader.authorize(relative)
        except AccessDenied:denied.append(relative)
        else:check('original_path_denied:'+relative,False)
    check('all_original_722_paths_denied_without_io',len(denied)==len(affected['paths'])==722)
    check('no_excluded_path_in_access_ledger',not ({reader.key(r['path']) for r in reader.accesses}&reader.forbidden))
    # Reconcile model identities from prior manifests ONLY. Do not open weights,
    # observations, labels, predictions, journals or any historical TEST path.
    prior=json.loads(cached['reports/phase6/test_adapter_v1/preservation_before.json'])
    pins=json.loads(cached['reports/phase6/inference/preregistration_v1.json'])['registry']
    models=[]
    for org,entry in pins['models'].items():
        check('prior_GraphSAGE_hash:'+org,prior.get(entry['model_path'])==entry['model_sha256'])
        for detector in ('graphsage','tabular_mlp'):
            relative=f'reports/phase6/calibration/v1/thresholds/{org}_{detector}.json'
            threshold=json.loads(cached[relative])
            check('threshold_model_protocol_identity:'+org+':'+detector,
                  threshold['organization']==org and threshold['detector']==detector and
                  threshold['protocol_sha256']==pins['protocol_sha256'])
            models.append(dict(organization=org,detector=detector,model_path=threshold['model_path'],
                               model_sha256=threshold['model_sha256'],threshold_sha256=hashlib.sha256(cached[relative]).hexdigest(),
                               evidence='Previously sealed threshold/model metadata; weights not reopened'))
    # Re-read only the same safe allowlist to verify preservation during audit.
    for relative,before in cached.items():check('audit_preserved:'+relative,reader.read(relative)==before)
    report=dict(status='PASS_CORRECTIVE_METADATA_AUDIT' if all(c['passed'] for c in checks) else 'REVIEW_REQUIRED',
                checks_passed=sum(c['passed'] for c in checks),checks_failed=sum(not c['passed'] for c in checks),
                allowlisted_files=len(cached),original_excluded_paths_denied=len(denied),
                excluded_payload_accesses=0,TEST_predictions_generated=0,weights_deserialized=0,
                saved_test_count=199,model_identity_metadata=models,
                original_incident_reversed=False,execution_approved=False,
                limitation='No fresh model-weight, dataset, private-journal or TEST integrity claim; prior evidence is retained as prior evidence.')
    for name,obj in [('summary.json',report),('checks.json',checks),('access_ledger.json',reader.accesses),('denied_paths.json',denied)]:
        with (destination/name).open('x',encoding='utf-8') as f:json.dump(obj,f,indent=2);f.write('\n')
    print(json.dumps({k:report[k] for k in ('status','checks_passed','checks_failed','allowlisted_files','original_excluded_paths_denied')}))
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    # One fixed bootstrap configuration, not an arbitrary inventory path.
    root=Path(__file__).resolve().parents[2]
    expected=root/'configs/phase6/adapter_metadata_audit_v1.json'
    if os.path.normcase(os.path.abspath(args.config))!=os.path.normcase(str(expected)):
        raise AccessDenied('Only the dedicated correction configuration may bootstrap the audit')
    run(root,json.loads(expected.read_bytes()),args.output)
