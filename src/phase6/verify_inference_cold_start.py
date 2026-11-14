"""Additional independent-process recovery audit on a private copy of a closed store.

Does not score new data, alter original journals, use labels, train or calibrate.
"""
import argparse,hashlib,json,shutil,time
from pathlib import Path
import torch
from src.phase6.readiness import ROOT,load,sha
from src.phase6.temporal_protocol import require
from src.phase6.inference_registry import LocalModelRegistry
from src.phase6.local_inference import LocalInference
from src.phase6.run_continuous_inference import BASE,pinned_configuration
from src.phase6.training_data import dump_json

def run(org):
    config,prereg=pinned_configuration();require(org in config['organizations'],'Unknown organization')
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    component=load(BASE/'v1'/org/'summary.json');expected=component['restarted'];source=component['source']
    require(component['status']=='PASS_LOCAL_INFERENCE_AND_EXACT_RECOVERY_COMPONENT','Replay not finished')
    original=ROOT/expected['private_store'];original_hash=sha(original)
    output=BASE/'cold_start_v1'/org;require(not output.exists(),'Cold-start audit already exists')
    private=output/'private';private.mkdir(parents=True);copy=private/'inference.sqlite';shutil.copyfile(original,copy)
    require(sha(copy)==original_hash,'Private copy differs')
    started=time.perf_counter();registry=LocalModelRegistry(ROOT,org,prereg['registry'])
    service=LocalInference(copy,org,source['variant_id'],registry,config,source_identity=source)
    try:
        require(service.input_offset==source['events'],'Cold source cursor differs')
        require(service.decision_digest()==expected['decision_digest'],'Cold decision log differs')
        require(hashlib.sha256(service.runtime.graph.checkpoint_bytes()).hexdigest()==expected['final_graph_checkpoint_sha256'],'Cold graph differs')
        require(registry.current.fingerprint==expected['bundle_fingerprint'],'Cold model/threshold identity differs')
        require(service.last_time.isoformat()==expected['final_ten_minutes']['last_flush'],'Cold clock differs')
        result=dict(status='PASS_INDEPENDENT_PROCESS_COLD_START',organization=org,input_offset=service.input_offset,
            final_clock=service.last_time.isoformat(),decision_digest=service.decision_digest(),
            final_graph_checkpoint_sha256=expected['final_graph_checkpoint_sha256'],bundle_fingerprint=registry.current.fingerprint,
            startup_and_verify_seconds=time.perf_counter()-started,new_observations_scored=0,
            scope='Fresh Python process reloads original model and threshold and restores a private copy of completed durable state. Mid-hour uncheckpointed journal recovery is separately verified by the independent restart replay.',
            original_store_sha256=original_hash,source_module_sha256=sha(Path(__file__)),test_files_opened=0)
    finally:service.close()
    require(sha(original)==original_hash,'Original journal changed during cold audit')
    dump_json(output/'summary.json',result)
    dump_json(output/'artifact_sha256.json',{p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()})
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--organization',required=True);run(parser.parse_args().organization)
