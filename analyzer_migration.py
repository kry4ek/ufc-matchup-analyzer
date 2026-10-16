"""Bounded, reviewed JSON import. Original installations are read-only."""
from __future__ import annotations
import contextlib
import json
import os
from pathlib import Path
import shutil
import uuid
from analyzer_history import History, fingerprint, MAX_BYTES, MAX_ENTRIES, utc_now
from analyzer_support import atomic_json, digest, safe_path
from analyzer_runtime import operation_lock, check_cancel

MAX_FILE = 8 * 1024 * 1024
MAX_SCAN = 200

def read_json(path, limit=MAX_FILE):
    if path.is_symlink() or path.stat().st_size>limit: raise ValueError('Unsupported link or oversized JSON: '+path.name)
    return json.loads(path.read_text(encoding='utf-8'))

def valid_entry(value, name):
    if not isinstance(value,dict) or value.get('schema')!=1: raise ValueError('Unsupported history schema')
    identifier=value.get('id','')
    if len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier) or name!=identifier+'.json': raise ValueError('Invalid history identity')
    if value.get('integrity')!=fingerprint({k:v for k,v in value.items() if k!='integrity'}): raise ValueError('History integrity mismatch')
    if not all(isinstance(value.get(k),dict) for k in ('request','context','payload')): raise ValueError('Invalid history structure')
    if not all(isinstance(value.get(k),str) for k in ('created_at','cache_key')): raise ValueError('Invalid history metadata')
    import datetime as dt
    try:
        created=dt.datetime.fromisoformat(value['created_at'])
        if created.tzinfo is None:raise ValueError('Missing timestamp timezone')
    except ValueError as exc:raise ValueError('Invalid history timestamp') from exc
    request=value['request'];payload=value['payload']
    if request.get('sex') not in ('men','women') or request.get('operation') not in ('predict','compare'): raise ValueError('Unsupported calculation')
    if payload.get('result_state','complete') not in ('complete','comparison') or payload.get('quick_comparison'): raise ValueError('Partial reports cannot be imported')
    for k in ('fighter_a','fighter_b','fight_date'):
        if not isinstance(payload.get(k),str) or not payload[k] or request.get(k)!=payload[k]: raise ValueError('Mismatched saved matchup')
    if value['cache_key']!=fingerprint(dict(request=request,context=value['context'])): raise ValueError('Invalid reuse context')
    from analyzer_catalog import iso_date
    from argparse import ArgumentTypeError
    try:iso_date(payload['fight_date'])
    except ArgumentTypeError as exc:raise ValueError('Invalid saved fight date') from exc
    if payload.get('result_state','complete')=='complete':
        from ufc_matchup_analyzer import validate_prediction
        validate_prediction(payload)
    if 'visual_evidence' in payload:
        record=payload['visual_evidence']
        if not isinstance(record,dict) or record.get('schema')!=1:raise ValueError('Unsupported visual evidence schema')
    if 'evidence_quality' in payload:
        from analyzer_evidence import validate_evidence
        validate_evidence(payload['evidence_quality'])
    from analyzer_bout_context import validate_context
    validate_context(payload)
    # Integrity alone does not establish that a record has a readable payload.
    # Rendering uses only captured JSON; it does not consult today's datasets.
    from analyzer_results import format_result
    from analyzer_reporting import format_html
    try:format_result(payload);format_html(payload)
    except (KeyError,TypeError,ValueError,AttributeError) as exc:raise ValueError('Unsupported saved report structure') from exc
    return value

def preferences(value,root=None):
    if not isinstance(value,dict): return {}
    result={}
    if value.get('text_size') in ('Small','Medium','Large'): result['text_size']=value['text_size']
    for field in ('inputs_collapsed','maximized'):
        if type(value.get(field)) is bool:result[field]=value[field]
    geometry=value.get('geometry','')
    try:
        w,h=map(int,geometry.split('x'))
        if 400<=w<=10000 and 300<=h<=10000:result['geometry']=f'{w}x{h}'
    except (AttributeError,ValueError):pass
    if root is not None:
        from analyzer_catalog import FighterCatalog,MEN_DIVISIONS,WOMEN_DIVISIONS
        divisions={('Men — '+d):'men' for d in MEN_DIVISIONS}
        divisions.update({('Women — '+d):'women' for d in WOMEN_DIVISIONS})
        division=value.get('division')
        if division in divisions:
            try:
                catalog=FighterCatalog(divisions[division],root)
                result['division']=division
                for side in ('a','b'):
                    name=value.get('fighter_'+side,'')
                    try:resolved=catalog.resolve(name) if isinstance(name,str) and len(name)<=256 and name else None
                    except ValueError:resolved=None
                    result['fighter_'+side]=resolved[0] if resolved else ''
            except (OSError,ValueError,KeyError):pass
    return result

def source_root(folder):
    source=Path(folder).resolve()
    if (source/'app/analyzer_support.py').is_file():source=source/'app'
    if not (source/'analyzer_support.py').is_file() or not (source/'.runtime/history').is_dir():
        raise ValueError('Choose an extracted app folder containing saved analyses.')
    return source.resolve()

def capacity(root):
    files=list((Path(root)/'.runtime/history').glob('*.json'))
    return len(files),sum(p.stat().st_size for p in files)

def preview(root,folder):
    root=Path(root).resolve();source=source_root(folder)
    if source==root or source.is_relative_to(root) or root.is_relative_to(source): raise ValueError('Choose a separate previous installation.')
    with operation_lock(root,'import_preview'):
        recover(root)
        target=History(root);existing={e['id']:e for e in target.entries()}
        contents={fingerprint(e) for e in existing.values()}
        rows=[];counts=dict(valid=0,duplicate=0,conflict=0,invalid=0,over_budget=0)
        paths=sorted((source/'.runtime/history').glob('*.json'))
        if len(paths)>MAX_SCAN:raise ValueError('Too many history files; import is limited to 200 files.')
        count,size=capacity(root);captured_bytes=0
        for path in paths:
            row=dict(name=path.name)
            try:
                if not path.resolve().is_relative_to(source/'.runtime/history'):raise ValueError('History path leaves the selected folder')
                entry=valid_entry(read_json(path),path.name);raw_size=path.stat().st_size
                status='duplicate' if fingerprint(entry) in contents else 'conflict' if entry['id'] in existing or (target.directory/path.name).exists() else 'over_budget' if count+1>MAX_ENTRIES or size+raw_size>MAX_BYTES else 'valid'
                can_capture=status in ('valid','over_budget') and captured_bytes+raw_size<=MAX_BYTES
                row.update(status=status,sha256=digest(path),size=raw_size,entry=entry if can_capture else None)
                if can_capture:captured_bytes+=raw_size
                if status=='valid':count+=1;size+=raw_size
            except (ValueError,OSError,TypeError,KeyError) as exc:row.update(status='invalid',reason=str(exc))
            counts[row['status']]+=1;rows.append(row)
        prefs={};prefs_hash=None
        path=source/'.runtime/ui_preferences.json'
        if path.exists():
            with contextlib.suppress(ValueError,OSError,TypeError):prefs=preferences(read_json(path,65536),root);prefs_hash=digest(path)
        value=dict(schema=1,id=uuid.uuid4().hex,created_at=utc_now(),source=str(source),rows=rows,counts=counts,
                   preferences=prefs,preferences_sha256=prefs_hash,target_capacity=capacity(root))
        value['integrity']=fingerprint(value)
        directory=root/'.runtime/import_previews';directory.mkdir(parents=True,exist_ok=True)
        for old in sorted(directory.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[9:]:old.unlink()
        atomic_json(directory/(value['id']+'.json'),value)
        return value

def identifier_path(root,directory,identifier):
    if len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier): raise ValueError('Invalid import identity')
    return Path(root)/'.runtime'/directory/(identifier+'.json')

def rollback(root,journal):
    conflicts=[]
    for item in journal['files']:
        path=safe_path(root,'.runtime/history/'+item['name'])
        if path.exists():
            if digest(path)==item['sha256']:path.unlink()
            else:conflicts.append(item['name'])
    if journal.get('preferences_after') is not None:
        path=Path(root)/'.runtime/ui_preferences.json'
        current=read_json(path,65536) if path.exists() else None
        if current==journal['preferences_after']:
            if journal['preferences_before'] is None:path.unlink(missing_ok=True)
            else:atomic_json(path,journal['preferences_before'])
        elif current!=journal['preferences_before']:conflicts.append('preferences')
    journal['status']='rolled_back';journal['conflicts']=conflicts
    atomic_json(identifier_path(root,'imports',journal['id']),journal)
    return conflicts

def recover(root):
    directory=Path(root)/'.runtime/imports'
    for path in directory.glob('*.json'):
        value=read_json(path,MAX_BYTES+1024*1024)
        if value.get('status')=='committing':rollback(root,value)
        # A crash can leave complete staged copies after commit or rollback.
        # Remove only this journal's unchanged files, preserving unrelated content.
        identifier_path(root,'imports',value['id'])
        staging=safe_path(root,'.runtime/import_staging/'+value['id'])
        if staging.is_dir():
            for item in value.get('files',[]):
                staged=safe_path(staging,item['name'])
                if staged.is_file() and digest(staged)==item['sha256']:staged.unlink()
            if not any(staging.iterdir()):staging.rmdir()

def apply(root,identifier,import_preferences=False,cancel=None,selected_ids=None):
    root=Path(root).resolve()
    with operation_lock(root,'import'):
        recover(root)
        value=read_json(identifier_path(root,'import_previews',identifier),MAX_BYTES+1024*1024)
        if value.get('integrity')!=fingerprint({k:v for k,v in value.items() if k!='integrity'}):raise ValueError('Import preview changed; review again.')
        source=source_root(value['source'])
        if selected_ids is None:chosen=[r for r in value['rows'] if r['status']=='valid']
        else:
            if not isinstance(selected_ids,list) or len(selected_ids)!=len(set(selected_ids)):raise ValueError('Invalid selected history list')
            available={r['name'][:-5]:r for r in value['rows'] if r['status'] in ('valid','over_budget') and r.get('entry')}
            if any(identifier not in available for identifier in selected_ids):raise ValueError('Select only reviewed eligible records')
            chosen=[available[identifier] for identifier in selected_ids]
        if source==root or source.is_relative_to(root) or root.is_relative_to(source):raise ValueError('Invalid source folder')
        count,size=capacity(root)
        if count+len(chosen)>MAX_ENTRIES or size+sum(r['size'] for r in chosen)>MAX_BYTES:raise ValueError('History capacity changed; review import again.')
        captured=[]
        for row in chosen:
            check_cancel(cancel)
            path=safe_path(source,'.runtime/history/'+row['name'])
            if digest(path)!=row['sha256']:raise ValueError('Previous history changed; review import again.')
            valid_entry(row['entry'],row['name'])
            if (root/'.runtime/history'/row['name']).exists():raise ValueError('Destination changed; review import again.')
            captured.append((row,json.dumps(row['entry'],indent=2,allow_nan=False)+'\n'))
        # Serialized size can differ from source whitespace; enforce the installed budget.
        if size+sum(len(raw.encode('utf-8')) for _,raw in captured)>MAX_BYTES:raise ValueError('Serialized import exceeds history capacity.')
        if shutil.disk_usage(root).free<sum(len(raw.encode('utf-8')) for _,raw in captured)+64*1024**2:raise OSError('Insufficient space for a safe import.')
        prefs_path=root/'.runtime/ui_preferences.json';before=read_json(prefs_path,65536) if prefs_path.exists() else None
        after=None
        if import_preferences and value['preferences']:
            if digest(source/'.runtime/ui_preferences.json')!=value['preferences_sha256']:raise ValueError('Previous preferences changed; review import again.')
            if preferences(value['preferences'],root)!=value['preferences']:raise ValueError('Remembered fighter availability changed; review import again.')
            after=dict(before or {},**value['preferences'])
            if after==before:after=None
        unselected=sum(r['status'] in ('valid','over_budget') for r in value['rows'])-len(chosen)
        message=f"Imported {len(chosen)} analyses. Skipped: {value['counts']['duplicate']} duplicates, {value['counts']['conflict']} conflicts, {value['counts']['invalid']} invalid, {unselected} unselected or over budget."
        if not captured and after is None:return dict(message=message,preferences={})
        journal=dict(schema=1,id=uuid.uuid4().hex,status='committing',created_at=utc_now(),source=value['source'],
                     files=[],preferences_before=before,preferences_after=after)
        import hashlib
        for row,raw in captured:journal['files'].append(dict(name=row['name'],sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest()))
        check_cancel(cancel);atomic_json(identifier_path(root,'imports',journal['id']),journal)
        try:
            staging=root/'.runtime/import_staging'/journal['id'];staging.mkdir(parents=True)
            for row,raw in captured:
                path=safe_path(root,'.runtime/history/'+row['name']);path.parent.mkdir(parents=True,exist_ok=True)
                staged=staging/row['name'];staged.write_text(raw,encoding='utf-8',newline='\n')
                # Same-volume hard link publishes a complete file exclusively; no overwrite.
                os.link(staged,path)
            if after is not None:atomic_json(prefs_path,after)
            journal['status']='committed';atomic_json(identifier_path(root,'imports',journal['id']),journal)
        except BaseException:
            rollback(root,journal);raise
        finally:
            if 'staging' in locals() and staging.exists():
                for staged in staging.glob('*.json'):staged.unlink()
                staging.rmdir()
        return dict(message=message,preferences=value['preferences'] if after is not None else {})

def undo(root):
    with operation_lock(root,'undo_import'):
        recover(root)
        journals=[read_json(p,MAX_BYTES+1024*1024) for p in (Path(root)/'.runtime/imports').glob('*.json')]
        journals=[j for j in journals if j.get('status')=='committed']
        if not journals:raise ValueError('There is no committed import to undo.')
        latest=max(journals,key=lambda j:j['created_at']);conflicts=rollback(root,latest)
        prefs_path=Path(root)/'.runtime/ui_preferences.json'
        current=read_json(prefs_path,65536) if prefs_path.exists() else {}
        return dict(message='Latest import undone.'+(' Changed files retained: '+', '.join(conflicts) if conflicts else ''),preferences_snapshot=current)
