"""Fail-closed execution scope for the additive held-out adapter.

Synthetic fixture capability is restricted to an isolated directory outside the
project. Production approval is a separate, hash-bound review artifact; this
module neither creates that approval nor interprets command-line flags as one.
This is an application guard, not an operating-system security boundary.
"""
from dataclasses import dataclass
import json
from pathlib import Path

from src.phase6.fpr_calibration import canonical_digest
from src.phase6.readiness import REPLAY, load, sha
from src.phase6.temporal_protocol import require

PROJECT = Path(__file__).resolve().parents[2]
CONFIG = 'configs/phase6/heldout_test_adapter_v1.json'
SOURCES = ('src/phase6/heldout_scope_v1.py',
           'src/phase6/heldout_local_inference_v1.py',
           'src/phase6/heldout_replay_v1.py',
           'src/phase6/heldout_evaluation_v1.py',
           'src/phase6/heldout_tabular_bundle_v1.py')


@dataclass(frozen=True)
class TestScope:
    __test__ = False
    root: Path
    output_root: Path
    synthetic_only: bool = False

    @classmethod
    def synthetic(cls, directory):
        root = Path(directory).resolve()
        require(not root.is_relative_to(PROJECT) and not PROJECT.is_relative_to(root),
                'Synthetic fixtures must be isolated outside the research project')
        return cls(root, root/'outputs', True)

    @classmethod
    def production(cls, output_root):
        scope = cls(PROJECT, Path(output_root).resolve(), False)
        require(scope.output_root.is_relative_to(PROJECT/'reports/phase6/heldout_test'),
                'Production outputs need a new heldout_test run directory')
        return scope

    @property
    def inference_config_sha256(self):
        # The canonical object digest is the accepted persistence identity;
        # the byte hash is checked separately, without editing the VAL config.
        return canonical_digest(load(PROJECT/'configs/phase6/continuous_inference_v1.json'))

    def approval_identity(self):
        cfg = load(PROJECT/CONFIG)
        return dict(adapter_version=cfg['version'], split='TEST',
                    configuration_sha256=sha(PROJECT/CONFIG),
                    source_sha256={p: sha(PROJECT/p) for p in SOURCES},
                    protocol_sha256=cfg['protocol_sha256'],
                    registry_sha256=sha(PROJECT/cfg['registry_path']))

    def assert_ready(self):
        require(self.root == self.root.resolve() and self.output_root == self.output_root.resolve(),
                'Scope paths must be canonical')
        if self.synthetic_only:
            require(not self.root.is_relative_to(PROJECT) and not PROJECT.is_relative_to(self.root),
                    'Fixture scope cannot address project data')
            require(self.output_root == self.root/'outputs', 'Invalid fixture output root')
            return
        require(self.root == PROJECT, 'Production project identity mismatch')
        require(self.output_root.is_relative_to(PROJECT/'reports/phase6/heldout_test'),
                'Invalid production output root')
        cfg = load(PROJECT/CONFIG)
        require(sha(PROJECT/'configs/phase6/split_protocol_v1.json') == cfg['protocol_sha256'],
                'Frozen scientific protocol changed')
        require(sha(PROJECT/cfg['inference_configuration_path']) == cfg['inference_configuration_sha256'],
                'Accepted inference configuration changed')
        for relative,digest in cfg['frozen_method_sha256'].items():
            require(sha(PROJECT/relative)==digest,'Frozen evaluation method changed: '+relative)
        path = PROJECT/cfg['production_approval_path']
        require(path.is_file(), 'TEST execution blocked: completed-adapter user review is pending')
        approval = load(path)
        require(approval.get('status') == 'USER_APPROVED_TEST_EXECUTION' and
                approval.get('identity') == self.approval_identity() and
                bool(approval.get('explicit_user_decision')),
                'Missing or stale explicit TEST execution approval')

    def check_output(self, path):
        require(Path(path).resolve().is_relative_to(self.output_root),
                'Output outside separately scoped run directory')

    def check_variant(self, variant, organization):
        require(isinstance(variant, str) and Path(variant).name == variant and
                variant.endswith('_TEST') and '/' not in variant and '\\' not in variant,
                'Only a TEST branch namespace is permitted')
        require(organization in ('Org1','Org2','Org3','Org4','Org5'), 'Unknown organization')

    def check_input(self, path, variant, organization, *, labels=False):
        """Explicit file allowlist; warm-up rows additionally bounded in loader."""
        self.check_variant(variant, organization)
        p = Path(path).resolve()
        require(p.is_relative_to(self.root), 'Input escaped scoped root')
        relative = p.relative_to(self.root).as_posix()
        require('_TRAIN' not in relative and '_VAL' not in relative, 'Other split forbidden')
        folder = self.root/REPLAY/variant
        permitted = {folder/'replay_manifest.json', folder/f'{organization}_observations.parquet'}
        if labels:
            permitted = {folder/f'{organization}_labels.parquet'}
        if p in {q.resolve() for q in permitted}:
            return p
        require(not labels, 'Labels outside exact offline-evaluation branch')
        ref_root = (self.root/REPLAY/'history_references').resolve()
        if p.is_relative_to(ref_root):
            require(p.parent.name in ('TEST_SEED1001','TEST_SEED1002','TEST_SEED1003') and
                    p.name == f'{organization}.json', 'Nonlocal history reference')
            return p
        # Exact source paths are authorized only by the separately pinned
        # history reference. Merely containing an organization name is unsafe.
        require(False, 'Input absent from TEST observation/history allowlist')

    def check_history_source(self, path, authorized_sources):
        p=Path(path).resolve()
        require(p.is_relative_to(self.root) and p in {Path(q).resolve() for q in authorized_sources},
                'Unreferenced warm-up source')
        relative=p.relative_to(self.root).as_posix()
        require('_TRAIN' not in relative and '_VAL' not in relative and p.suffix=='.parquet',
                'Split-specific or invalid history source')
        return p

    def verify_bundle(self, bundle, organization):
        from src.phase6.local_graphsage import state_digest
        registry=load(PROJECT/'reports/phase6/inference/preregistration_v1.json')['registry']
        entry=registry['models'][organization]
        require(bundle.identity['organization']==organization and
                bundle.identity['model_sha256']==entry['model_sha256'] and
                bundle.identity['threshold_sha256']==entry['threshold_sha256'] and
                bundle.identity['protocol_sha256']==registry['protocol_sha256'],
                'Held-out bundle differs from accepted original')
        require(sha(PROJECT/entry['model_path'])==entry['model_sha256'] and
                sha(PROJECT/entry['threshold_path'])==entry['threshold_sha256'],
                'Original model or threshold changed')
        require(state_digest(bundle.model.state_dict())==bundle.state_digest and
                bundle.threshold==load(PROJECT/entry['threshold_path'])['calibration']['threshold'] and
                bundle.protocol==load(PROJECT/'configs/phase6/split_protocol_v1.json') and
                bundle.sampler==load(PROJECT/'configs/phase6/neighbor_sampling_v1.json'),
                'In-memory model, threshold, protocol or sampling state changed')
        require(not bundle.model.training and all(not p.requires_grad for p in bundle.model.parameters()),
                'Held-out model must be frozen in evaluation mode')
