"""Parent-owned, resumable chronological evaluation of the exported app policies."""
from __future__ import annotations
import argparse
import contextlib
import csv
import datetime as dt
import importlib.util
import json
import math
from pathlib import Path
import random
import sys

PROTOCOL='v06-frozen-20261013-1'

def scores(rows,field='probability'):
    if not rows:return {}
    count=len(rows);p=[r[field] for r in rows];y=[r['outcome'] for r in rows]
    clipped=[max(1e-12,min(1-1e-12,v)) for v in p]
    return dict(accuracy=sum((v>=.5)==bool(label) for v,label in zip(p,y))/count,
                brier=sum((v-label)**2 for v,label in zip(p,y))/count,
                log_loss=-sum(label*math.log(v)+(1-label)*math.log(1-v) for v,label in zip(clipped,y))/count)

def calibration(rows):
    bins=[]
    for i in range(5):
        group=[r for r in rows if i/5<=r['probability']<(i+1)/5 or i==4 and r['probability']==1]
        bins.append(dict(low=i/5,high=(i+1)/5,count=len(group),mean_probability=sum(r['probability'] for r in group)/len(group) if group else None,
                         observed_rate=sum(r['outcome'] for r in group)/len(group) if group else None))
    return bins

def uncertainty(rows):
    events=sorted({r['event_date'] for r in rows})
    if len(events)<5:return dict(status='Unavailable: fewer than five independent event/date clusters',clusters=len(events))
    rng=random.Random(42);samples=[]
    for _ in range(500):
        selected=rng.choices(events,k=len(events));sample=[r for date in selected for r in rows if r['event_date']==date];samples.append(scores(sample)['brier'])
    samples.sort();return dict(method='500 event/date bootstrap replicates; seed 42',brier_low=samples[12],brier_high=samples[487],clusters=len(events))

def cases(root,start,end):
    from analyzer_catalog import MEN_DIVISIONS,WOMEN_DIVISIONS
    groups={};excluded={'men':0,'women':0}
    paths={'men':root/'mens_ufc_model/data/raw/ufcstats_men/fights.csv',
           'women':root/'womens_ufc_model/output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv'}
    with (root/'mens_ufc_model/data/raw/ufcstats_men/fighters.csv').open(encoding='utf-8-sig',newline='') as stream:names={r['fighter_id']:r['fighter_name'] for r in csv.DictReader(stream)}
    for sex,path in paths.items():
        with path.open(encoding='utf-8-sig',newline='') as stream:
            for r in csv.DictReader(stream):
                date=r['event_date'][:10]
                if start<=date<=end:groups.setdefault((sex,r['fight_id']),[]).append(r)
    result=[]
    for (sex,identifier),rows in groups.items():
        r=rows[0];date=r['event_date'][:10]
        if sex=='men':
            division=r.get('weight_class');ids=sorted((r.get('fighter_red_id',''),r.get('fighter_blue_id','')))
            if r.get('result')!='win_loss' or division not in MEN_DIVISIONS or not all(ids) or not r.get('winner_id'):
                excluded[sex]+=1;continue
            a,b=ids;fighter_a=names.get(a);fighter_b=names.get(b);outcome=int(r['winner_id']==a)
        else:
            division=r.get('division','').replace("Women's ",'')
            if len(rows)!=2 or division not in WOMEN_DIVISIONS or any(x.get('won') not in ('0','1','0.0','1.0') for x in rows):
                excluded[sex]+=1;continue
            ordered=sorted(rows,key=lambda x:x['profile_url']);ra,rb=ordered
            a=ra['profile_url'].rstrip('/').rsplit('/',1)[-1];b=rb['profile_url'].rstrip('/').rsplit('/',1)[-1]
            fighter_a=ra['fighter'];fighter_b=rb['fighter'];outcome=int(float(ra['won']))
        result.append(dict(sex=sex,fight_id=identifier,event_date=date,division=division,fighter_a=fighter_a,fighter_b=fighter_b,fighter_a_id=a,fighter_b_id=b,outcome=outcome))
    return sorted(result,key=lambda r:(r['event_date'],r['sex'],r['fight_id'])),excluded

def audit_cv(root,end):
    import pandas as pd
    from sklearn.model_selection import StratifiedKFold
    path=root/'womens_ufc_model/output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv'
    data=pd.read_csv(path);data=data[(data['event_date']<end)&data['fighter_a_won'].isin([0,1])].reset_index(drop=True)
    overlap=0;folds=[]
    for train,test in StratifiedKFold(n_splits=5,shuffle=True,random_state=42).split(data,data['fighter_a_won']):
        train_ids=set(data.iloc[train]['fight_id']);test_ids=set(data.iloc[test]['fight_id']);count=len(train_ids&test_ids)
        overlap+=count;folds.append(count)
    return dict(status='FAIL' if overlap else 'PASS',overlapping_bout_counts_by_fold=folds,
                rows=len(data),unique_bouts=data['fight_id'].nunique(),
                finding='Existing women ensemble uses shuffled, ungrouped folds; mirrored bouts cross training/validation folds. Internal calibration also uses ungrouped stratification. Outer evaluation remains strictly chronological; internal CV is not a clean accuracy estimate.')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--app-root',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--start',default='2026-09-19');parser.add_argument('--end',default='2026-09-26');parser.add_argument('--holdout-start',default='2026-09-26');args=parser.parse_args()
    root=args.app_root.resolve();sys.path.insert(0,str(root))
    from analyzer_support import atomic_json,digest,manifest
    from analyzer_history import fingerprint
    from analyzer_validation import format_validation
    from ufc_matchup_analyzer import parser as app_parser,predict
    for date in (args.start,args.end,args.holdout_start):dt.date.fromisoformat(date)
    if not args.start<args.holdout_start<=args.end:raise ValueError('Development must precede holdout')
    args.out.mkdir(parents=True,exist_ok=True)
    planned,excluded=cases(root,args.start,args.end)
    dataset_hashes={item['path']:digest(root/item['path']) for item in manifest()['files']}
    code={str(p.relative_to(root)).replace('\\','/'):digest(p) for d in ('mens_ufc_model','womens_ufc_model') for p in (root/d).rglob('*.py') if '__pycache__' not in p.parts}
    protocol=dict(version=PROTOCOL,start=args.start,end=args.end,holdout_start=args.holdout_start,datasets=dataset_hashes,code=code,
                  scoring='One decisive bout, stable ID order; no same-date training; 5 fixed equal-width calibration bins; log-loss clip 1e-12; no tuning.',
                  baselines='50/50 and unmodified pre-fight Elo expected score; no fit to held-out outcomes.')
    signature=fingerprint(protocol);checkpoint=args.out/'checkpoint.json'
    state=dict(signature=signature,protocol=protocol,planned=planned,rows=[],failures=[])
    if checkpoint.exists():
        state=json.loads(checkpoint.read_text(encoding='utf-8'))
        if state['signature']!=signature:raise ValueError('Evaluation inputs changed; use a new output directory.')
    else:atomic_json(checkpoint,state)
    audit=audit_cv(root,args.holdout_start);atomic_json(args.out/'cv-audit.json',audit)
    completed={r['sex']+'/'+r['fight_id'] for r in state['rows']+state['failures']}
    # Model settings/protocol frozen before these holdout outcomes are scored.
    for case in planned:
        identity=case['sex']+'/'+case['fight_id']
        if identity in completed:continue
        log=args.out/(case['sex']+'-'+case['fight_id']+'.log')
        try:
            cli=app_parser().parse_args(['predict',case['sex'],'--fighter-a',case['fighter_a'],'--fighter-b',case['fighter_b'],'--fighter-a-id',case['fighter_a_id'],'--fighter-b-id',case['fighter_b_id'],'--division',case['division'],'--fight-date',case['event_date'],'--workers','1'])
            with log.open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream):payload=predict(cli,root)
            latest=payload.get('actual_max_training_event_date_used') or payload.get('latest_training_event_date')
            if not latest or str(latest)[:10]>=case['event_date']:raise ValueError('Training cutoff audit failed')
            snapshots=[payload.get('fighter_'+side+'_comparison',{}) for side in ('a','b')]
            elo=[float(s.get('pre_elo',s.get('elo_before',1500))) for s in snapshots]
            row=dict(case,probability=payload['fighter_a_win_probability'],fifty_fifty=.5,
                     elo_baseline=1/(1+10**((elo[1]-elo[0])/400)),latest_training_date=str(latest),
                     partition='holdout' if case['event_date']>=args.holdout_start else 'development')
            state['rows'].append(row)
        except (Exception,SystemExit) as exc:state['failures'].append(dict(case,error=str(exc)))
        atomic_json(checkpoint,state);print(identity,'scored',len(state['rows']),'failed',len(state['failures']),flush=True)
    report=dict(schema=1,status='LIMITED_RETROSPECTIVE_EVALUATION',protocol_version=PROTOCOL,
                period=dict(start=args.start,end=args.end,holdout_start=args.holdout_start),datasets=dataset_hashes,code=code,cv_audit=audit,
                limitations=['Small two-event/date evaluation; not evidence of general accuracy or profitability.',audit['finding'],
                             'No algorithm tuning or calibration changes. Corrected snapshot does not reconstruct historical publication state.',
                             'Mirrored-fold defect needs a separately validated parent model correction; this report does not clear that methodological gate.'],models={})
    for sex,version in (('men','v3_bayes_smoothed'),('women','v1_current_ensemble')):
        rows=[r for r in state['rows'] if r['sex']==sex];failed=[r for r in state['failures'] if r['sex']==sex];total=sum(r['sex']==sex for r in planned)
        holdout=[r for r in rows if r['partition']=='holdout'];development=[r for r in rows if r['partition']=='development']
        report['models'][sex]=dict(model_version=version,evaluated=len(rows),excluded=excluded[sex],failed=len(failed),remaining=total-len(rows)-len(failed),
                                 scores={name:scores(holdout,field) for name,field in [('Model holdout','probability'),('50/50 holdout','fifty_fifty'),('Elo holdout','elo_baseline')]},
                                 development_scores=scores(development),calibration=calibration(holdout),uncertainty=uncertainty(holdout),
                                 event_dates=sorted({r['event_date'] for r in rows}),failures=failed)
    if state['failures']:report['status']='INCOMPLETE_EVALUATION_WITH_FAILURES'
    report['integrity']=fingerprint(report);atomic_json(args.out/'model_validation.json',report)
    (args.out/'MODEL_VALIDATION.md').write_text('# Dated model evaluation\n\n'+format_validation(report)+'\n',encoding='utf-8')
if __name__=='__main__':main()
