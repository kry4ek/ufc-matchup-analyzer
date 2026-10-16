"""Frozen, descriptive bout evidence. Does not supply model features."""
from __future__ import annotations
from collections import Counter
import csv
import datetime as dt
import math
from pathlib import Path
from analyzer_history import fingerprint

SIDES = ('fighter_a', 'fighter_b')
UNRECORDED = 'Not recorded in this saved analysis. Refresh to capture these details.'
COUNTS = ('sig_landed','sig_attempted','total_landed','total_attempted','knockdowns',
          'td_landed','td_attempted','sub_attempts','control_seconds')
METRICS = (
    ('sig_per_min','Significant strikes landed / min','per_min','sig_landed','minutes',1),
    ('absorbed_per_min','Significant strikes absorbed / min','per_min','opponent_sig_landed','minutes',1),
    ('sig_accuracy','Significant-strike accuracy','percent','sig_landed','sig_attempted',1),
    ('td_per_15','Takedowns / 15 min','per_15_min','td_landed','minutes',15),
    ('td_accuracy','Takedown accuracy','percent','td_landed','td_attempted',1),
    ('td_defense','Takedown defense','percent','opponent_td_landed','opponent_td_attempted',1),
    ('control_share','Control share','percent','control_seconds','duration_seconds',1),
)

def number(value):
    try:
        if isinstance(value,bool) or value is None or str(value).strip() in ('','--','N/A'): return None
        result=float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError,ValueError): return None

class FightSource:
    """Request-local source reader; retain only the selected fighters' bouts."""
    def __init__(self, root, sex, identities):
        self.root=Path(root);self.sex=sex;self.identities=identities;self.cache={};self.hashes={}
        self.wanted={str(v[1]) for v in identities.values() if v[1]}
        self.fight_ids=None

    def records(self,path):
        from analyzer_support import digest
        path=Path(path)
        if path not in self.cache:
            before=digest(path)
            with path.open(encoding='utf-8-sig',newline='') as stream:
                if path.name=='fight_stats.csv':
                    fights=self.records(path.with_name('fights.csv'))
                    wanted={r['fight_id'] for r in fights if self.wanted.intersection((r.get('fighter_red_id'),r.get('fighter_blue_id')))}
                    rows=[r for r in csv.DictReader(stream) if r.get('fight_id') in wanted]
                else: rows=list(csv.DictReader(stream))
            if digest(path)!=before: raise ValueError('Fight data changed while reading. Retry after maintenance completes.')
            self.hashes[path]=before;self.cache[path]=rows
        return self.cache[path]

    def verify(self):
        from analyzer_support import digest
        if any(digest(path)!=value for path,value in self.hashes.items()):
            raise ValueError('Fight data changed during analysis. Retry with one dataset snapshot.')

def _stats(row, sex):
    mapping = dict(sig_landed='significant_strikes_landed',sig_attempted='significant_strikes_attempted',
        total_landed='total_strikes_landed',total_attempted='total_strikes_attempted',knockdowns='knockdowns',
        td_landed='takedowns_landed',td_attempted='takedowns_attempted',sub_attempts='submission_attempts',control_seconds='control_time_seconds')
    if sex=='women': mapping.update(sig_landed='sig_str_landed_repaired',sig_attempted='sig_str_attempted_repaired',
        total_landed='total_str_landed',total_attempted='total_str_attempted',knockdowns='kd_landed',
        td_landed='td_landed',td_attempted='td_attempted',sub_attempts='sub_attempts')
    values={k:number(row.get(v)) for k,v in mapping.items()}
    issues={k:'Missing or invalid source value' for k,v in values.items() if v is None}
    for prefix in ('sig','total','td'):
        a,b=prefix+'_landed',prefix+'_attempted'
        if values[a] is not None and values[b] is not None and values[a]>values[b]:
            values[a]=values[b]=None;issues[a]=issues[b]='Landed exceeds attempted'
    return values,issues

def _duration(row):
    seconds=number(row.get('elapsed_seconds'))
    if seconds is None:
        minutes=number(row.get('minutes'));seconds=minutes*60 if minutes is not None else None
    return seconds if seconds and seconds>0 else None

def normalize_bout(meta, rows, sex, fighter_id):
    def identifier(r): return str(r.get('fighter_id') or r.get('profile_url','').rstrip('/').rsplit('/',1)[-1])
    own=[r for r in rows if identifier(r)==str(fighter_id)]
    other=[r for r in rows if identifier(r)==str(meta.get('opponent_id'))]
    unique=len(own)==1 and bool(fighter_id)
    paired=unique and len(other)==1 and bool(meta.get('opponent_id')) and meta['opponent_id']!=fighter_id
    values,issues=_stats(own[0] if unique else {},sex)
    opponent,opponent_issues=_stats(other[0] if paired else {},sex)
    duration=_duration(own[0]) if unique else None
    if paired and _duration(other[0])!=duration:
        duration=None;issues['duration_seconds']='Paired source durations disagree'
    for data,notes in ((values,issues),(opponent,opponent_issues)):
        if duration and data['control_seconds'] is not None and data['control_seconds']>duration:
            data['control_seconds']=None;notes['control_seconds']='Control exceeds recorded duration'
    return dict(**meta,fighter_id=str(fighter_id or ''),stats=values,opponent_stats=opponent,
        duration_seconds=duration,minutes=duration/60 if duration else None,
        issues=issues,opponent_issues=opponent_issues,paired=paired,
        opponent_prebout_elo=None,elo_note='Dated pre-bout opponent rating unavailable.',
        source_fingerprint=fingerprint(rows),
        pairing_note='Paired by recorded identities.' if paired else 'Unambiguous paired identities unavailable; opponent statistics withheld.')

def aggregate(bouts):
    records=[]
    for metric_id,label,unit,numerator,denominator,factor in METRICS:
        total=denom=0.;eligible=0
        for bout in bouts:
            values=bout['stats'];opp=bout['opponent_stats']
            n=opp.get(numerator[9:]) if numerator.startswith('opponent_') else values.get(numerator)
            d=opp.get(denominator[9:]) if denominator.startswith('opponent_') else bout.get(denominator) if denominator in ('minutes','duration_seconds') else values.get(denominator)
            if n is None or d is None: continue
            total+=n;denom+=d;eligible+=1
        value=factor*total/denom if denom>0 else None
        if value is not None and metric_id=='td_defense': value=1-value
        records.append(dict(id=metric_id,semantic_version=1,label=label,unit=unit,value=value,
            numerator=total,denominator=denom,denominator_unit=denominator,
            eligible_bouts=eligible,missing_bouts=len(bouts)-eligible,
            unavailable_reason='0 recorded attempts or duration' if denom==0 else None))
    dates=[r['event_date'] for r in bouts]
    return dict(bout_count=len(bouts),results=dict(Counter(r.get('result','unknown') for r in bouts)),
        date_from=min(dates) if dates else None,date_through=max(dates) if dates else None,metrics=records,
        opponent_context=[dict(opponent=r['opponent'],event_date=r['event_date'],prebout_elo=r['opponent_prebout_elo']) for r in bouts[:5]])

def capture(source, history, visual_evidence=None):
    from analyzer_fight_history import identity_id
    path=source.root/('mens_ufc_model/data/raw/ufcstats_men/fight_stats.csv' if source.sex=='men' else 'womens_ufc_model/output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv')
    by_fight={}
    for r in source.records(path):by_fight.setdefault(r.get('fight_id'),[]).append(r)
    details=dict(schema=1,history_cutoff=history['history_cutoff'])
    form=dict(schema=1,history_cutoff=history['history_cutoff'],scope='All recorded UFC divisions',
        note='UFC career includes the selected recent window. Same-day ties use fight ID; intraday order is unavailable.')
    for side in SIDES:
        fighter_id=source.identities[side][1]
        bouts=[normalize_bout(meta,by_fight.get(meta['fight_id'],[]),source.sex,fighter_id) for meta in history[side]]
        points={(p['fight_id'],p['date']):p for p in (visual_evidence or {}).get('elo',{}).get(side,[])}
        for bout in bouts:
            point=points.get((bout['fight_id'],bout['event_date']),{})
            rating=number(point.get('opponent_overall'))
            if rating is not None:
                bout['opponent_prebout_elo']=rating
                bout['elo_note']=f'Opponent overall Elo before this bout: {rating:.2f}. Engine state, not an official ranking.'
        details[side]=dict(fighter_id=str(fighter_id or ''),bouts=bouts[:5])
        form[side]=dict(fighter_id=str(fighter_id or ''),windows={str(n):aggregate(bouts[:n]) for n in (3,5)})
        form[side]['windows']['career']=aggregate(bouts)
    source.verify()
    provenance=fingerprint({str(p.relative_to(source.root)):v for p,v in source.hashes.items()})
    details['source_fingerprint']=form['source_fingerprint']=provenance
    return dict(bout_details=details,recent_form=form)

def display_value(value,unit=''):
    if value is None:return 'N/A'
    return f'{value:.1%}' if unit=='percent' else f'{value:.2f}'

def results_text(results):
    return ' / '.join(label+' '+str(results.get(name,0)+(results.get('no_contest',0) if name=='nc' else 0)) for name,label in (('win','W'),('loss','L'),('draw','D'),('nc','NC')))

def form_rows(payload,side,window='5'):
    record=payload.get('recent_form',{}).get(side,{}).get('windows',{})
    recent,career=record.get(str(window)),record.get('career')
    if not recent or not career:return []
    rows=[]
    for a,b in zip(recent['metrics'],career['metrics']):
        delta=None if a['value'] is None or b['value'] is None else a['value']-b['value']
        delta_text='N/A' if delta is None else f'{delta*100:+.1f} pp' if a['unit']=='percent' else f'{delta:+.2f}'
        def support(r):
            unit='minutes' if r['denominator_unit']=='minutes' else 'seconds' if r['denominator_unit']=='duration_seconds' else 'attempts'
            return f"{r['eligible_bouts']} bouts; {r['denominator']:.1f} {unit}; {r['missing_bouts']} missing"
        rows.append((a['label'],display_value(a['value'],a['unit']),display_value(b['value'],b['unit']),delta_text,support(a)+' / '+support(b)))
    return rows

def bout_text(bout):
    lines=[f"{bout['event_date']} · {bout['opponent']} · {bout.get('result','')} · {bout.get('method','')}",
        f"Duration: {display_value(bout['duration_seconds'])} seconds. {bout['pairing_note']}"]
    labels=('Significant strikes landed','Significant strikes attempted','Total strikes landed','Total strikes attempted','Knockdowns','Takedowns landed','Takedowns attempted','Submission attempts','Control (seconds)')
    def count(v):return 'N/A' if v is None else f'{v:g}'
    lines.append('Selected fighter / opponent')
    for name,label in zip(COUNTS,labels):
        lines.append(label+': '+count(bout['stats'][name])+' / '+count(bout['opponent_stats'][name]))
    notes=sorted(set(bout.get('issues',{}).values())|set(bout.get('opponent_issues',{}).values()))
    return '\n'.join(lines+[bout['elo_note']]+notes)

def format_context(payload):
    if 'recent_form' not in payload:return ''
    lines=['RECENT FORM VERSUS UFC CAREER',payload['recent_form']['scope'],payload['recent_form']['note']]
    for side in SIDES:
        lines+=['',payload[side]]
        for window in ('3','5'):
            data=payload['recent_form'][side]['windows'][window]
            lines.append(f"Last {window} (actual {data['bout_count']}) / UFC career · {results_text(data['results'])}")
            lines+=[' | '.join(row) for row in form_rows(payload,side,window)]
        for bout in payload.get('bout_details',{}).get(side,{}).get('bouts',[]):lines+=['',bout_text(bout)]
    return '\n'.join(lines)+'\n'

def _validate_context(payload):
    """Bound all new captured evidence, including imported JSON."""
    for name in ('bout_details','recent_form'):
        if name not in payload:continue
        block=payload[name]
        if not isinstance(block,dict) or block.get('schema')!=1:raise ValueError('Unsupported '+name+' schema')
        dt.date.fromisoformat(block['history_cutoff'])
        if payload.get('fight_date') and block['history_cutoff']!=payload['fight_date']:raise ValueError('Mismatched descriptive cutoff')
        for side in SIDES:
            record=block[side]
            if not isinstance(record.get('fighter_id'),str):raise ValueError('Invalid captured identity')
            if name=='bout_details':
                bouts=record['bouts']
                if not isinstance(bouts,list) or len(bouts)>5:raise ValueError('Too many bout details')
                for bout in bouts:
                    if dt.date.fromisoformat(bout['event_date'])>=dt.date.fromisoformat(block['history_cutoff']):raise ValueError('Future bout detail')
                    if bout['fighter_id']!=record['fighter_id']:raise ValueError('Mismatched bout identity')
                    duration=bout.get('duration_seconds')
                    if duration is not None and (type(duration) not in (int,float) or number(duration) is None or duration<=0):raise ValueError('Invalid bout duration')
                    for field in ('stats','opponent_stats'):
                        if set(bout[field])!=set(COUNTS):raise ValueError('Invalid bout stat fields')
                        if any(v is not None and (type(v) not in (int,float) or number(v) is None) for v in bout[field].values()):raise ValueError('Invalid bout statistic')
                        for prefix in ('sig','total','td'):
                            landed=bout[field][prefix+'_landed'];attempts=bout[field][prefix+'_attempted']
                            if landed is not None and attempts is not None and landed>attempts:raise ValueError('Invalid landed/attempted pair')
                        if duration and bout[field]['control_seconds'] is not None and bout[field]['control_seconds']>duration:raise ValueError('Invalid control duration')
            else:
                if set(record['windows'])!={'3','5','career'}:raise ValueError('Invalid recent windows')
                for window,value in record['windows'].items():
                    count=value['bout_count']
                    if type(count)!=int or not 0<=count<=1000 or (window!='career' and count>int(window)):raise ValueError('Invalid window count')
                    if len(value['metrics'])!=len(METRICS):raise ValueError('Invalid recent metrics')
                    if not isinstance(value.get('results'),dict) or any(type(v)!=int or v<0 for v in value['results'].values()) or sum(value['results'].values())!=count:raise ValueError('Invalid result accounting')
                    if not isinstance(value.get('opponent_context'),list) or len(value['opponent_context'])>5:raise ValueError('Invalid opponent context')
                    for metric,spec in zip(value['metrics'],METRICS):
                        if metric['id']!=spec[0] or metric['unit']!=spec[2] or metric['semantic_version']!=1:raise ValueError('Invalid metric contract')
                        for field in ('numerator','denominator','eligible_bouts','missing_bouts'):
                            if type(metric[field]) not in (int,float) or number(metric[field]) is None:raise ValueError('Invalid metric support')
                        if any(type(metric[k])!=int for k in ('eligible_bouts','missing_bouts')):raise ValueError('Noninteger bout support')
                        if metric['eligible_bouts']+metric['missing_bouts']!=count:raise ValueError('Invalid support accounting')
                        if metric['value'] is not None and (type(metric['value']) not in (int,float) or number(metric['value']) is None):raise ValueError('Invalid metric value')
                        if metric['unit']=='percent' and metric['value'] is not None and metric['value']>1:raise ValueError('Invalid percentage')

def validate_context(payload):
    try:_validate_context(payload)
    except (KeyError,TypeError,AttributeError,OverflowError) as exc:
        raise ValueError('Invalid captured bout/recent-form structure') from exc
