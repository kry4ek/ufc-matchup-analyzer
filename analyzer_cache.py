"""Bounded local computation artifacts; keys describe contents, not timestamps."""
from __future__ import annotations
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid
from analyzer_history import fingerprint
from analyzer_support import atomic_json, digest

SCHEMA = 1
MAX_BYTES = 1024 ** 3

class ComputeCache:
    def __init__(self, root, context, enabled=True, limit=MAX_BYTES):
        self.directory = Path(root) / '.runtime/compute_cache'
        self.context = context
        self.enabled = enabled
        self.limit = limit
        self.hits = []
        self.timings = {}
        with contextlib.suppress(OSError): self.prune()

    def key(self, kind, inputs):
        return fingerprint(dict(schema=SCHEMA, kind=kind, context=self.context, inputs=inputs,
                                root_location=str(self.directory.parent.parent.resolve())))

    def load(self, kind, inputs):
        if not self.enabled: return None
        key = self.key(kind, inputs)
        path = self.directory / (key + '.bin')
        try:
            info = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
            if info.get('schema') != SCHEMA or info.get('key') != key or info.get('kind') != kind:
                return None
            if path.stat().st_size != info['size'] or info['size'] > self.limit or digest(path) != info['sha256']:
                return None
            # These are local computation artifacts, never accepted from datasets/downloads.
            from joblib.externals import cloudpickle
            result = cloudpickle.loads(path.read_bytes())
            os.utime(path, None)
            self.hits.append(kind)
            return result
        except Exception:
            with contextlib.suppress(OSError): path.unlink()
            with contextlib.suppress(OSError): path.with_suffix('.json').unlink()
            return None

    def save(self, kind, inputs, value):
        temporary = None
        try:
            from joblib.externals import cloudpickle
            raw = cloudpickle.dumps(value)
            if len(raw) > self.limit: return
            self.directory.mkdir(parents=True, exist_ok=True)
            self.prune(reserve=len(raw))
            if shutil.disk_usage(self.directory).free < len(raw) + 64 * 1024**2: return
            key = self.key(kind, inputs)
            path = self.directory / (key + '.bin')
            temporary = path.with_name(key + '.' + uuid.uuid4().hex + '.tmp')
            temporary.write_bytes(raw)
            os.replace(temporary, path)
            atomic_json(path.with_suffix('.json'), dict(schema=SCHEMA, key=key, kind=kind,
                sha256=hashlib.sha256(raw).hexdigest(), size=len(raw)))
            self.prune()
        except Exception:
            # Calculation remains successful when optional cache storage is unavailable.
            pass
        finally:
            if temporary:
                with contextlib.suppress(OSError): temporary.unlink(missing_ok=True)

    def get(self, kind, inputs, compute):
        start = time.monotonic()
        result = self.load(kind, inputs)
        if result is not None:
            from analyzer_protocol import progress
            progress('cache', 'Using compatible ' + kind.replace('_', ' '))
        else:
            result = compute()
            self.save(kind, inputs, result)
        self.timings[kind] = self.timings.get(kind, 0) + time.monotonic() - start
        return result

    def wrap(self, module, name, inputs=None):
        original = getattr(module, name)
        def cached(*args, **kwargs):
            return self.get(name, inputs or {}, lambda: original(*args, **kwargs))
        setattr(module, name, cached)

    def prune(self, reserve=0):
        for path in self.directory.glob('*.tmp'): path.unlink(missing_ok=True)
        for path in self.directory.glob('*.json'):
            if not path.with_suffix('.bin').exists(): path.unlink(missing_ok=True)
        files = sorted(self.directory.glob('*.bin'), key=lambda p:p.stat().st_mtime_ns, reverse=True)
        total = reserve
        for path in files:
            total += path.stat().st_size
            if total > self.limit:
                total -= path.stat().st_size
                path.unlink(missing_ok=True)
                path.with_suffix('.json').unlink(missing_ok=True)

def cache_size(root):
    return sum(p.stat().st_size for p in (Path(root)/'.runtime/compute_cache').glob('*') if p.is_file())

def clear_cache(root):
    from analyzer_runtime import operation_lock
    with operation_lock(root, 'clear_cache'):
        directory = Path(root).resolve()/'.runtime/compute_cache'
        if not directory.resolve().is_relative_to(Path(root).resolve()): raise ValueError('Cache directory must be local to this app.')
        for path in directory.glob('*'):
            if path.is_file() and not path.is_symlink(): path.unlink()
