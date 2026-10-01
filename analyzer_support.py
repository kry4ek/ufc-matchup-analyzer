"""Portable installation and dataset checks; standard library only."""
from __future__ import annotations
import csv, datetime as dt, hashlib, importlib, importlib.metadata, json, os, pathlib, struct, sys, tempfile, urllib.request, zipfile

ROOT = pathlib.Path(__file__).resolve().parent
VERSION = '0.3.0'

def digest(path):
    with pathlib.Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def atomic_json(path, value):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    os.replace(temporary, path)

def safe_path(root, relative):
    root = pathlib.Path(root).resolve(); path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('Path must remain inside the project: ' + str(relative))
    return path

def csv_info(path):
    count = 0; latest = ''; invalid = 0
    with pathlib.Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream); columns = reader.fieldnames or []
        for row in reader:
            count += 1; value = row.get('event_date', row.get('date', '')) or ''
            if value:
                try:
                    date = dt.date.fromisoformat(value[:10])
                    invalid += date > dt.date.today()
                    latest = max(latest, date.isoformat())
                except ValueError:
                    invalid += 1
    return dict(rows=count, columns=columns, latest_date=latest or None, invalid_or_future_dates=invalid)

def manifest(root=ROOT):
    return json.loads((pathlib.Path(root) / 'dataset_manifest.json').read_text(encoding='utf-8'))

def data_health(root=ROOT, verify_hashes=True, targets=('men','women')):
    root=pathlib.Path(root); spec=manifest(root); state=root/'.runtime/local_dataset_state.json'
    current=json.loads(state.read_text(encoding='utf-8')) if state.exists() else spec
    expected={x['path']:x for x in current['files']}; checks=[]
    prefixes=tuple('mens_ufc_model/' if x=='men' else 'womens_ufc_model/' for x in targets)
    for original in spec['files']:
        rel=original['path']
        if not rel.startswith(prefixes): continue
        path=safe_path(root,rel); entry=expected.get(rel,original)
        if not path.is_file(): checks.append(dict(path=rel,status='FAIL',message='Missing; run setup or supply the matching dataset archive.'));continue
        try:
            info=csv_info(path)
            if not info['rows']: raise ValueError('Dataset is empty')
            missing=set(original['columns'])-set(info['columns'])
            if missing: raise ValueError('Missing columns: '+', '.join(sorted(missing)))
            if info['invalid_or_future_dates']: raise ValueError('Invalid or future event dates')
            if verify_hashes and digest(path)!=entry['sha256']: raise ValueError('Checksum changed outside a validated update; restore or rebuild explicitly.')
            checks.append(dict(path=rel,status='PASS',sha256=entry['sha256'] if verify_hashes else None,**info))
        except (ValueError,OSError,csv.Error) as exc:checks.append(dict(path=rel,status='FAIL',message=str(exc)))
    return checks

def dataset_state(root=ROOT):
    records=[]
    for entry in manifest(root)['files']:
        path=safe_path(root,entry['path'])
        records.append(dict(path=entry['path'],sha256=digest(path),size_bytes=path.stat().st_size,**csv_info(path)))
    return dict(version=VERSION,validated_at=dt.datetime.now(dt.timezone.utc).isoformat(),files=records)

def dependency_health(root=ROOT):
    results=[]
    for line in (pathlib.Path(root)/'requirements.lock').read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'): continue
        name,version=line.split('==')
        try:
            actual=importlib.metadata.version(name)
            results.append(dict(package=name,status='PASS' if actual==version else 'FAIL',expected=version,actual=actual))
        except importlib.metadata.PackageNotFoundError: results.append(dict(package=name,status='FAIL',expected=version,actual='missing'))
    return results

def install_dataset_archive(archive,root=ROOT):
    root=pathlib.Path(root); spec=manifest(root); expected={x['path']:x for x in spec['files']}
    # Validate every member and hash before touching any installed file.
    with tempfile.TemporaryDirectory(prefix='ufc-data-',dir=root) as temp:
        staging=pathlib.Path(temp)
        with zipfile.ZipFile(archive) as z:
            names=z.namelist()
            if len(names)!=len(set(names)) or set(names)!=set(expected):raise ValueError('Archive members do not match this release manifest')
            for name in names:
                entry=expected[name]; member=z.getinfo(name)
                if member.file_size!=entry['size_bytes']:raise ValueError('Unexpected dataset size: '+name)
                dest=safe_path(staging,name);dest.parent.mkdir(parents=True,exist_ok=True)
                with z.open(name) as src,dest.open('wb') as out:
                    import shutil; shutil.copyfileobj(src,out)
                if digest(dest)!=entry['sha256']:raise ValueError('Bad dataset checksum: '+name)
        existing=[name for name in names if safe_path(root,name).exists()]
        if existing:raise ValueError('Refusing to overwrite existing datasets; use a fresh extraction for archive recovery.')
        installed=[]
        try:
            for name in names:
                dest=safe_path(root,name);dest.parent.mkdir(parents=True,exist_ok=True);os.replace(safe_path(staging,name),dest);installed.append(dest)
        except BaseException:
            for path in installed:path.unlink(missing_ok=True)
            raise

def ensure_data(root=ROOT,archive=None):
    root=pathlib.Path(root);spec=manifest(root)
    present=[safe_path(root,x['path']).exists() for x in spec['files']]
    if all(present):return
    if any(present):raise ValueError('Incomplete dataset installation. Restore missing files from your matching beginner ZIP; setup will not overwrite existing data.')
    if archive:install_dataset_archive(archive,root);return
    repository=spec.get('release_repository')
    if not repository:raise ValueError('Data is absent. Use the beginner ZIP or setup --dataset-archive <matching ZIP>. Release URL has not yet been configured for publication.')
    import re
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('Invalid release repository')
    url=f'https://github.com/{repository}/releases/download/v{spec["version"]}/ufc-matchup-analyzer-datasets-v{spec["version"]}.zip'
    with tempfile.TemporaryDirectory(prefix='ufc-download-',dir=root) as temp:
        path=pathlib.Path(temp)/'datasets.zip'
        with urllib.request.urlopen(url,timeout=60) as source,path.open('wb') as target:
            import shutil;shutil.copyfileobj(source,target)
        install_dataset_archive(path,root)

def doctor(root=ROOT,skip_hashes=False):
    checks=[dict(component='Python',status='PASS' if sys.version_info[:2]==(3,14) and struct.calcsize('P')==8 else 'FAIL',message=sys.version.split()[0]+'; 64-bit Python 3.14 required')]
    checks.extend(dependency_health(root));checks.extend(data_health(root,not skip_hashes))
    try:
        for module in ['numpy','pandas','sklearn','joblib','requests','bs4','lxml.etree']:importlib.import_module(module)
        checks.append(dict(component='Runtime library imports',status='PASS'))
    except (ImportError,OSError) as exc:checks.append(dict(component='Runtime library imports',status='FAIL',message='Run setup again; '+str(exc)))
    try:
        with tempfile.TemporaryFile(dir=root):pass
        checks.append(dict(component='Writable project folder',status='PASS'))
    except OSError as exc:checks.append(dict(component='Writable project folder',status='FAIL',message=str(exc)))
    if (pathlib.Path(root)/'.runtime/maintenance.lock').exists():checks.append(dict(component='Maintenance lock',status='FAIL',message='An update is active or was interrupted; inspect .runtime and use recover after it stops.'))
    for check in checks:
        label=check.get('component',check.get('package',check.get('path','check')))
        print(f'{check["status"]}: {label}'+(' — '+check['message'] if 'message' in check else ''))
    return 1 if any(x['status']=='FAIL' for x in checks) else 0
