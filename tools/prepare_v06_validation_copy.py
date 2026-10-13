"""Create a data-equipped disposable app copy without user history or caches."""
import argparse
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,manifest

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    out=args.out.resolve()
    if out.exists():raise ValueError('Choose a new disposable output directory')
    files=[p.relative_to(ROOT).as_posix() for p in ROOT.glob('analyzer*.py')]+['ufc_matchup_analyzer.py','requirements.lock','dataset_manifest.json','source_manifest.json']
    files+=json.loads((ROOT/'source_manifest.json').read_text())['allowlist']
    files+=[e['path'] for e in manifest()['files']]
    for rel in files:
        target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,target)
    atomic_json(out/'.runtime/ui_preferences.json',dict(history_enabled=False))
    print('Prepared disposable data-equipped copy:',out)
if __name__=='__main__':main()
