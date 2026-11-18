"""Generated all-alert fixture solely to exercise receipt recovery at every org."""
import sys
from dataclasses import replace
from pathlib import Path
import wal_fixture_worker_v4 as base
from src.phase6.heldout_contract_v2 import Scope,canonical,digest
from src.phase6.local_graphsage import state_digest
original=base.make_world

def make_world(root):
    generated,old,bundles=original(root);seals=[]
    for seal in old.catalog.seals:
        b=bundles[seal.organization,seal.detector]
        if seal.detector=='graphsage':
            b.model.bias.fill_(1.)
            b.identity=dict(b.identity,model_sha256=digest([seal.organization,seal.detector,'all-positive-RAM-fixture']))
            b.fingerprint=digest(b.identity)
        seals.append(replace(seal,identity_json=canonical(b.identity),state_digest=state_digest(b.model.state_dict())))
    catalog=replace(old.catalog,seals=tuple(seals))
    return generated,Scope.synthetic(old.root,catalog),bundles

if __name__=='__main__':
    base.make_world=make_world
    base.main()
