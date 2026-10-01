"""Prepare deterministic local review archives. Public upload is a separate gate."""
from pathlib import Path
import argparse, hashlib, json, sys, zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import VERSION,atomic_json,digest,manifest

PUBLIC=['ufc_matchup_analyzer.py','analyzer_support.py','analyzer_maintenance.py','analyzer_runtime.py','analyzer_catalog.py','analyzer_results.py','analyzer_controller.py','analyzer_worker.py','analyzer_gui.py','analyzer_bootstrap.py','QUICK_START.txt','setup.py','setup.ps1','setup.bat','run.bat','requirements.lock','.gitignore','.gitattributes','README.md','LICENSE','DATA_NOTICE.md','THIRD_PARTY.md','CONTRIBUTING.md','RELEASE_VERIFICATION.md','source_manifest.json','dataset_manifest.json','release_checks.json','.github/workflows/ci.yml']
PUBLIC += ['runtime_inputs.json']
PUBLIC += ['analyzer_history.py','analyzer_protocol.py','analyzer_reporting.py','analyzer_widgets.py','analyzer_engine_runner.py']

def archive(path,items,prefix='',base=ROOT):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for rel in sorted(items):
            info=zipfile.ZipInfo(prefix+rel,date_time=(2026,9,30,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            with (base/rel).open('rb') as source,z.open(info,'w') as target:
                import shutil
                shutil.copyfileobj(source,target)

def refresh_export_hashes():
    source=json.loads((ROOT/'source_manifest.json').read_text())
    for item in source['files']:item['exported_sha256']=digest(ROOT/item['path'])
    atomic_json(ROOT/'source_manifest.json',source)

def public_files():
    source=json.loads((ROOT/'source_manifest.json').read_text())
    files=PUBLIC+source['allowlist']+['verification_evidence.json']
    for directory,pattern in [('docs','*.md'),('docs/images','*.png'),('tests','*.py'),('tests','*.ps1'),('tools','*.py'),('native','*.c')]:files+=[x.relative_to(ROOT).as_posix() for x in (ROOT/directory).glob(pattern)]
    files=sorted(set(files));missing=[x for x in files if not (ROOT/x).is_file()]
    if missing:raise ValueError('Missing public files: '+', '.join(missing))
    return files

def gate(root=ROOT):
    data=json.loads((root/'dataset_manifest.json').read_text());checks=json.loads((root/'release_checks.json').read_text())
    failed=[x['name'] for x in checks['checks'] if x.get('required',True) and x.get('phase')!='after_publish' and x['status']!='PASS']
    if data.get('redistribution_status')!='cleared':failed.append('dataset redistribution review')
    if not data.get('release_repository'):failed.append('publication repository / pinned data URL')
    if failed:raise ValueError('PUBLICATION BLOCKED: '+', '.join(failed))

def main():
    p=argparse.ArgumentParser();p.add_argument('--out-dir',type=Path,default=ROOT.parent/'release-assets');p.add_argument('--portable-folder',type=Path);p.add_argument('--repository',help='owner/ufc-matchup-analyzer; configure only when publication identity is known');p.add_argument('--check-publication',action='store_true');a=p.parse_args()
    if a.repository:
        import re
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/ufc-matchup-analyzer',a.repository):raise ValueError('Expected owner/ufc-matchup-analyzer')
        spec=manifest();spec['release_repository']=a.repository;atomic_json(ROOT/'dataset_manifest.json',spec)
    if a.check_publication:gate();print('Publication gate PASS');return
    refresh_export_hashes();files=public_files()
    data=[x['path'] for x in manifest()['files']]
    for item in manifest()['files']:
        if digest(ROOT/item['path'])!=item['sha256']:raise ValueError('Release datasets differ from original snapshot: '+item['path'])
    a.out_dir.mkdir(parents=True,exist_ok=True)
    archives=[(f'ufc-matchup-analyzer-source-v{VERSION}.zip',files,'ufc-matchup-analyzer/',ROOT),(f'ufc-matchup-analyzer-datasets-v{VERSION}.zip',data,'',ROOT)]
    if a.portable_folder:
        spec=json.loads((a.portable_folder/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
        if spec['version']!=VERSION:raise ValueError('Portable app version mismatch')
        for item in spec['files']:
            path=a.portable_folder/item['path']
            if digest(path)!=item['sha256']:raise ValueError('Portable file checksum mismatch: '+item['path'])
        portable=[x['path'] for x in spec['files']]+['PACKAGE_MANIFEST.json']
        archives.insert(0,(f'ufc-matchup-analyzer-v{VERSION}-windows.zip',portable,'UFC Matchup Analyzer/',a.portable_folder))
    entries=[]
    for name,items,prefix,base in archives:
        path=a.out_dir/name;archive(path,items,prefix,base);entries.append(dict(file=name,size_bytes=path.stat().st_size,sha256=digest(path),members=len(items)));print(name+f': {path.stat().st_size/1048576:.2f} MiB')
    atomic_json(a.out_dir/'archive_manifest.json',dict(version=VERSION,status='local_review_candidate',archives=entries))
    (a.out_dir/'SHA256SUMS.txt').write_text('\n'.join(x['sha256']+'  '+x['file'] for x in entries)+'\n',encoding='utf-8')
    atomic_json(ROOT/'.runtime/public_file_inventory.json',dict(files=files))

if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as exc:print(str(exc),file=sys.stderr);raise SystemExit(1)
