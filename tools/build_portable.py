"""Build the Windows folder distribution from pinned, verified build inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import VERSION,atomic_json,digest,manifest,safe_path
from tools.package_release import public_files,refresh_export_hashes

PYTHON_SHA256='d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15'

def unpack_checked(path,destination,trim_tests=False):
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            if trim_tests and any(part in ('tests','test','benchmarks','examples','__pycache__') for part in Path(member.filename).parts):continue
            target=safe_path(destination,member.filename)
            if member.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(member) as source,target.open('wb') as output:shutil.copyfileobj(source,output)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--python-zip',type=Path,required=True);p.add_argument('--tk-root',type=Path,required=True)
    p.add_argument('--wheels',type=Path,required=True);p.add_argument('--zig',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    input_spec=json.loads((ROOT/'runtime_inputs.json').read_text(encoding='utf-8'))
    if digest(args.python_zip)!=PYTHON_SHA256:raise ValueError('Official Python archive checksum mismatch')
    if digest(args.zig)!=input_spec['zig_exe_sha256']:raise ValueError('Build compiler checksum mismatch')
    for item in input_spec['tk_files']:
        if digest(safe_path(args.tk_root,item['path']))!=item['sha256']:raise ValueError('Matching Tcl/Tk component checksum mismatch: '+item['path'])
    if args.out.exists():raise ValueError('Choose a new output directory; existing app folders are never overwritten')
    refresh_export_hashes()
    args.out.mkdir(parents=True);app=args.out/'app';app.mkdir();runtime=args.out/'runtime';runtime.mkdir()
    files=public_files()
    # The user-facing root has only the launcher and short instructions. Developer
    # tools remain in the source archive rather than bloating the app distribution.
    omit={'setup.py','setup.ps1','setup.bat','run.bat','.gitignore','.gitattributes','.github/workflows/ci.yml','CONTRIBUTING.md'}
    for rel in files:
        if rel in omit or rel.startswith(('tests/','tools/','native/')):continue
        target=app/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,target)
    for entry in manifest()['files']:
        source=ROOT/entry['path']
        if digest(source)!=entry['sha256']:raise ValueError('Dataset snapshot hash mismatch: '+entry['path'])
        target=app/entry['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    unpack_checked(args.python_zip,runtime)
    dlls=runtime/'DLLs';dlls.mkdir()
    if not (args.tk_root/'DLLs/_tkinter.pyd').exists():raise ValueError('Matching Python 3.14.7 _tkinter module is missing')
    for source in (args.tk_root/'DLLs').iterdir():
        if source.suffix.lower() in ('.dll','.pyd'):shutil.copy2(source,dlls/source.name)
    shutil.copytree(args.tk_root/'Lib/tkinter',runtime/'Lib/tkinter',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(args.tk_root/'tcl',runtime/'tcl',ignore=shutil.ignore_patterns('*.pyc','__pycache__','*.lib','*.sh','nmake','demos'))
    lock=[line.strip().split('==') for line in (ROOT/'requirements.lock').read_text().splitlines() if line.strip() and not line.startswith('#')]
    build_info={'input_manifest_sha256':digest(ROOT/'runtime_inputs.json'),'python':{'version':'3.14.7','sha256':digest(args.python_zip),'source':'https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip'},'wheels':[],'tk_files':[]}
    packages=runtime/'Lib/site-packages';packages.mkdir(parents=True)
    for name,version in lock:
        prefix=name.replace('-','_').lower()+'-'+version+'-'
        matches=[p for p in args.wheels.glob('*.whl') if p.name.lower().startswith(prefix)]
        if len(matches)!=1:raise ValueError('Expected exactly one wheel for '+name+'=='+version)
        wheel=matches[0]
        expected=next((x for x in input_spec['wheels'] if x['file']==wheel.name),None)
        if not expected or digest(wheel)!=expected['sha256']:raise ValueError('Wheel checksum mismatch: '+wheel.name)
        unpack_checked(wheel,packages,trim_tests=True)
        build_info['wheels'].append(dict(package=name,version=version,file=wheel.name,sha256=digest(wheel)))
    for path in runtime.rglob('*'):
        if path.is_file() and path.relative_to(runtime).parts[0] in ('tcl','DLLs'):
            build_info['tk_files'].append(dict(path=path.relative_to(runtime).as_posix(),sha256=digest(path)))
    # Explicit paths isolate this interpreter from registry/PATH/user packages.
    (runtime/'python314._pth').write_text('python314.zip\n.\nDLLs\nLib\nLib/site-packages\n../app\n../app/mens_ufc_model\n../app/womens_ufc_model\nimport site\n',encoding='utf-8',newline='\n')
    native=args.out/'UFC Matchup Analyzer.exe'
    env=os.environ.copy();env['ZIG_GLOBAL_CACHE_DIR']=str(ROOT/'.runtime/build-cache/global');env['ZIG_LOCAL_CACHE_DIR']=str(ROOT/'.runtime/build-cache/local')
    subprocess.run([str(args.zig.resolve()),'cc','-target','x86_64-windows-gnu','-Os','-s','-municode','-Wl,--subsystem,windows',str(ROOT/'native/launcher.c'),'-o',str(native.resolve()),'-luser32','-lkernel32'],check=True,env=env)
    shutil.copy2(ROOT/'QUICK_START.txt',args.out/'QUICK_START.txt')
    build_info['launcher']=dict(source_sha256=digest(ROOT/'native/launcher.c'),sha256=digest(native),compiler='Zig 0.15.2')
    atomic_json(args.out/'BUILD_INFO.json',build_info)
    inventory=[dict(path=p.relative_to(args.out).as_posix(),size_bytes=p.stat().st_size,sha256=digest(p)) for p in sorted(args.out.rglob('*')) if p.is_file()]
    atomic_json(args.out/'PACKAGE_MANIFEST.json',dict(version=VERSION,status='local_review_candidate',files=inventory))
    print(json.dumps(dict(folder=str(args.out),files=len(inventory)+1,size_bytes=sum(x['size_bytes'] for x in inventory)+(args.out/'PACKAGE_MANIFEST.json').stat().st_size),indent=2))

if __name__=='__main__':main()
