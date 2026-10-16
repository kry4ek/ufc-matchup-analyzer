"""Checked v0.4 maintenance patches over the reproducible v0.3 export."""
from pathlib import Path
import hashlib
import json

def apply_patch(rel, text, patches=None):
    patches=patches if patches is not None else json.loads(Path(__file__).with_name('engine_patches.json').read_text(encoding='utf-8'))
    patch=patches.get(rel)
    if not patch:return text
    digest=lambda value:hashlib.sha256(value.encode('utf-8')).hexdigest()
    if rel=='mens_ufc_model/src/features/mens_features.py' and 'Parsed CSV statistics already contain numeric scalars' in text:
        start=text.index('def _num(value: Any, default: float = 0.0) -> float:')
        end=text.index('\n\ndef add_opponent_stats',start)
        optimized=text[start:end]
        original='''def _num(value: Any, default: float = 0.0) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return default if pd.isna(parsed) else float(parsed)'''
        if optimized.endswith('\n'):original+='\n'
        normalized=text[:start]+original+text[end:]
        if digest(normalized)!=patch['base_sha256']:raise ValueError('Numeric optimization changed unrelated maintenance context')
        applied=apply_patch(rel,normalized,patches)
        if applied.count(original)!=1:raise ValueError('Numeric maintenance composition is ambiguous')
        return applied.replace(original,optimized,1)
    if digest(text)==patch['result_sha256']:return text
    if digest(text)!=patch['base_sha256']:raise ValueError('Maintenance patch baseline changed: '+rel)
    lines=text.splitlines(keepends=True)
    for edit in reversed(patch['edits']):
        start,end=edit['start'],edit['end']
        if ''.join(lines[start:end])!=edit['old']:raise ValueError('Maintenance patch context changed: '+rel)
        lines[start:end]=edit['new'].splitlines(keepends=True)
    result=''.join(lines)
    if digest(result)!=patch['result_sha256']:raise ValueError('Maintenance patch output differs: '+rel)
    return result
