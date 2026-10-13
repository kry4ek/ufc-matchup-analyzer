"""Bounded fresh source rechecks and immutable, reviewed replacement transactions."""
from __future__ import annotations
import contextlib
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent))
from analyzer_history import fingerprint, utc_now
from analyzer_support import atomic_json, digest, safe_path
from analyzer_runtime import check_cancel, operation_lock, python_executable
from analyzer_errors import MaintenanceError

MAX_EVENTS=20
SCHEMA=1
SOURCE_PATHS={'men':['mens_ufc_model/data/raw/ufcstats_men/fights.csv','mens_ufc_model/data/raw/ufcstats_men/fight_stats.csv'],
              'women':['womens_ufc_model/output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv']}

def read_rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))

def write_rows(path,rows,columns=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns or list(rows[0]),extrasaction='ignore');writer.writeheader();writer.writerows(rows)

def canonical(value):
    if value is None:return None
    text=' '.join(str(value).split())
    if text.casefold() in ('','nan','none','null','--','---'):return None
    if len(text)>=10:
        try:
            if text[10:] in ('',' 00:00:00','T00:00:00'):return dt.date.fromisoformat(text[:10]).isoformat()
        except ValueError:pass
    try:
        n=Decimal(text)
        if n.is_finite():return str(n.normalize())
    except InvalidOperation:pass
    return text

def row_identity(row,sex):
    return row.get('fighter_id') if sex=='men' else row.get('profile_url','').rstrip('/').rsplit('/',1)[-1]

def validate_pair(rows,sex,fid):
    if not fid:raise ValueError('Source fight identity is missing.')
    dates={canonical(r.get('event_date')) for r in rows}
    if len(dates)!=1 or None in dates:raise ValueError('Paired dates disagree for '+fid)
    date=dt.date.fromisoformat(next(iter(dates))[:10])
    if date>dt.date.today():raise ValueError('Future source bout: '+fid)
    results=[r.get('result') for r in rows]
    if results in (['win','loss'],['loss','win']):
        if any(canonical(r.get('won'))!=('1' if r['result']=='win' else '0') for r in rows):raise ValueError('Decisive targets disagree for '+fid)
    elif results in (['draw','draw'],['nc','nc'],['no_contest','no_contest']):
        if any(canonical(r.get('won')) is not None for r in rows):raise ValueError('Draw/NC targets must be empty for '+fid)
    else:raise ValueError('Inconsistent completed results for '+fid)
    if 'result_marker' in rows[0]:
        expected={'win':'W','loss':'L','draw':'D','nc':'NC','no_contest':'NC'}
        if any(str(r.get('result_marker','')).upper().replace('/','')!=expected[r['result']] for r in rows):raise ValueError('Source markers disagree for '+fid)

def diff_capture(root,sex,capture):
    """Validate complete paired replacements independently of the append audit."""
    old_tables={rel:read_rows(Path(root)/rel) for rel in SOURCE_PATHS[sex]}
    changes=[]
    events=capture['events'];dates={e['event_date'][:10] for e in events}
    names={e['event_name'] for e in events};event_ids={e['event_id'] for e in events}
    event_lookup={}
    event_path=Path(root)/'mens_ufc_model/data/raw/ufcstats_men/events.csv'
    if sex=='women' and event_path.exists():
        for event in read_rows(event_path):event_lookup.setdefault((canonical(event['event_date']),event['event_name']),set()).add(event['event_id'])
    source=capture['tables']
    if sex=='men':
        fights=source[SOURCE_PATHS[sex][0]];stats=source[SOURCE_PATHS[sex][1]]
        groups={}
        for row in stats:groups.setdefault(row['fight_id'],[]).append(row)
        if {r['fight_id'] for r in fights}!=set(groups):raise ValueError('Raw bouts and paired statistics identify different fights.')
        for fight in fights:
            rows=groups[fight['fight_id']]
            if len(rows)!=2:raise ValueError('Incomplete linked statistics for '+fight['fight_id'])
            if {fight.get('fighter_red_id'),fight.get('fighter_blue_id')}!={r.get('fighter_id') for r in rows}:raise ValueError('Linked fighter identities disagree for '+fight['fight_id'])
            result=fight.get('result')
            if result=='win_loss':
                winners=[r.get('fighter_id') for r in rows if r.get('result')=='win']
                losers=[r.get('fighter_id') for r in rows if r.get('result')=='loss']
                if winners!=[fight.get('winner_id')] or losers!=[fight.get('loser_id')]:raise ValueError('Raw and paired outcomes disagree for '+fight['fight_id'])
            elif result in ('draw','no_contest'):
                if canonical(fight.get('winner_id')) is not None or canonical(fight.get('loser_id')) is not None or any(r.get('result')!=result for r in rows):raise ValueError('Raw and paired outcomes disagree for '+fight['fight_id'])
            else:raise ValueError('Unsupported completed raw result for '+fight['fight_id'])
            if any(canonical(r.get('event_date'))!=canonical(fight.get('event_date')) or r.get('event_id')!=fight.get('event_id') for r in rows):raise ValueError('Linked event metadata disagrees for '+fight['fight_id'])
    seen_ids=set()
    for rel,old_rows in old_tables.items():
        new_rows=source[rel]
        old_groups={};new_groups={}
        for row in old_rows:old_groups.setdefault(row['fight_id'],[]).append(row)
        for row in new_rows:new_groups.setdefault(row['fight_id'],[]).append(row)
        expected={r['fight_id'] for r in old_rows if (r.get('event_id') in event_ids if sex=='men' else
            bool(event_lookup.get((canonical(r.get('event_date')),r.get('event_name')),set()) & event_ids) or r.get('event_name') in names and r.get('event_date','')[:10] in dates)}
        if expected-set(new_groups):raise ValueError('Known bouts are missing from the fresh capture: '+', '.join(sorted(expected-set(new_groups))))
        for fid,rows in new_groups.items():
            paired=not (sex=='men' and rel.endswith('/fights.csv'))
            if len(rows)!=(2 if paired else 1):raise ValueError('Incomplete or duplicate source rows for '+fid)
            if paired:
                validate_pair(rows,sex,fid)
                ids=[row_identity(r,sex) for r in rows]
                if not all(ids) or len(set(ids))!=2:raise ValueError('Unresolved fighter identities for '+fid)
                if fid in old_groups and {row_identity(r,sex) for r in old_groups[fid]}!=set(ids):raise ValueError('Fighter identity changed for '+fid)
                if sex=='women' and fid in old_groups:
                    from analyzer_catalog import key as name_key
                    previous={row_identity(r,sex):r for r in old_groups[fid]}
                    if any(name_key(r['fighter'])!=name_key(previous[row_identity(r,sex)]['fighter']) for r in rows):
                        raise ValueError('Fighter name changed for '+fid+'; the name-based engine requires identity reconciliation before replacement.')
            elif fid in old_groups:
                fields=('fighter_red_id','fighter_blue_id')
                if {rows[0].get(k) for k in fields}!={old_groups[fid][0].get(k) for k in fields}:raise ValueError('Fighter identity changed for '+fid)
            old=old_groups.get(fid,[])
            key=lambda r: str(row_identity(r,sex) or r['fight_id'])
            before=sorted(old,key=key);after=sorted(rows,key=key)
            differences=[]
            for index,row in enumerate(after):
                previous=before[index] if index<len(before) else {}
                for column in old_rows[0]:
                    if column not in row:raise ValueError('Fresh capture omitted source field '+column+' for '+fid)
                    x,y=canonical(previous.get(column)),canonical(row.get(column))
                    if x!=y:differences.append(dict(identity=key(row),field=column,before=previous.get(column),after=row.get(column)))
            if differences:
                changes.append(dict(path=rel,fight_id=fid,kind='corrected' if old else 'added',differences=differences))
                seen_ids.add(fid)
    return changes

def capture_source(root,sex,start,end,progress=None):
    """Runs in a hidden child process; no installed or derived data is written."""
    import pandas as pd
    from bs4 import BeautifulSoup
    from analyzer_maintenance import ENGINE
    cwd=Path(root)/ENGINE[sex]
    sys.path.insert(0,str(cwd))
    name='recheck_updater_'+sex
    spec=importlib.util.spec_from_file_location(name,cwd/('update_ufc_'+('mens' if sex=='men' else 'womens')+'_dataset_incremental.py'))
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    prior=sys.argv;sys.argv=[str(spec.origin)]
    try:args=module.parse_args()
    finally:sys.argv=prior
    notify=progress or (lambda **kw:None)
    if sex=='men':
        scraper=module.make_scraper(args);scraper.refresh_cache=True
        soup=BeautifulSoup(scraper.fetch_html(args.events_url),'lxml')
    else:
        session=module.make_session(args.user_agent)
        soup=module.fetch_soup(session,args.events_url,timeout=args.timeout,sleep=args.sleep)
    all_events=module.parse_event_list(soup)
    if not all_events:raise ValueError('No completed events could be parsed.')
    events=module.select_completed_events(all_events,pd.Timestamp(start),pd.Timestamp(end),None)
    if len({e['event_url'] for e in events})!=len(events):raise ValueError('Duplicate completed event identities in source listing.')
    if len(events)>MAX_EVENTS:raise ValueError(f'This range contains {len(events)} events; narrow it to at most {MAX_EVENTS}.')
    selected=[dict(event_id=e.get('event_id') or e['event_url'].rstrip('/').rsplit('/',1)[-1],event_name=e['event_name'],event_date=str(e['event_date'].date()),location=e.get('location',''),event_url=e['event_url']) for e in events]
    known_events=Path(root)/'mens_ufc_model/data/raw/ufcstats_men/events.csv'
    if known_events.exists():
        expected={e['event_id'] for e in read_rows(known_events) if start<=e['event_date'][:10]<=end}
        missing=expected-{e['event_id'] for e in selected}
        if missing:raise ValueError('Known completed events are missing from the fresh listing: '+', '.join(sorted(missing)))
    notify(stage='download',message='Selected '+str(len(selected))+' completed events',detail='; '.join(e['event_date']+' '+e['event_name'] for e in selected))
    tables={rel:[] for rel in SOURCE_PATHS[sex]}
    today=pd.Timestamp(dt.date.today())
    existing={r['fight_id'] for r in read_rows(Path(root)/SOURCE_PATHS[sex][0])}
    for i,event in enumerate(events):
        notify(stage='download',message='Rechecking '+event['event_name'],completed=i,total=len(events),unit='events')
        if sex=='men':
            metas=scraper.get_event_fights(event['event_url'])
            if not metas:raise ValueError('Event contains no fight links: '+event['event_name'])
            for meta in metas:
                if not module.is_mens_fight_meta(meta):continue
                # Re-fetched pairs use the same completed W/blank inference as new
                # captures; replacement identities are independently checked below.
                module.validate_completed_fight_meta(meta,event,today=today,allow_future_events=False,existing_fight_ids=set())
                fight,rows,_=module.parse_fight_detail(scraper,pd.Series(event),meta)
                module.validate_parsed_result(meta,fight,rows,today,False)
                tables[SOURCE_PATHS[sex][0]].append(fight);tables[SOURCE_PATHS[sex][1]].extend(rows)
        else:
            event_soup=module.fetch_soup(session,event['event_url'],timeout=args.timeout,sleep=args.sleep)
            links=list(dict.fromkeys(a.get('href') for a in event_soup.select('a[href*="/fight-details/"]') if a.get('href')))
            if not links:raise ValueError('Event contains no fight links: '+event['event_name'])
            for link in links:
                rows=module.parse_fight_page(session,link,event,timeout=args.timeout,sleep=args.sleep,today=today,allow_future_events=False)
                if rows:tables[SOURCE_PATHS[sex][0]].extend(rows)
    # Preserve the existing source schema; scrapers may include unrelated helper fields.
    for rel,rows in tables.items():
        columns=list(read_rows(Path(root)/rel)[0])
        tables[rel]=[{k:('' if pd.isna(r.get(k)) else str(r.get(k))) for k in columns} for r in rows]
    if sex=='men':
        audit=module.audit_new_rows_for_apply(pd.DataFrame(tables[SOURCE_PATHS[sex][0]]),pd.DataFrame(tables[SOURCE_PATHS[sex][1]]),set(),today,False)
    else:audit=module.audit_new_rows_for_apply(pd.DataFrame(tables[SOURCE_PATHS[sex][0]]),set(),today,False)
    if audit['unsafe_rows_count']:raise ValueError('Fresh capture failed paired-result/target validation: '+str(audit['issues']))
    return dict(events=selected,tables=tables,audit=audit)

def preview(root,start=None,end=None,progress=None,cancel=None,runner=None):
    from analyzer_maintenance import ENGINE
    from analyzer_runtime import run_logged_process
    root=Path(root).resolve();notify=progress or (lambda **kw:None)
    end=end or dt.date.today().isoformat();start=start or (dt.date.fromisoformat(end)-dt.timedelta(days=90)).isoformat()
    if dt.date.fromisoformat(start)>dt.date.fromisoformat(end) or dt.date.fromisoformat(end)>dt.date.today():raise ValueError('Choose an ordered range ending no later than today.')
    identifier=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
    txn=root/'.runtime/corrections'/identifier;txn.mkdir(parents=True)
    from analyzer_support import dataset_state
    baseline={e['path']:digest(root/e['path']) for e in dataset_state(root)['files']}
    captures={};changes=[]
    with operation_lock(root,'recheck'):
        attempts=sorted((root/'.runtime/corrections').iterdir(),key=lambda p:p.stat().st_mtime_ns,reverse=True)
        for old in attempts[10:]:
            if old.is_dir() and old.resolve().is_relative_to((root/'.runtime/corrections').resolve()):shutil.rmtree(old)
        for sex in ('men','women'):
            check_cancel(cancel);output=txn/(sex+'.json')
            cmd=[python_executable(),str(root/'analyzer_corrections.py'),'capture',sex,start,end,str(output)]
            if runner:runner(cmd,root/ENGINE[sex],txn/(sex+'.log'))
            else:run_logged_process(cmd,root/ENGINE[sex],txn/(sex+'.log'),progress=notify,cancel=cancel)
            captures[sex]=json.loads(output.read_text(encoding='utf-8'))
            changes.extend(dict(sex=sex,**c) for c in diff_capture(root,sex,captures[sex]))
        value=dict(schema=SCHEMA,id=identifier,created_at=utc_now(),start=start,end=end,baseline=baseline,captures=captures,changes=changes)
        value['integrity']=fingerprint(value);atomic_json(txn/'preview.json',value)
        previews=sorted((root/'.runtime/corrections').glob('*/preview.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True)
        for old in previews[10:]:
            if old.parent.resolve().is_relative_to((root/'.runtime/corrections').resolve()):shutil.rmtree(old.parent)
        return value

def validate_preview(root,identifier):
    import re
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}-[a-f0-9]{8}',identifier):raise ValueError('Invalid correction preview ID.')
    p=Path(root)/'.runtime/corrections'/identifier/'preview.json'
    try:value=json.loads(p.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:raise ValueError('The preview is unavailable or malformed; recheck the selected events again.') from exc
    if value.get('schema')!=SCHEMA or value.get('id')!=identifier or value.get('integrity')!=fingerprint({k:v for k,v in value.items() if k!='integrity'}):raise ValueError('Correction preview changed; recheck the source again.')
    for rel,sha in value['baseline'].items():
        if digest(safe_path(root,rel))!=sha:raise ValueError('Installed datasets changed since this preview; recheck again.')
    for sex in ('men','women'):
        expected=diff_capture(root,sex,value['captures'][sex])
        if expected!=[{k:v for k,v in c.items() if k!='sex'} for c in value['changes'] if c['sex']==sex]:raise ValueError('Correction preview is inconsistent.')
    return value

def apply_source(stage,sex,capture,changes):
    """Replace full paired records; keep unaffected raw/source rows intact."""
    wanted={c['fight_id'] for c in changes if c['sex']==sex}
    for rel in SOURCE_PATHS[sex]:
        rows=read_rows(Path(stage)/rel);columns=list(rows[0])
        combined=[r for r in rows if r['fight_id'] not in wanted]+[r for r in capture['tables'][rel] if r['fight_id'] in wanted]
        combined.sort(key=lambda r:(r.get('event_date',''),r['fight_id'],str(row_identity(r,sex))))
        write_rows(Path(stage)/rel,combined,columns)
    if sex=='men':
        path=Path(stage)/'mens_ufc_model/data/raw/ufcstats_men/events.csv'
        if path.exists():
            rows=read_rows(path);columns=list(rows[0]);lookup={r['event_id']:r for r in rows}
            for event in capture['events']:
                lookup[event['event_id']]={k:event.get(k,lookup.get(event['event_id'],{}).get(k,'')) for k in columns}
            write_rows(path,sorted(lookup.values(),key=lambda r:(r['event_date'],r['event_id'])),columns)

def training_keys(engine,sex):
    from collections import Counter
    rel='data/processed/mens_training_rows_v3_bayes_smoothing_candidate.csv' if sex=='men' else 'output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv'
    path=Path(engine)/rel
    if not path.exists():return Counter()
    return Counter((r['fight_id'],r.get('fighter_a_id',r.get('fighter_a')),r.get('fighter_b_id',r.get('fighter_b'))) for r in read_rows(path) if canonical(r.get('fighter_a_won')) in ('0','1'))

def apply(root,identifier,progress=None,cancel=None,runner=None,validator=None):
    from analyzer_maintenance import ENGINE,maintenance_lock,promote,rollback,rebuild_engine,validate_engine,data_files,training_count
    from analyzer_runtime import run_logged_process
    root=Path(root).resolve();notify=progress or (lambda **kw:None)
    def run(cmd,cwd,log):
        if runner:return runner(cmd,cwd,log)
        return run_logged_process(cmd,cwd,log,progress=notify,cancel=cancel)
    with operation_lock(root,'apply_corrections'):
        value=validate_preview(root,identifier)
        if not value['changes']:return dict(status='no_changes',preview=value)
        transaction=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
        txn=root/'.runtime/transactions'/transaction;stage=txn/'stage';logs=txn/'logs';logs.mkdir(parents=True)
        targets=[sex for sex in ('men','women') if any(c['sex']==sex for c in value['changes'])]
        required=sum(p.stat().st_size for sex in targets for p in (root/ENGINE[sex]).rglob('*') if p.is_file() and not any(part in ('cache','__pycache__','_update_manifests') or part.startswith('_backup') for part in p.parts))*3+64*1024**2
        if shutil.disk_usage(root).free<required:raise MaintenanceError('insufficient_space','Not enough free disk space','Free space on the app drive before applying corrections.',operation='apply_corrections')
        journal=dict(id=transaction,targets=targets,pid=os.getpid(),status='staging',kind='corrections',promotions=[],summary={})
        with maintenance_lock(root,transaction):
            try:
                stage.mkdir();shutil.copy2(root/'dataset_manifest.json',stage/'dataset_manifest.json')
                for helper in ('analyzer_protocol.py','analyzer_errors.py'):shutil.copy2(root/helper,stage/helper)
                files=[]
                for sex in ('men','women'):
                    changes=[c for c in value['changes'] if c['sex']==sex]
                    if not changes:continue
                    check_cancel(cancel)
                    shutil.copytree(root/ENGINE[sex],stage/ENGINE[sex],ignore=shutil.ignore_patterns('.venv','__pycache__','cache','_backup*','_update_manifests'))
                    before_keys=training_keys(root/ENGINE[sex],sex)
                    before=sum(before_keys.values())
                    apply_source(stage,sex,value['captures'][sex],value['changes'])
                    if sex=='women':
                        run([python_executable(),str(root/'analyzer_corrections.py'),'rebuild-women',str(stage/ENGINE[sex]),str(root/ENGINE[sex])],stage/ENGINE[sex],logs/'women-advanced.log')
                    rebuild_engine(stage,sex,logs,run,notify)
                    (validator or validate_engine)(stage,sex,logs,run)
                    after=training_count(stage/ENGINE[sex],sex)
                    after_keys=training_keys(stage/ENGINE[sex],sex)
                    journal['summary'][sex]=dict(corrected_fights=len({c['fight_id'] for c in changes if c['kind']=='corrected'}),added_fights=len({c['fight_id'] for c in changes if c['kind']=='added'}),binary_training_rows_added=sum((after_keys-before_keys).values()),binary_training_rows_removed=sum((before_keys-after_keys).values()),binary_training_rows_net=after-before,changed=True)
                    for file in (stage/ENGINE[sex]).rglob('*'):
                        relative=file.relative_to(stage/ENGINE[sex])
                        if file.is_file() and file.suffix in ('.csv','.json') and (relative.parts[0]=='data' or relative.parts[0].startswith('output')):files.append(file.relative_to(stage).as_posix())
                from analyzer_support import dataset_state,data_health
                combined={e['path']:e for e in dataset_state(root)['files']}
                for sex in journal['summary']:
                    for e in data_health(stage,False,(sex,)):
                        path=stage/e['path'];combined[e['path']]=dict(path=e['path'],sha256=digest(path),size_bytes=path.stat().st_size,rows=e['rows'],columns=e['columns'],latest_date=e['latest_date'])
                atomic_json(stage/'.runtime/local_dataset_state.json',dict(files=list(combined.values()),transaction=transaction,validated_at=utc_now()))
                files.append('.runtime/local_dataset_state.json');check_cancel(cancel)
                notify(stage='committing',message='Installing validated corrections',cancellable=False)
                promote(root,stage,txn,journal,sorted(files))
                atomic_json(txn/'correction-preview.json',value)
                if stage.resolve().is_relative_to(txn.resolve()):shutil.rmtree(stage)
                return dict(status='committed',transaction=transaction,summary=journal['summary'])
            except BaseException:
                import traceback
                (txn/'failure.log').write_text(traceback.format_exc(),encoding='utf-8')
                from analyzer_maintenance import recover_transaction
                recover_transaction(root,txn,journal)
                raise

def rebuild_women(stage,original):
    """Rebuild advanced rows from the earliest changed source date onwards."""
    import pandas as pd
    stage=Path(stage);original=Path(original)
    rel='output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv'
    old=read_rows(original/rel);new=read_rows(stage/rel)
    old_groups={};new_groups={}
    for r in old:old_groups.setdefault(r['fight_id'],[]).append(r)
    for r in new:new_groups.setdefault(r['fight_id'],[]).append(r)
    ids={fid for fid in set(old_groups)|set(new_groups) if old_groups.get(fid)!=new_groups.get(fid)}
    # Source ordering alone is not a correction.
    ids={fid for fid in ids if fingerprint(sorted(old_groups.get(fid,[]),key=lambda r:r['fighter']))!=fingerprint(sorted(new_groups.get(fid,[]),key=lambda r:r['fighter']))}
    if not ids:return
    earliest=min(r['event_date'][:10] for r in old+new if r['fight_id'] in ids)
    sys.path.insert(0,str(stage));spec=importlib.util.spec_from_file_location('women_rebuild_updater',stage/'update_ufc_womens_dataset_incremental.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    advanced_path=stage/'output_advanced_features_sig_fixed/ufc_womens_model_training_rows_advanced_sig_fixed.csv'
    advanced=pd.read_csv(advanced_path);stats=pd.read_csv(stage/rel);stats['event_date']=pd.to_datetime(stats['event_date'])
    predictor=module.import_predictor(str(stage/'predict_matchup_advanced.py'))
    # One dated Elo traversal per event, shared by bouts on the same date.
    original_elo=module.get_elo_state;states={}
    def elo(p,s,date):
        k=str(date)
        if k not in states:states[k]=original_elo(p,s,date)
        return states[k]
    module.get_elo_state=elo
    fresh=module.build_new_training_rows(predictor,advanced,stats,stage/'output_quality_fixed/ufc_womens_fighter_profiles.csv',stats[stats['event_date']>=pd.Timestamp(earliest)])
    kept=advanced[pd.to_datetime(advanced['event_date'])<pd.Timestamp(earliest)]
    pd.concat([kept,fresh],ignore_index=True).sort_values(['event_date','fight_id','fighter_a','fighter_b']).to_csv(advanced_path,index=False)

if __name__=='__main__':
    if sys.argv[1]=='capture':
        from analyzer_protocol import progress
        try:atomic_json(sys.argv[5],capture_source(Path(__file__).resolve().parent,sys.argv[2],sys.argv[3],sys.argv[4],progress))
        except Exception as exc:
            from analyzer_protocol import source_failure
            source_failure(exc)
            raise
    elif sys.argv[1]=='rebuild-women':rebuild_women(*sys.argv[2:])
