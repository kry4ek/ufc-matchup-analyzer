"""Test an isolated source-only copy containing exactly the curated public files."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.package_release import public_files,refresh_export_hashes
from analyzer_support import atomic_json,digest

def main():
    out=ROOT/'work/v0.8/source-check'
    if out.exists():raise ValueError('Source check folder already exists; inspect completed evidence before rerunning')
    refresh_export_hashes();files=public_files()
    for rel in files:
        target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,target)
    env=os.environ.copy();env['ANALYZER_SOURCE_ONLY']='1';env['PYTHONUTF8']='1'
    command=[sys.executable,'-X','utf8','-u','-m','unittest','discover','-s',str(out/'tests'),'-v']
    with (ROOT/'work/v0.8/source-tests.log').open('w',encoding='utf-8') as stream:subprocess.run(command,env=env,cwd=out,stdout=stream,stderr=subprocess.STDOUT,check=True)
    atomic_json(ROOT/'work/v0.8/source-code-tested.json',dict(status='PASS',files={rel:digest(out/rel) for rel in files if rel.endswith(('.py','.c','.cjs'))}))
    print('Curated source-only regression PASS',flush=True)
if __name__=='__main__':main()
