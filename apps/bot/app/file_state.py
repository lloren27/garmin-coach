"""Serialize local state mutations across threads/processes and replace atomically."""
from contextlib import contextmanager
from functools import wraps
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading

_lock = threading.RLock()
_local = threading.local()


@contextmanager
def state_lock(directory):
    with _lock:
        if getattr(_local, 'held', False):
            yield
            return
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / '.state.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            _local.held = True
            try:
                yield
            finally:
                _local.held = False
                fcntl.flock(handle, fcntl.LOCK_UN)


def serialized_file_state(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        from . import store
        if store.DATABASE_URL:
            return fn(*args, **kwargs)
        with state_lock(store.DATA_DIR):
            return fn(*args, **kwargs)
    return call


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
            name = handle.name
            json.dump(data, handle, ensure_ascii=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
