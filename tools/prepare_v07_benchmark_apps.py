"""Create isolated identical-policy apps for the numeric optimization benchmark."""
import argparse
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest

def main():
    p=argparse.ArgumentParser();p.add_argument('--app',type=Path,required=True);p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    source=a.app.resolve();manifest=json.loads((source/'source_manifest.json').read_text())
    datasets=json.loads((source/'dataset_manifest.json').read_text())
    paths=manifest['allowlist']+[e['path'] for e in datasets['files']]
    paths += [p.name for p in source.glob('analyzer*.py')]+['ufc_matchup_analyzer.py','source_manifest.json','dataset_manifest.json','requirements.lock']
    if shutil.disk_usage(a.out.parent).free<1024**3:raise ValueError('At least 1 GiB free required')
    relative='mens_ufc_model/src/features/mens_features.py'
    for name in ('reference','candidate'):
        out=a.out/name
        if out.exists():raise ValueError('Benchmark directory already exists: '+str(out))
        for rel in sorted(set(paths)):
            target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/rel,target)
        replacement=(a.parent/'work/v07-performance-baseline'/relative if name=='reference' else a.parent/relative)
        text=(source/relative).read_text(encoding='utf-8')
        parent_text=replacement.read_text(encoding='utf-8')
        start=parent_text.index('def _num(value: Any, default: float = 0.0) -> float:')
        end=parent_text.index('\n\ndef add_opponent_stats',start)
        original_start=text.index('def _num(value: Any, default: float = 0.0) -> float:')
        original_end=text.index('\n\ndef add_opponent_stats',original_start)
        (out/relative).write_text(text[:original_start]+parent_text[start:end]+text[original_end:],encoding='utf-8',newline='\n')
        copied=json.loads((out/'source_manifest.json').read_text())
        for row in copied['files']:
            if row['path']==relative:row.update(source_sha256=digest(replacement),exported_sha256=digest(out/relative))
        atomic_json(out/'source_manifest.json',copied)
        atomic_json(out/'.runtime/ui_preferences.json',dict(history_enabled=False))
    print('Prepared identical-model, isolated-cache benchmark apps')

if __name__=='__main__':main()
