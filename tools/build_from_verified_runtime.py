"""Build a new app using an unchanged, manifest-verified portable runtime/launcher."""
import argparse
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import VERSION,atomic_json,digest,manifest,safe_path
from tools.package_release import public_files,refresh_export_hashes

def main():
    p=argparse.ArgumentParser();p.add_argument('--from-package',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    source=args.from_package.resolve();out=args.out.resolve()
    if out.exists():raise ValueError('Choose a new output directory.')
    package=json.loads((source/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    build=json.loads((source/'BUILD_INFO.json').read_text(encoding='utf-8'))
    if build['input_manifest_sha256']!=digest(ROOT/'runtime_inputs.json'):raise ValueError('Runtime inputs changed; use the full pinned build.')
    if build['launcher']['source_sha256']!=digest(ROOT/'native/launcher.c'):raise ValueError('Launcher source changed; compile it again.')
    if (source/'app/requirements.lock').read_bytes()!=(ROOT/'requirements.lock').read_bytes():raise ValueError('Dependencies changed; use the full build.')
    selected=[e for e in package['files'] if e['path'].startswith('runtime/') or e['path']=='UFC Matchup Analyzer.exe']
    if not selected or not any(e['path']=='runtime/python.exe' for e in selected):raise ValueError('No complete runtime was declared.')
    for e in selected:
        path=safe_path(source,e['path'])
        if digest(path)!=e['sha256']:raise ValueError('Runtime or launcher drift: '+e['path'])
    refresh_export_hashes();out.mkdir(parents=True)
    for e in selected:
        target=safe_path(out,e['path']);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/e['path'],target)
    omit={'setup.py','setup.ps1','setup.bat','run.bat','.gitignore','.gitattributes','.github/workflows/ci.yml','CONTRIBUTING.md'}
    for rel in public_files():
        if rel in omit or rel.startswith(('tests/','tools/','native/')):continue
        target=safe_path(out/'app',rel);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,target)
    for e in manifest()['files']:
        if digest(ROOT/e['path'])!=e['sha256']:raise ValueError('Dataset snapshot changed: '+e['path'])
        target=safe_path(out/'app',e['path']);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/e['path'],target)
    shutil.copy2(ROOT/'QUICK_START.txt',out/'QUICK_START.txt')
    build['runtime_reuse']=dict(source_package_version=package['version'],source_package_manifest_sha256=digest(source/'PACKAGE_MANIFEST.json'),verified_runtime_and_launcher_files=len(selected),unchanged_inputs=True)
    atomic_json(out/'BUILD_INFO.json',build)
    inventory=[dict(path=p.relative_to(out).as_posix(),size_bytes=p.stat().st_size,sha256=digest(p)) for p in sorted(out.rglob('*')) if p.is_file()]
    atomic_json(out/'PACKAGE_MANIFEST.json',dict(version=VERSION,status='local_review_candidate',files=inventory))
    print(json.dumps(dict(version=VERSION,files=len(inventory)+1,size_bytes=sum(e['size_bytes'] for e in inventory)),indent=2))

if __name__=='__main__':main()
