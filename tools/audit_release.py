"""Audit retained source, dependency closure, private paths, secrets, and data."""
from pathlib import Path
import argparse, ast, json, re, subprocess, sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import data_health,dependency_health,digest
from tools.package_release import public_files

def main():
    p=argparse.ArgumentParser();p.add_argument('--source-only',action='store_true');a=p.parse_args();errors=[];parsed=0
    files=[x for x in ROOT.rglob('*.py') if not any(y in x.parts for y in ['.venv','.runtime','__pycache__','work','dist','release-assets'])]
    for file in files:
        text=file.read_text(encoding='utf-8-sig');parsed+=1
        try:ast.parse(text,filename=file.name)
        except SyntaxError as exc:errors.append(f'{file.relative_to(ROOT)}: {exc}')
        if re.search(r'[A-Z]:\\(?:Users\\[^\s"\']+|ufc_fight_predictor)',text):errors.append('Private source path: '+str(file.relative_to(ROOT)))
        if re.search(r'github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',text):errors.append('Possible secret: '+str(file.relative_to(ROOT)))
    source=json.loads((ROOT/'source_manifest.json').read_text())
    for item in source['files']:
        if digest(ROOT/item['path'])!=item['exported_sha256']:errors.append('Export hash drift: '+item['path'])
    public=public_files()
    for rel in public:
        path=ROOT/rel
        if path.suffix.lower() not in ('.py','.ps1','.bat','.md','.txt','.json','.c','.yml','.lock'):
            continue
        text=path.read_text(encoding='utf-8-sig')
        if re.search(r'[A-Z]:[\\/](?:Users[\\/][^\s"\']+|ufc_fight_predictor)',text):errors.append('Private public-file path: '+rel)
        if re.search(r'github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',text):errors.append('Possible public-file secret: '+rel)
    dependencies=dependency_health();errors.extend('Dependency: '+x['package'] for x in dependencies if x['status']=='FAIL')
    if not a.source_only:errors.extend('Data: '+x['path'] for x in data_health() if x['status']=='FAIL')
    # Verify none of the excluded runtime material is tracked when Git is available.
    try:
        tracked=subprocess.check_output(['git','-C',str(ROOT),'ls-files'],text=True,stderr=subprocess.DEVNULL).splitlines()
        errors.extend('File outside public allowlist: '+x for x in tracked if x not in public)
        errors.extend('Excluded tracked file: '+x for x in tracked if re.search(r'(^|/)(\.venv|\.runtime|full_card_predictor|\.claude|cache|_backup[^/]*)(/|$)',x) or x.startswith('mens_ufc_model/data/') or re.match(r'womens_ufc_model/output[^/]*/',x))
    except (FileNotFoundError,subprocess.CalledProcessError):pass
    print(json.dumps(dict(status='FAIL' if errors else 'PASS',python_files=parsed,public_files=len(public),dependency_checks=len(dependencies),errors=errors),indent=2))
    return bool(errors)

if __name__=='__main__':raise SystemExit(main())
