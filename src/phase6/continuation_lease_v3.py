"""Read-only predecessor byte lease; no process control and no file writes."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import os
from src.phase6.temporal_protocol import require
from src.phase6.continuation_contract_v3 import CapturePermit,ContinuationScope

_held=ContextVar('continuation_predecessor_read_leases',default=frozenset())

@contextmanager
def predecessor_lease(authority,catalog):
    if type(authority) is CapturePermit:
        authority.validate(catalog);source=authority.source
    else:
        require(type(authority) is ContinuationScope,'Verified predecessor lease authority required')
        authority.assert_ready()
        if authority.certificate_path is None:
            yield;return
        source=Path(authority.certificate()['body']['source_root']).resolve()
    lock=source.parent/'execution.lock';key=str(lock.resolve())
    if key in _held.get():
        yield;return
    require(lock.is_file() and lock.stat().st_size>=1,'Original execution lease is missing; quiescence cannot be locked')
    handle=lock.open('rb');acquired=False;token=None
    try:
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as e:raise ValueError('Predecessor execution is still owned; capture/continuation refused') from e
        acquired=True;token=_held.set(_held.get()|{key});yield
    finally:
        if token is not None:_held.reset(token)
        if acquired:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_UN)
        handle.close()
