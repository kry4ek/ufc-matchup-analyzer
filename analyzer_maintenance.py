"""Staged, journaled data maintenance. Never write to the research workspace."""
from __future__ import annotations
import contextlib, datetime as dt, json, os, pathlib, shutil, subprocess, sys, uuid
from analyzer_support import ROOT, atomic_json, data_health, dataset_state, digest, safe_path
from analyzer_runtime import check_cancel, operation_lock, python_executable, run_logged_process,cleanup_stale_temp_aliases

ENGINE={'men':'mens_ufc_model','women':'womens_ufc_model'}

def run_logged(cmd,cwd,log):
    print('Running '+pathlib.Path(cmd[1]).name+' …',flush=True)
    run_logged_process(cmd,cwd,log)

def rebuild_engine(stage,sex,logs,runner=run_logged):
    cwd=stage/ENGINE[sex]
    if sex=='men':
        steps=[['src/data/build_mens_training_dataset.py'],['src/features/add_mens_elo_features.py'],['src/features/build_mens_advanced_features.py'],['src/features/build_mens_bayes_smoothing_candidate.py']]
    else:
        steps=[['build_prefight_bayesian_smoothing_v1_REBUILT.py','build','--training-rows','output_advanced_features_sig_fixed/ufc_womens_model_training_rows_advanced_sig_fixed.csv','--fighter-stats','output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv','--out-dir','output_bayesian_prefight_smoothing_sig_fixed_v1']]
    for i,args in enumerate(steps):runner([python_executable(),*args],cwd,logs/f'{sex}-rebuild-{i}.log')

def process_alive(pid):
    if not isinstance(pid,int) or pid<=0:return False
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return ctypes.get_last_error()==5
        try:
            code=ctypes.c_ulong()
            if not kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code)):return True
            return code.value==259
        finally:kernel.CloseHandle(ctypes.c_void_p(handle))
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True

@contextlib.contextmanager
def maintenance_lock(root,transaction):
    path=root/'.runtime/maintenance.lock';path.parent.mkdir(parents=True,exist_ok=True)
    try:
        with path.open('x',encoding='utf-8') as stream:json.dump(dict(pid=os.getpid(),transaction=transaction),stream)
    except FileExistsError as exc:raise RuntimeError('Maintenance is already active or interrupted. Use doctor and recover.') from exc
    try:yield
    finally:path.unlink(missing_ok=True)

def rollback(root,txn,journal):
    for record in reversed(journal.get('promotions',[])):
        target=safe_path(root,record['path']);saved=safe_path(txn/'before',record['path'])
        if record['existed']:
            if not saved.exists():raise RuntimeError('Recovery backup is missing: '+record['path'])
            temp=target.with_name(target.name+'.recovering');shutil.copy2(saved,temp);os.replace(temp,target)
        else:target.unlink(missing_ok=True)
    journal['status']='rolled_back';atomic_json(txn/'journal.json',journal)

def promote(root,stage,txn,journal,files):
    journal['status']='committing';atomic_json(txn/'journal.json',journal)
    for rel in files:
        source=safe_path(stage,rel);target=safe_path(root,rel)
        if target.exists() and digest(source)==digest(target):continue
        existed=target.exists()
        if existed:
            before=safe_path(txn/'before',rel);before.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,before)
        # Persist intent before replacement so recovery also handles an abrupt exit.
        journal['promotions'].append(dict(path=rel,existed=existed));atomic_json(txn/'journal.json',journal)
        target.parent.mkdir(parents=True,exist_ok=True);tmp=target.with_name(target.name+'.incoming');shutil.copy2(source,tmp);os.replace(tmp,target)
    journal['status']='committed';atomic_json(txn/'journal.json',journal)

def validate_engine(stage,sex,logs,runner=run_logged):
    checks=data_health(stage,False,(sex,))
    bad=[x for x in checks if x['status']=='FAIL']
    if bad:raise RuntimeError('Staged dataset validation failed: '+json.dumps(bad))
    if sex=='men':
        output=stage/ENGINE[sex]/'_update_manifests/dataset_validation.json'
        runner([python_executable(),'src/validation/validate_mens_dataset.py','--allow-mirrored','--out',str(output)],stage/ENGINE[sex],logs/'men-validation.log')
        result=json.loads(output.read_text(encoding='utf-8'))
        if not result['leakage_checks']['passed'] or not result['duplicates']['training_fight_id']['passed'] or result['target_checks']['invalid_or_missing_fighter_a_won'] or any(result['stat_row_integrity'][key] for key in ['fight_stat_rows_per_fight_not_two','fights_missing_stat_rows','fight_stats_for_unknown_fights']):
            raise RuntimeError('Men dataset integrity or leakage audit failed')
    else:
        # Draw/NC source rows can remain, but binary training must exclude them.
        import csv
        stats=stage/ENGINE[sex]/'output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv'
        with stats.open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        from collections import Counter
        pairs=Counter(r['fight_id'] for r in rows)
        if any(n!=2 for n in pairs.values()):raise RuntimeError('Women stats must contain two rows per fight')
        train=stage/ENGINE[sex]/'output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv'
        with train.open(encoding='utf-8-sig',newline='') as f:
            for row in csv.DictReader(f):
                if row.get('fighter_a_won') not in ('','0','1','0.0','1.0'):raise RuntimeError('Invalid women target')
                for key,value in row.items():
                    if key.endswith('history_max_event_date_before') and value and value[:10]>=row['event_date'][:10]:raise RuntimeError('Women prefight history leakage')

def validate_update_audits(cwd):
    import csv
    audits=list((cwd/'_update_manifests').rglob('new_rows_safety_audit.json'))
    if not audits:raise RuntimeError('Updater did not produce a safety audit')
    for path in audits:
        audit=json.loads(path.read_text(encoding='utf-8'))
        if 'unsafe_rows_count' not in audit:raise RuntimeError('Malformed safety audit')
        if audit['unsafe_rows_count']:raise RuntimeError('Unsafe staged rows; update blocked')
    for path in (cwd/'_update_manifests').rglob('*_inspected.csv'):
        with path.open(encoding='utf-8-sig',newline='') as stream:
            for row in csv.DictReader(stream):
                status=row.get('status','').lower()
                if 'error' in status or status in ('skipped_future_event','skipped_unresolved_result','skipped_no_winner_loser'):
                    raise RuntimeError('Incomplete or unsafe source capture: '+status+'. See '+str(path))

def data_files(engine):
    return {p.relative_to(engine).as_posix():digest(p) for p in engine.rglob('*') if p.is_file() and p.suffix in ('.csv','.json') and (p.relative_to(engine).parts[0]=='data' or p.relative_to(engine).parts[0].startswith('output'))}

def fight_count(engine,sex):
    import csv
    path=engine/('data/raw/ufcstats_men/fights.csv' if sex=='men' else 'output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv')
    if not path.exists():return 0
    with path.open(encoding='utf-8-sig',newline='') as stream:return len({r.get('fight_id') for r in csv.DictReader(stream)}-{None,''})

def maintenance(root=ROOT,kind='update',target='all',apply=False,max_events=None,from_date=None,runner=run_logged,validator=validate_engine,progress=None,cancel=None):
    with operation_lock(root,kind):
        return _maintenance(root,kind,target,apply,max_events,from_date,runner,validator,progress,cancel)

def _maintenance(root=ROOT,kind='update',target='all',apply=False,max_events=None,from_date=None,runner=run_logged,validator=validate_engine,progress=None,cancel=None):
    root=pathlib.Path(root).resolve();targets=list(ENGINE) if target=='all' else [target]
    emit=progress or (lambda **event:None)
    check_cancel(cancel)
    expected=sum(p.stat().st_size for sex in targets for p in (root/ENGINE[sex]).rglob('*') if p.is_file() and not any(part in ('.venv','__pycache__','cache','_update_manifests') or part.startswith('_backup') for part in p.parts))
    required=expected*3+64*1024*1024
    if shutil.disk_usage(root).free<required:raise RuntimeError(f'Not enough free space for a safe update. Free at least {required/1048576:.0f} MB on this drive and try again.')
    if runner is run_logged:
        def runner(cmd,cwd,log):
            run_logged_process(cmd,cwd,log,cancel)
    transaction=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
    txn=root/'.runtime/transactions'/transaction;stage=txn/'stage';logs=txn/'logs'
    journal=dict(id=transaction,kind=kind,targets=targets,status='staging',promotions=[],pid=os.getpid(),summary={})
    with maintenance_lock(root,transaction):
        emit(stage='staging',message='Preparing private dataset copies',cancellable=True)
        stage.mkdir(parents=True);atomic_json(txn/'journal.json',journal)
        try:
            shutil.copy2(root/'dataset_manifest.json',stage/'dataset_manifest.json')
            for sex in targets:
                shutil.copytree(root/ENGINE[sex],stage/ENGINE[sex],ignore=shutil.ignore_patterns('.venv','__pycache__','cache','_backup*','_update_manifests'))
            for sex in targets:
                check_cancel(cancel)
                cwd=stage/ENGINE[sex]
                before=data_files(cwd);count=fight_count(cwd,sex)
                if kind=='update':
                    emit(stage='download',message='Checking completed '+sex+' fights',cancellable=True)
                    script='update_ufc_mens_dataset_incremental.py' if sex=='men' else 'update_ufc_womens_dataset_incremental.py'
                    args=[python_executable(),script,'--audit','--manifest-dir','_update_manifests/run']
                    if sex=='women':args+=['--profiles','output_quality_fixed/ufc_womens_fighter_profiles.csv']
                    if max_events is not None:args+=['--max-events',str(max_events)]
                    if from_date:args+=['--from-date',from_date]
                    if apply:args+=['--apply']
                    runner(args,cwd,logs/f'{sex}-update.log')
                    validate_update_audits(cwd)
                    changed=data_files(cwd)!=before
                    journal['summary'][sex]=dict(added_fights=max(0,fight_count(cwd,sex)-count),changed=changed)
                    # Skipped unresolved/future fights must remain visible in audit logs.
                    if not apply:continue
                    if not changed:continue
                else:journal['summary'][sex]=dict(added_fights=0,changed=True)
                check_cancel(cancel)
                emit(stage='rebuilding',message='Rebuilding '+sex+' model features',cancellable=True)
                rebuild_engine(stage,sex,logs,runner)
                emit(stage='validating',message='Validating '+sex+' datasets and historical cutoffs',cancellable=True)
                validator(stage,sex,logs,runner)
            check_cancel(cancel)
            if kind=='update' and not apply:
                journal['status']='dry_run';atomic_json(txn/'journal.json',journal)
                print('Dry-run complete. Installed datasets unchanged. Audit: '+str(txn))
            elif kind=='update' and not any(x['changed'] for x in journal['summary'].values()):
                journal['status']='no_changes';atomic_json(txn/'journal.json',journal)
                print('Already up to date. Installed datasets unchanged.')
            else:
                # Only CSV/JSON data files inside retained data/output directories are promoted.
                files=[]
                for sex in targets:
                    engine=stage/ENGINE[sex]
                    for file in engine.rglob('*'):
                        relative=file.relative_to(engine)
                        if file.is_file() and file.suffix in ('.csv','.json') and (relative.parts[0]=='data' or relative.parts[0].startswith('output')):files.append(file.relative_to(stage).as_posix())
                # Update the verification state atomically as part of the same transaction.
                combined={x['path']:x for x in dataset_state(root)['files']}
                for sex in targets:
                    for entry in data_health(stage,False,(sex,)):
                        rel=entry['path'];path=stage/rel
                        combined[rel]=dict(path=rel,sha256=digest(path),size_bytes=path.stat().st_size,rows=entry['rows'],columns=entry['columns'],latest_date=entry['latest_date'])
                atomic_json(stage/'.runtime/local_dataset_state.json',dict(files=list(combined.values()),validated_at=dt.datetime.now(dt.timezone.utc).isoformat(),transaction=transaction))
                files.append('.runtime/local_dataset_state.json')
                check_cancel(cancel)
                emit(stage='committing',message='Installing validated datasets; please wait',cancellable=False)
                promote(root,stage,txn,journal,sorted(files))
                print('Validated datasets committed. Backup/recovery ID: '+transaction)
        except BaseException:
            rollback(root,txn,journal)
            raise
        finally:
            for sex in targets:
                audits=stage/ENGINE[sex]/'_update_manifests'
                if audits.exists():shutil.copytree(audits,txn/'audits'/sex,dirs_exist_ok=True)
            # Remove only the verified private staging tree; retain audits and backups.
            if stage.exists() and stage.resolve().is_relative_to((root/'.runtime/transactions').resolve()):shutil.rmtree(stage)
    emit(stage='complete',message='Already up to date' if journal['status']=='no_changes' else 'Dataset operation complete',cancellable=False)
    return transaction

def recover(root=ROOT,transaction=None):
    with operation_lock(root,'recovery'):
        return _recover(root,transaction)

def _recover(root=ROOT,transaction=None):
    root=pathlib.Path(root).resolve();lock=root/'.runtime/maintenance.lock'
    active=json.loads(lock.read_text(encoding='utf-8')) if lock.exists() else {}
    if process_alive(active.get('pid')):raise RuntimeError('Maintenance process is still running; recovery refused')
    transaction=transaction or active.get('transaction')
    if not transaction:raise ValueError('Provide --transaction ID from the update output')
    if pathlib.Path(transaction).name!=transaction or transaction in ('.','..'):raise ValueError('Invalid transaction ID')
    txn=safe_path(root/'.runtime/transactions',transaction)
    journal=json.loads((txn/'journal.json').read_text(encoding='utf-8'))
    if journal['status']=='committed':
        state=root/'.runtime/local_dataset_state.json'
        if not state.exists() or json.loads(state.read_text(encoding='utf-8')).get('transaction')!=transaction:
            raise RuntimeError('Only the most recent committed maintenance transaction can be restored')
    if journal['status']=='rolled_back':print('Already restored.');lock.unlink(missing_ok=True);return
    rollback(root,txn,journal);lock.unlink(missing_ok=True);print('Restored the datasets from before transaction '+transaction)

def recover_interrupted(root=ROOT):
    """Journal status, rather than a stale filename alone, determines recovery."""
    root=pathlib.Path(root)
    with operation_lock(root,'startup recovery'):
        cleanup_stale_temp_aliases(root,process_alive)
        lock=root/'.runtime/maintenance.lock'
        active=json.loads(lock.read_text(encoding='utf-8')) if lock.exists() else {}
        if process_alive(active.get('pid')):raise RuntimeError('A dataset update is still running. Wait for it to finish.')
        recovered=[]
        transactions=root/'.runtime/transactions'
        for path in sorted(transactions.glob('*/journal.json')):
            journal=json.loads(path.read_text(encoding='utf-8'))
            if journal['status'] in ('staging','committing'):
                if process_alive(journal.get('pid')):raise RuntimeError('A dataset update is still running.')
                rollback(root,path.parent,journal)
                stage=path.parent/'stage'
                if stage.exists() and stage.resolve().is_relative_to(transactions.resolve()):shutil.rmtree(stage)
                recovered.append(journal['id'])
        lock.unlink(missing_ok=True)
        return recovered

def cleanup_history(root=ROOT):
    root=pathlib.Path(root)
    state=root/'.runtime/local_dataset_state.json'
    keep=json.loads(state.read_text(encoding='utf-8')).get('transaction') if state.exists() else None
    txns=root/'.runtime/transactions'
    items=sorted(txns.glob('*/journal.json'),reverse=True)
    for index,path in enumerate(items):
        journal=json.loads(path.read_text(encoding='utf-8'))
        if journal['status'] in ('staging','committing') or journal['id']==keep:continue
        backup=path.parent/'before'
        if backup.exists() and backup.resolve().is_relative_to(txns.resolve()):shutil.rmtree(backup)
        if index>=10 and path.parent.resolve().is_relative_to(txns.resolve()):shutil.rmtree(path.parent)
    for directory in (root/'.runtime/jobs',root/'.runtime/logs'):
        files=sorted((p for p in directory.glob('*') if p.is_file()),key=lambda p:p.stat().st_mtime,reverse=True)
        for path in files[40:]:path.unlink(missing_ok=True)
