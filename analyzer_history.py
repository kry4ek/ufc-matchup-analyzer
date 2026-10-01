"""Bounded local JSON history and exact, content-based result reuse."""
from __future__ import annotations
import datetime as dt
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import uuid
from analyzer_support import atomic_json, digest, VERSION

SCHEMA = 1
MAX_ENTRIES = 50
MAX_BYTES = 50 * 1024 * 1024

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()

def calculation_context(root, sex, checks):
    root = Path(root)
    prefix = 'mens_ufc_model' if sex == 'men' else 'womens_ufc_model'
    code = {p.relative_to(root).as_posix(): digest(p) for p in sorted((root / prefix).rglob('*.py')) if '__pycache__' not in p.parts}
    for p in sorted(root.glob('analyzer*.py')) + [root / 'ufc_matchup_analyzer.py']:
        code[p.name] = digest(p)
    versions = {}
    for line in (root / 'requirements.lock').read_text().splitlines():
        if line.strip() and not line.startswith('#'):
            name = line.split('==')[0]
            versions[name] = importlib.metadata.version(name)
    return dict(datasets={c['path']: c['sha256'] for c in checks if c['status'] == 'PASS'},
                code=code, dependencies=versions, python=sys.version, engine='v3_bayes_smoothed' if sex == 'men' else 'v1_current_ensemble', report_version=VERSION)

def history_enabled(root):
    try:
        return json.loads((Path(root) / '.runtime/ui_preferences.json').read_text()).get('history_enabled', True)
    except (OSError, ValueError):
        return True

class History:
    def __init__(self, root):
        self.root = Path(root)
        self.directory = self.root / '.runtime/history'

    def entries(self):
        entries = []
        for p in self.directory.glob('*.json'):
            try:
                value = json.loads(p.read_text(encoding='utf-8'))
                if not isinstance(value, dict) or value.get('schema') != SCHEMA or not isinstance(value.get('payload'), dict):
                    continue
                if not isinstance(value.get('request'), dict) or not isinstance(value.get('context'), dict) or not isinstance(value.get('created_at'), str) or not isinstance(value.get('cache_key'), str):
                    continue
                if value['request'].get('sex') not in ('men', 'women') or value['request'].get('operation') not in ('predict', 'compare'):
                    continue
                if any(name not in value['payload'] for name in ('fighter_a', 'fighter_b', 'fight_date')):
                    continue
                if value.get('id') != p.stem or value.get('integrity') != fingerprint({k: v for k, v in value.items() if k != 'integrity'}):
                    continue
                entries.append(value)
            except (OSError, ValueError, TypeError):
                continue
        return sorted(entries, key=lambda x: x['created_at'], reverse=True)

    def lookup(self, request, context):
        cache_key = fingerprint(dict(request=request, context=context))
        return next((e for e in self.entries() if e['cache_key'] == cache_key), None)

    def save(self, request, context, payload):
        if payload.get('result_state') not in ('complete', 'comparison'):
            return None
        existing = self.lookup(request, context)
        entry = dict(schema=SCHEMA, id=uuid.uuid4().hex, created_at=payload['generated_at'],
                     request=request, context=context, cache_key=fingerprint(dict(request=request, context=context)), payload=payload)
        entry['integrity'] = fingerprint(entry)
        atomic_json(self.directory / (entry['id'] + '.json'), entry)
        if existing:
            self.delete(existing['id'])
        self.prune()
        return entry['id']

    def prune(self):
        files = sorted(self.directory.glob('*.json'), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
        total = 0
        for i, p in enumerate(files):
            size = p.stat().st_size
            if i >= MAX_ENTRIES or total + size > MAX_BYTES:
                p.unlink()
            else:
                total += size

    def delete(self, identifier):
        if len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
            raise ValueError('Invalid history identifier')
        (self.directory / (identifier + '.json')).unlink(missing_ok=True)

    def clear(self):
        for p in self.directory.glob('*.json'):
            p.unlink()

def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
