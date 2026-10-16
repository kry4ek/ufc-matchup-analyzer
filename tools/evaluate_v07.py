"""Parent-owned, resumable event-date evaluation with one outcome per bout.

Scores stored prefight rows. Live/stored feature parity is a separate promotion
gate; this evaluator must not be described as an end-to-end app evaluation.
"""
from __future__ import annotations
import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def signature(value): return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    os.replace(temp,path)

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module);return module

def register(parent,out,live_app):
    import pandas as pd
    paths={'women':'womens_ufc_model/output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv',
           'men':'mens_ufc_model/data/processed/mens_training_rows_v3_bayes_smoothing_candidate.csv'}
    protocol=dict(version='v07-live-inputs-20261015-3',start='2023-09-27',end='2026-09-26',holdout_start='2025-09-27',
        exposure_dates=['2026-09-19','2026-09-26'],primary='log_loss',brier_margin=.015,log_loss_margin=.025,
        minimum_women_holdout_bouts=50,minimum_women_holdout_dates=20,
        split_policy='event-date-expanding-3_calibration-latest-20pct-v1',
        scoring='Stable identity orientation; one W/L outcome per bout; training event_date < evaluation date; five fixed probability bins',
        scope='Parent models with actual dated public-app women inputs; installed training snapshot retained',
        live_app=str(live_app.resolve()),live_code={rel:digest(live_app/rel) for rel in ['womens_ufc_model/predict_matchup_advanced.py','analyzer_protocol.py']},
        workers=2,
        evaluator_sha256=digest(Path(__file__)),
        limitations=['Retrospective corrected source snapshot; not prospective performance',
                    'Previously scored v0.6 dates excluded from final-test claim and retained in diagnostic accounting',
                    'Prior research exposure beyond recorded v0.6 dates is not independently established'],
        datasets={k:dict(path=v,sha256=digest(parent/v)) for k,v in paths.items()},
        code={rel:digest(parent/rel) for rel in ['womens_ufc_model/predict_matchup_advanced.py',
            'womens_ufc_model/chronological_ensemble.py','work/v07-research-baseline/womens_ufc_model/predict_matchup_advanced.py',
            'mens_ufc_model/src/models/train_baseline.py','mens_ufc_model/src/models/model_registry.py']})
    protocol['cohorts']={}
    import importlib.metadata
    protocol['dependencies']={k:importlib.metadata.version(k) for k in ('numpy','pandas','scikit-learn','scipy','joblib')}
    protocol['code']['womens_ufc_model/output_quality_fixed/ufc_womens_fighter_profiles.csv']=digest(parent/'womens_ufc_model/output_quality_fixed/ufc_womens_fighter_profiles.csv')
    for sex,rel in paths.items():
        data=pd.read_csv(parent/rel);data=data[data.fighter_a_won.isin([0,1])]
        cohort=data[(data.event_date>=protocol['start'])&(data.event_date<=protocol['end'])]
        development=cohort[cohort.event_date<protocol['holdout_start']]
        holdout=cohort[(cohort.event_date>=protocol['holdout_start'])&~cohort.event_date.isin(protocol['exposure_dates'])]
        protocol['cohorts'][sex]=dict(development_bouts=int(development.fight_id.nunique()),
            development_dates=int(development.event_date.nunique()),holdout_bouts=int(holdout.fight_id.nunique()),
            holdout_dates=int(holdout.event_date.nunique()),exposure_bouts=int(cohort[cohort.event_date.isin(protocol['exposure_dates'])].fight_id.nunique()))
    path=out/'protocol.json'
    if path.exists():raise ValueError('Protocol already registered; do not overwrite')
    protocol['registered_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    protocol['signature']=signature(protocol);write(path,protocol)
    print(json.dumps(protocol['cohorts'],indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--register',action='store_true');p.add_argument('--live-app',type=Path);p.add_argument('--sex',choices=['men','women'],default='women')
    p.add_argument('--partition',choices=['development','holdout'],default='development');p.add_argument('--max-dates',type=int)
    a=p.parse_args();parent=a.parent.resolve();out=a.out.resolve()
    if a.register:
        if a.live_app is None:raise ValueError('Actual live app inputs required')
        return register(parent,out,a.live_app)
    import numpy as np
    import pandas as pd
    from sklearn.metrics import log_loss,brier_score_loss
    protocol=json.loads((out/'protocol.json').read_text())
    original_signature=protocol.pop('signature')
    if signature(protocol)!=original_signature:raise ValueError('Protocol changed')
    protocol['signature']=original_signature
    if digest(Path(__file__))!=protocol['evaluator_sha256']:raise ValueError('Evaluator changed')
    import importlib.metadata
    if any(importlib.metadata.version(k)!=v for k,v in protocol['dependencies'].items()):raise ValueError('Dependencies changed')
    live_app=Path(protocol['live_app'])
    if any(digest(live_app/k)!=v for k,v in protocol['live_code'].items()):raise ValueError('Live input adapter changed')
    for row in protocol['datasets'].values():
        if digest(parent/row['path'])!=row['sha256']:raise ValueError('Dataset changed')
    for rel,sha in protocol['code'].items():
        if digest(parent/rel)!=sha:raise ValueError('Research source changed; register a new protocol')
    sex=a.sex;data=pd.read_csv(parent/protocol['datasets'][sex]['path'])
    if sex=='men':
        sys.path.insert(0,str(parent/'mens_ufc_model'))
        from src.models.train_baseline import read_training
        data=read_training(parent/protocol['datasets'][sex]['path'])
        data['event_date']=data.event_date.dt.strftime('%Y-%m-%d')
    data=data[data.fighter_a_won.isin([0,1])].reset_index(drop=True)
    planned=data[(data.event_date>=protocol['start'])&(data.event_date<=protocol['end'])]
    planned=(planned[planned.event_date<protocol['holdout_start']] if a.partition=='development'
             else planned[(planned.event_date>=protocol['holdout_start'])&~planned.event_date.isin(protocol['exposure_dates'])])
    dates=sorted(planned.event_date.unique())
    checkpoint=out/(sex+'-'+a.partition+'-checkpoint.json')
    state=json.loads(checkpoint.read_text()) if checkpoint.exists() else dict(signature=original_signature,
        sex=sex,partition=a.partition,planned_bouts=int(planned.fight_id.nunique()),planned_dates=len(dates),rows=[],attempts=[])
    if state['signature']!=original_signature:raise ValueError('Checkpoint changed inputs')
    completed={r['event_date'] for r in state['rows']}
    if sex=='women':
        sys.path.insert(0,str(parent/'womens_ufc_model'))
        candidate=load('v07_candidate',parent/'womens_ufc_model/predict_matchup_advanced.py')
        reference=load('v07_reference',parent/'work/v07-research-baseline/womens_ufc_model/predict_matchup_advanced.py')
        import chronological_ensemble as corrected
        sys.path.insert(0,str(live_app))
        live=load('v07_live',live_app/'womens_ufc_model/predict_matchup_advanced.py')
        profiles=pd.read_csv(parent/'womens_ufc_model/output_quality_fixed/ufc_womens_fighter_profiles.csv')
        names=profiles.groupby('fighter').profile_url.agg(lambda x:set(str(v).rstrip('/').rsplit('/',1)[-1] for v in x))
        identities={name:next(iter(ids)) for name,ids in names.items() if len(ids)==1}
        numeric=candidate.get_numeric_features(data);categorical=candidate.get_categorical_features(data)
        features=numeric+categorical
        original_cv=reference.cross_val_score
        def bounded(*args,**kwargs):kwargs['n_jobs']=protocol['workers'];return original_cv(*args,**kwargs)
        reference.cross_val_score=bounded
    else:
        sys.path.insert(0,str(parent/'mens_ufc_model'))
        from src.models.model_registry import get_model_config
        from src.models.train_baseline import build_model_pipeline
        config=get_model_config('v3_bayes_smoothed');features=config.features
    processed=0
    for date in dates:
        if date in completed:continue
        if a.max_dates is not None and processed>=a.max_dates:break
        processed+=1;started=time.monotonic();attempt=dict(event_date=date,started_at=dt.datetime.now(dt.timezone.utc).isoformat())
        attempt['status']='running';state['attempts'].append(attempt);write(checkpoint,state)
        attempt_number=len(state['attempts'])
        write(out/'attempts'/(sex+'-'+a.partition+f'-{attempt_number:05d}-start.json'),dict(signature=original_signature,**attempt))
        try:
            train=data[data.event_date<date].reset_index(drop=True);test=planned[planned.event_date==date].reset_index(drop=True)
            if set(train.fight_id)&set(test.fight_id):raise ValueError('Outer bout overlap')
            if sex=='women':
                live_test=test.copy();live_directory=live_app/'womens_ufc_model';saved_cwd=os.getcwd()
                try:
                    os.chdir(live_directory)
                    for identity,group in test.groupby('fight_id',sort=True):
                        if len(group)!=2:raise ValueError('Incomplete evaluation bout')
                        i,j=group.index
                        row=test.loc[i]
                        sys.argv=['live','--fighter-a',str(row.fighter_a),'--fighter-b',str(row.fighter_b),
                            '--division',str(row.division),'--fight-date',str(date),'--profiles',
                            str(live_directory/'output_quality_fixed/ufc_womens_fighter_profiles.csv'),'--quiet-diagnostics']
                        args=live.parse_args();args.comparison_only=True
                        with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink):prepared=live.prepare_matchup(args)
                        for feature in features:
                            live_test.loc[i,feature]=prepared['pred_row_forward'].iloc[0][feature]
                            live_test.loc[j,feature]=prepared['pred_row_reverse'].iloc[0][feature]
                finally:os.chdir(saved_cwd)
                fitted,weights,audit=corrected.fit_ensemble(train,features,numeric,categorical,candidate.build_model_pipeline)
                candidate_p=sum(weights[name]*est.predict_proba(live_test[features])[:,1] for name,est in fitted.items())
                models=reference.build_models(train.fighter_a_won)
                for estimator in models.values():
                    inner=estimator.estimator if hasattr(estimator,'estimator') else estimator
                    if hasattr(inner,'n_jobs'):inner.set_params(n_jobs=1)
                pipelines={name:reference.build_model_pipeline(model,numeric,categorical) for name,model in models.items()}
                weights=reference.compute_model_weights(pipelines,train[features],train.fighter_a_won)
                reference_p=np.zeros(len(test))
                for name,est in pipelines.items():
                    est.fit(train[features],train.fighter_a_won);reference_p+=weights[name]*est.predict_proba(live_test[features])[:,1]
                write(out/'audits'/('women-'+date+'.json'),audit)
            else:
                est=build_model_pipeline(config.model_name,list(config.numeric_features),list(config.categorical_features),logistic_c=config.logistic_c)
                est.fit(train[features],train.fighter_a_won)
                candidate_p=reference_p=est.predict_proba(test[features])[:,1]
            forecast=[]
            for identity,group in test.groupby('fight_id',sort=True):
                if len(group)!=2:raise ValueError('Expected mirrored pair '+str(identity))
                if sex=='women' and any(test.loc[i,'fighter_a'] not in identities for i in group.index):raise ValueError('Missing or ambiguous stable identity')
                order=sorted(group.index,key=lambda i:str(test.loc[i,'fighter_a_id'] if 'fighter_a_id' in test else identities[test.loc[i,'fighter_a']]))
                i,j=order
                cp=float((candidate_p[i]+1-candidate_p[j])/2);rp=float((reference_p[i]+1-reference_p[j])/2)
                if sex=='men':cp=.5+config.shrink_factor*(cp-.5);rp=cp
                baseline_row=live_test.loc[i] if sex=='women' else test.loc[i]
                diff=float(baseline_row['elo_diff']) if 'elo_diff' in baseline_row else float(baseline_row.get('pre_elo_diff',0))
                forecast.append(dict(event_date=date,fight_id=str(identity),fighter_a=str(test.loc[i,'fighter_a']),
                    fighter_b=str(test.loc[i,'fighter_b']),probability=cp,reference=rp,fifty_fifty=.5,
                    elo=1/(1+10**(-diff/400)),outcome=int(test.loc[i,'fighter_a_won']),training_max=str(train.event_date.max())))
            # Persist forecasts before outcome aggregation; retrospective scope
            # remains explicit because test rows already include known outcomes.
            write(out/'forecasts'/(sex+'-'+date+'.json'),dict(signature=original_signature,rows=forecast))
            state['rows'].extend(forecast);attempt['status']='complete'
        except Exception as exc:
            import traceback
            attempt.update(status='failed',error=str(exc),traceback=traceback.format_exc())
        attempt['seconds']=round(time.monotonic()-started,3)
        write(out/'attempts'/(sex+'-'+a.partition+f'-{attempt_number:05d}-finish.json'),dict(signature=original_signature,**attempt))
        write(checkpoint,state)
        print(sex,date,attempt['status'],len(state['rows']),'/',state['planned_bouts'],attempt['seconds'],flush=True)
        if attempt['status']=='failed':break
    summary=dict(signature=original_signature,sex=sex,partition=a.partition,planned=state['planned_bouts'],scored=len(state['rows']),
                 remaining=state['planned_bouts']-len(state['rows']),failed_attempts=sum(x['status']=='failed' for x in state['attempts']),metrics={})
    if state['rows']:
        y=[r['outcome'] for r in state['rows']]
        for field in ['probability','reference','fifty_fifty','elo']:
            values=[r[field] for r in state['rows']]
            summary['metrics'][field]=dict(log_loss=float(log_loss(y,values,labels=[0,1])),brier=float(brier_score_loss(y,values)),
                accuracy=float(np.mean((np.array(values)>=.5)==np.array(y))))
    write(out/(sex+'-'+a.partition+'-summary.json'),summary)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
