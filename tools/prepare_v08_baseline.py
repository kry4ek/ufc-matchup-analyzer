"""Preserve the actual working tree and data before v0.8 changes."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analyzer_support import atomic_json, digest, manifest
from tools.package_release import public_files

def main():
    destination = ROOT/'work/v0.8/reference'
    if destination.exists():
        raise SystemExit('Reference already exists; refusing to replace it')
    paths = sorted(set(public_files()+[v['path'] for v in manifest()['files']]))
    inventory = []
    for rel in paths:
        source = ROOT/rel; target = destination/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        inventory.append(dict(path=rel, sha256=digest(target), bytes=target.stat().st_size))
    atomic_json(destination/'.runtime/ui_preferences.json', dict(history_enabled=False))
    atomic_json(ROOT/'work/v0.8/baseline-inventory.json', dict(files=inventory,
        git_status=subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True),
        runtime=sys.version, baseline='Actual v0.7 working tree including UI polish'))
    checkpoint=ROOT/'work/v0.8/RESUME-CHECKPOINT.md'
    checkpoint.write_text('# v0.8 checkpoint\n\nBaseline preserved in reference/. Runtime is dist/UFC Matchup Analyzer UI polish/runtime/python.exe.\n'
        'Scope: all five app changes, no prospective work, clean OS/real alternate DPI deferred.\n'
        'Next: baseline suite/profile, then contracts and implementation.\n',encoding='utf-8')
    print('Preserved',len(inventory),'files',flush=True)
if __name__ == '__main__': main()
