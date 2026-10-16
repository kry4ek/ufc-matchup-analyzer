"""Synchronize final documentation into this task's new package and re-inventory."""
import argparse
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest,manifest,VERSION
from tools.package_release import public_files,refresh_export_hashes

def main():
    p=argparse.ArgumentParser();p.add_argument('--package',type=Path,required=True);a=p.parse_args()
    package=a.package.resolve()
    if not package.is_relative_to((ROOT/'dist').resolve()) or package.name!='UFC Matchup Analyzer v0.8.0':raise ValueError('Only this task new v0.8 package can be synchronized')
    before=json.loads((package/'PACKAGE_MANIFEST.json').read_text())
    if before['version']!=VERSION:raise ValueError('Wrong package version')
    refresh_export_hashes();omit={'setup.py','setup.ps1','setup.bat','run.bat','.gitignore','.gitattributes','.github/workflows/ci.yml','CONTRIBUTING.md'}
    items={e['path'] for e in before['files'] if e['path'].startswith('runtime/') or e['path'] in ('UFC Matchup Analyzer.exe','BUILD_INFO.json','QUICK_START.txt')}
    for rel in public_files():
        if rel in omit or rel.startswith(('tests/','tools/','native/')):continue
        target=package/'app'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,target);items.add('app/'+rel)
    for row in manifest()['files']:
        if digest(package/'app'/row['path'])!=row['sha256']:raise ValueError('Packaged data drift')
        items.add('app/'+row['path'])
    shutil.copy2(ROOT/'QUICK_START.txt',package/'QUICK_START.txt')
    records=[dict(path=rel,size_bytes=(package/rel).stat().st_size,sha256=digest(package/rel)) for rel in sorted(items)]
    atomic_json(package/'PACKAGE_MANIFEST.json',dict(version=VERSION,status='local_review_candidate',files=records))
    print('Final package source/docs inventory synchronized; runtime state excluded',flush=True)
if __name__=='__main__':main()
