"""Read-only recent UFC history, frozen into each analysis payload."""
from __future__ import annotations
import csv
import datetime as dt
from pathlib import Path
from analyzer_catalog import key

RESULT_LABELS = {'win':'Win','loss':'Loss','draw':'Draw','nc':'No contest','no_contest':'No contest'}
OLD_HISTORY_MESSAGE = 'Recent fights were not saved with this analysis. Recalculate to include them.'

def records(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        yield from csv.DictReader(stream)

def identity_id(url):
    return (url or '').rstrip('/').rsplit('/',1)[-1]

def recent_fights(root, sex, fighter_a, fighter_b, fight_date, limit=5, source=None):
    dt.date.fromisoformat(fight_date)
    read = source.records if source else records
    identities = {'fighter_a':fighter_a,'fighter_b':fighter_b}
    histories = {side:{} for side in identities}
    root = Path(root)
    if sex == 'men':
        base = root/'mens_ufc_model/data/raw/ufcstats_men'
        names = {r['fighter_id']:r.get('fighter_name','') for r in read(base/'fighters.csv')}
        events = {r['event_id']:r.get('event_name','') for r in read(base/'events.csv')}
        wanted = {str(identity[1]) for identity in identities.values()}
        stats = {}
        for row in read(base/'fight_stats.csv'):
            if row.get('fighter_name') and not names.get(row.get('fighter_id')):names[row.get('fighter_id')]=row['fighter_name']
            if row.get('fighter_id') in wanted:stats[(row['fight_id'],row['fighter_id'])] = row
        for row in read(base/'fights.csv'):
            date = row.get('event_date','')[:10]
            if not date or date >= fight_date:continue
            for side, (name, fighter_id) in identities.items():
                fighter_id = str(fighter_id)
                pair = (row.get('fighter_red_id'),row.get('fighter_blue_id'))
                if fighter_id not in pair:continue
                opponent_id = pair[1] if pair[0] == fighter_id else pair[0]
                result = row.get('result','')
                result = ('win' if row.get('winner_id') == fighter_id else 'loss') if result == 'win_loss' else result
                stat = stats.get((row['fight_id'],fighter_id),{})
                histories[side][row['fight_id']] = dict(fight_id=row['fight_id'],event_date=date,event_name=events.get(row.get('event_id'),''),opponent=stat.get('opponent_name') or names.get(opponent_id) or opponent_id or 'N/A',opponent_id=opponent_id,division=row.get('weight_class',''),result=result,method=row.get('method',''),round=row.get('round',''),time=row.get('time',''))
    elif sex == 'women':
        path = root/'womens_ufc_model/output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv'
        source_rows = list(read(path))
        opponents = {}
        for row in source_rows:
            identifier=identity_id(row.get('profile_url'))
            if identifier:opponents.setdefault((row.get('fight_id'),key(row.get('fighter',''))),set()).add(identifier)
        for row in source_rows:
            date = row.get('event_date','')[:10]
            if not date or date >= fight_date:continue
            for side, (name, fighter_id) in identities.items():
                row_id = identity_id(row.get('profile_url'))
                if fighter_id and row_id:
                    if row_id != str(fighter_id):continue
                elif key(row.get('fighter','')) != key(name):continue
                opponent_ids=opponents.get((row['fight_id'],key(row.get('opponent',''))),set())
                opponent_id=next(iter(opponent_ids)) if len(opponent_ids)==1 else ''
                histories[side].setdefault(row['fight_id'],dict(fight_id=row['fight_id'],event_date=date,event_name=row.get('event_name',''),opponent=row.get('opponent') or 'N/A',opponent_id=opponent_id,division=row.get('division',''),result=row.get('result',''),method=row.get('method',''),round=row.get('round',''),time=row.get('time','')))
    else:raise ValueError('Unknown fighter history category')
    return dict(schema_version=1,history_cutoff=fight_date,**{side:sorted(rows.values(),key=lambda r:(r['event_date'],r['fight_id']),reverse=True)[:limit] for side,rows in histories.items()})

def fight_evidence(root, sex, fighter_a, fighter_b, fight_date, source=None, history=None):
    from analyzer_history import fingerprint
    import copy
    history=copy.deepcopy(history) if history is not None else recent_fights(root,sex,fighter_a,fighter_b,fight_date,limit=None,source=source)
    path=Path(root)/('mens_ufc_model/data/raw/ufcstats_men/fight_stats.csv' if sex=='men' else 'womens_ufc_model/output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv')
    stats={}
    for row in (source.records(path) if source else records(path)):stats.setdefault(row.get('fight_id'),[]).append(row)
    for side in ('fighter_a','fighter_b'):
        for row in history[side]:
            row['content_fingerprint']=fingerprint(dict(metadata=row,stats=sorted(stats.get(row['fight_id'],[]),key=lambda r:str(r.get('fighter_id',r.get('profile_url',r.get('fighter','')))))))
    return history

def display_row(row):
    return tuple(str(row.get(field) or 'N/A') if field != 'result' else RESULT_LABELS.get(row.get(field),'N/A') for field in ('event_date','opponent','result','division','method'))

def format_recent_fights(payload):
    history = payload.get('recent_fights')
    if not history:return OLD_HISTORY_MESSAGE+'\n'
    lines = ['RECENT UFC FIGHTS','Last five recorded UFC bouts before '+history['history_cutoff'],
             'All recorded divisions; dates use the installed source snapshot, including later corrections.']
    for side in ('fighter_a','fighter_b'):
        rows = history.get(side,[])
        lines += ['',payload[side]+f' — {len(rows)} recorded bout'+('s' if len(rows)!=1 else '')]
        if not rows:lines.append('No eligible recorded UFC fights before this date.')
        for row in rows:
            lines.append(' | '.join(display_row(row)))
            lines.append('  Event: '+str(row.get('event_name') or 'N/A')+'; round: '+str(row.get('round') or 'N/A')+'; time: '+str(row.get('time') or 'N/A'))
    return '\n'.join(lines)+'\n'
