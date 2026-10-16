"""Create a marked disposable maintenance app without caches or user state."""
import argparse
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--export',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    root=a.out.resolve();source=a.source.resolve()
    if root.exists():raise ValueError('Choose a fresh disposable folder')
    out=root/'app';manifest=json.loads((a.export/'source_manifest.json').read_text())
    datasets=json.loads((source/'dataset_manifest.json').read_text())
    paths=manifest['allowlist']+[r['path'] for r in datasets['files']]
    paths += [p.name for p in source.glob('analyzer*.py')]+['ufc_matchup_analyzer.py','requirements.lock','dataset_manifest.json']
    for rel in sorted(set(paths)):
        chosen=a.export/rel if rel in manifest['allowlist'] else source/rel
        target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(chosen,target)
    atomic_json(out/'source_manifest.json',manifest)
    atomic_json(out/'.runtime/ui_preferences.json',dict(history_enabled=False))
    (root/'DISPOSABLE_V05_CHECK').write_text('Owned v0.7 maintenance fixture; never use installed app data.\n')
    for name in ('check_v05_corrections.py','check_v05_feature_rebuild.py'):
        target=out/'tools'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/'tools'/name,target)
    print('Prepared isolated marked maintenance app')

if __name__=='__main__':main()
