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

def engine_policy(root,sex):
    default='v3_bayes_smoothed' if sex=='men' else 'v1_current_ensemble'
    try:
        value=json.loads((Path(root)/'source_manifest.json').read_text()).get('model_policies',{}).get(sex,default)
    except (OSError,ValueError):return default
    allowed=('v3_bayes_smoothed',) if sex=='men' else ('v1_current_ensemble','v2_chronological_calibrated_ensemble')
    if value not in allowed:raise ValueError('Unknown installed model policy')
    return value

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
    validation=root/'docs/model_validation.json'
    return dict(datasets={c['path']: c['sha256'] for c in checks if c['status'] == 'PASS'},
                validation_artifact_sha256=digest(validation) if validation.is_file() else None,
                code=code, dependencies=versions, python=sys.version, engine=engine_policy(root,sex), report_version=VERSION)

def history_enabled(root):
    try:
        return json.loads((Path(root) / '.runtime/ui_preferences.json').read_text()).get('history_enabled', True)
    except (OSError, ValueError):
        return True

class History:
    def __init__(self, root):
        self.root = Path(root)
        self.directory = self.root / '.runtime/history'

    def load(self, identifier):
        if not isinstance(identifier,str) or len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):raise ValueError('Invalid history identifier')
        path=self.directory/(identifier+'.json')
        if path.stat().st_size>8*1024**2:raise ValueError('Oversized saved report')
        value=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or value.get('schema')!=SCHEMA or value.get('id')!=identifier or value.get('integrity')!=fingerprint({k:v for k,v in value.items() if k!='integrity'}):raise ValueError('Saved report integrity mismatch')
        if not all(isinstance(value.get(k),dict) for k in ('request','context','payload')):raise ValueError('Invalid history structure')
        if value['request'].get('sex') not in ('men','women') or value['request'].get('operation') not in ('predict','compare'):raise ValueError('Invalid saved request')
        if any(not isinstance(value['payload'].get(k),str) for k in ('fighter_a','fighter_b','fight_date')):raise ValueError('Invalid saved matchup')
        if not all(isinstance(value.get(k),str) for k in ('created_at','cache_key')):raise ValueError('Invalid history metadata')
        from analyzer_bout_context import validate_context
        validate_context(value['payload'])
        return value

    def summaries(self):
        """Rebuildable content-checked metadata, with full payloads read on open."""
        index_path=self.root/'.runtime/history_index.json'
        try:
            cache=json.loads(index_path.read_text(encoding='utf-8'))
            if not isinstance(cache,dict) or not isinstance(cache.get('files'),dict) or cache.get('integrity')!=fingerprint(cache['files']):cache={}
        except (OSError,ValueError,TypeError):cache={}
        old=cache.get('files',{});current={};result=[]
        for path in self.directory.glob('*.json'):
            try:
                if path.stat().st_size>8*1024**2:continue
                sha=digest(path);saved=old.get(path.name,{})
                if not isinstance(saved,dict):saved={}
                if saved.get('sha256')==sha:summary=saved['summary']
                else:
                    entry=self.load(path.stem);p=entry['payload']
                    summary=dict(id=entry['id'],created_at=entry['created_at'],request=entry['request'],
                        context_fingerprint=fingerprint(entry['context']),cache_key=entry['cache_key'],
                        payload={k:p.get(k) for k in ('fighter_a','fighter_b','fight_date','division','result_state')})
                current[path.name]=dict(sha256=sha,summary=summary);result.append(summary)
            except (OSError,ValueError,TypeError,KeyError):continue
        temporary=index_path.with_name('history_index.'+uuid.uuid4().hex+'.json')
        try:
            atomic_json(temporary,dict(schema=1,files=current,integrity=fingerprint(current)))
            temporary.replace(index_path)
        except OSError:pass
        finally:
            try:temporary.unlink(missing_ok=True)
            except OSError:pass
        return sorted(result,key=lambda v:v['created_at'],reverse=True)

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
        for summary in self.summaries():
            if summary['cache_key']==cache_key:
                try:return self.load(summary['id'])
                except (OSError,ValueError,TypeError,KeyError):continue
        return None

    def save(self, request, context, payload, preserve_id=None):
        if payload.get('result_state') not in ('complete', 'comparison'):
            return None
        existing = self.lookup(request, context)
        entry = dict(schema=SCHEMA, id=uuid.uuid4().hex, created_at=payload['generated_at'],
                     request=request, context=context, cache_key=fingerprint(dict(request=request, context=context)), payload=payload)
        entry['integrity'] = fingerprint(entry)
        raw_bytes=len((json.dumps(entry,indent=2,allow_nan=False)+'\n').encode('utf-8'))
        original=self.directory/(str(preserve_id)+'.json') if preserve_id else None
        if raw_bytes>8*1024**2 or raw_bytes>MAX_BYTES:raise ValueError('Result is too large for bounded history; export the displayed result instead.')
        if original and original.exists() and raw_bytes+original.stat().st_size>MAX_BYTES:
            raise ValueError('Original and refreshed result exceed history capacity; comparison remains available without saving.')
        atomic_json(self.directory / (entry['id'] + '.json'), entry)
        if existing and existing['id']!=preserve_id:
            self.delete(existing['id'])
        self.prune(preserve_ids=(preserve_id,entry['id']))
        return entry['id']

    def prune(self,preserve_ids=()):
        files = sorted(self.directory.glob('*.json'), key=lambda p: (p.stem in preserve_ids,p.stat().st_mtime_ns, p.name), reverse=True)
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
