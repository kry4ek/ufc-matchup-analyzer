"""Isolated performance snapshot; user history/preferences are never cleared."""
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,manifest
from tools.package_release import public_files

def main():
    target=ROOT/'work/v0.8/candidate'
    if target.exists():raise ValueError('Candidate benchmark snapshot exists; choose explicit follow-up rather than replacing it')
    for rel in sorted(set(public_files()+[v['path'] for v in manifest()['files']])):
        path=target/rel;path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,path)
    atomic_json(target/'.runtime/ui_preferences.json',dict(history_enabled=False))
    print('Isolated candidate snapshot prepared',flush=True)
if __name__=='__main__':main()
