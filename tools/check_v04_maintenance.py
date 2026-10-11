"""Mixed-outcome capture/rebuild checks on an explicitly disposable app copy.

Network discovery/parsing is replaced with labeled fixtures. Both real updaters,
all rebuild subprocesses, audits, promotion, repeat and recovery are exercised.
"""
import argparse
import copy
import csv
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest import mock
import pandas as pd
from bs4 import BeautifulSoup
from analyzer_support import ROOT, atomic_json, data_health, digest
from analyzer_maintenance import maintenance, recover
from analyzer_runtime import run_logged_process

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))

def fixture_runner(cmd,cwd,log,progress):
    if not Path(cmd[1]).name.startswith('update_ufc_'):
        return run_logged_process(cmd,cwd,log,progress=lambda **e:progress(target='men' if cwd.name=='mens_ufc_model' else 'women',**{k:v for k,v in e.items() if k!='target'}))
    sex='men' if cwd.name=='mens_ufc_model' else 'women'
    sys.path.insert(0,str(cwd));name='fixture_updater_'+sex
    spec=importlib.util.spec_from_file_location(name,cwd/cmd[1]);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    event=dict(event_id='fixture_event',event_name='CONTROLLED MIXED OUTCOME FIXTURE',event_date=pd.Timestamp('2026-10-10'),event_url='http://ufcstats.com/event-details/fixture_event',location='Fixture')
    ids=['v04fixture_'+sex+'_'+str(i) for i in range(3)]
    old=Path.cwd();os.chdir(cwd)
    try:
        with mock.patch.object(sys,'argv',cmd[1:]),mock.patch.object(module,'parse_event_list',return_value=[event]):
            if sex=='men':
                raw=cwd/'data/raw/ufcstats_men';fights=read(raw/'fights.csv');stats=read(raw/'fight_stats.csv')
                template=next(r for r in fights if r['weight_class']=='Lightweight' and r['result']=='win_loss')
                pair=[r for r in stats if r['fight_id']==template['fight_id']]
                assert len(pair)==2
                metas=[];parsed={}
                for index,outcome in enumerate(('win_loss','draw','no_contest')):
                    rows=copy.deepcopy(pair);fight=copy.deepcopy(template)
                    fight.update(fight_id=ids[index],event_id=event['event_id'],event_date='2026-10-10',result=outcome,is_mens_bout=True)
                    if outcome!='win_loss':fight.update(winner_id='',loser_id='')
                    markers=[]
                    for row in rows:
                        result=('win' if row['fighter_id']==fight['winner_id'] else 'loss') if outcome=='win_loss' else outcome
                        marker={'win':'W','loss':'L','draw':'D','no_contest':'NC'}[result];markers.append(marker)
                        row.update(fight_id=ids[index],event_id=event['event_id'],event_date='2026-10-10',result=result,won=1 if result=='win' else 0 if result=='loss' else pd.NA)
                    meta=dict(fight_id=ids[index],fight_url='http://ufcstats.com/fight-details/'+ids[index],division='Lightweight',fighter_1=rows[0]['fighter_name'],fighter_2=rows[1]['fighter_name'],fighter_1_result_marker=markers[0],fighter_2_result_marker=markers[1])
                    metas.append(meta);parsed[ids[index]]=(fight,rows,{})
                scraper=mock.Mock();scraper.refresh_cache=False;scraper.fetch_html.return_value='<html>fixture</html>';scraper.get_event_fights.return_value=metas
                with mock.patch.object(module,'make_scraper',return_value=scraper),mock.patch.object(module,'parse_fight_detail',side_effect=lambda scraper,event,meta:copy.deepcopy(parsed[meta['fight_id']])):
                    assert module.main()==0
            else:
                stats=read(cwd/'output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv')
                pair=[r for r in stats if r['fight_id']==stats[0]['fight_id']];assert len(pair)==2
                parsed={}
                for index,outcome in enumerate(('win_loss','draw','nc')):
                    rows=copy.deepcopy(pair)
                    for side,row in enumerate(rows):
                        result=('win' if side==0 else 'loss') if outcome=='win_loss' else outcome
                        row.update(fight_id=ids[index],event_name=event['event_name'],event_date=pd.Timestamp('2026-10-10'),result=result,result_marker={'win':'W','loss':'L','draw':'D','nc':'NC'}[result],won=1 if result=='win' else 0 if result=='loss' else float('nan'))
                    parsed[ids[index]]=rows
                def parse(session,url,event,**kwargs):
                    rows=copy.deepcopy(parsed[url.rsplit('/',1)[-1]])
                    module.validate_completed_people(rows,event,kwargs['today'],kwargs['allow_future_events'])
                    return rows
                with mock.patch.object(module,'fetch_soup',return_value=BeautifulSoup('<html>fixture</html>','html.parser')),mock.patch.object(module,'parse_fight_links_from_event',return_value=['http://ufcstats.com/fight-details/'+i for i in ids]),mock.patch.object(module,'parse_fight_page',side_effect=parse):module.main()
    finally:os.chdir(old)

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    # The caller must create this marker after making a disposable extraction.
    if not (ROOT.parent/'DISPOSABLE_V04_CHECK').is_file():raise ValueError('This check requires a marked disposable portable extraction')
    baseline={r['path']:digest(ROOT/r['path']) for r in data_health(ROOT)}
    events=[];last_phase=[None]
    def progress(**event):
        events.append(event)
        phase=(event.get('stage'),event.get('phase'),event.get('step_index'))
        if phase!=last_phase[0]:
            print(event.get('message'),flush=True);last_phase[0]=phase
    runner=lambda cmd,cwd,log:fixture_runner(cmd,cwd,log,progress)
    transaction=maintenance(ROOT,apply=True,runner=runner,progress=progress)
    journal=json.loads((ROOT/'.runtime/transactions'/transaction/'journal.json').read_text())
    assert journal['status']=='committed',journal
    for sex in ('men','women'):
        summary=journal['summary'][sex]
        assert [summary[k] for k in ('captured_fights','decisive_fights','draws','no_contests','binary_training_rows_added')]==[3,1,1,1,2],summary
        base=ROOT/('mens_ufc_model' if sex=='men' else 'womens_ufc_model')
        stats=read(base/('data/raw/ufcstats_men/fight_stats.csv' if sex=='men' else 'output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv'))
        nonbinary={'v04fixture_'+sex+'_'+str(i) for i in (1,2)}
        captured=[r for r in stats if r['fight_id'] in nonbinary]
        assert len(captured)==4 and all(r['won']=='' for r in captured)
        train=read(base/('data/processed/mens_training_rows_v3_bayes_smoothing_candidate.csv' if sex=='men' else 'output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv'))
        assert not any(r['fight_id'] in nonbinary for r in train)
    assert all(r['status']=='PASS' for r in data_health(ROOT))
    after={r['path']:digest(ROOT/r['path']) for r in data_health(ROOT)}
    repeat=maintenance(ROOT,apply=True,runner=runner,progress=progress)
    assert json.loads((ROOT/'.runtime/transactions'/repeat/'journal.json').read_text())['status']=='no_changes'
    assert after=={r['path']:digest(ROOT/r['path']) for r in data_health(ROOT)}
    recover(ROOT,transaction)
    assert baseline=={r['path']:digest(ROOT/r['path']) for r in data_health(ROOT)}
    measured=[e for e in events if e.get('total')]
    assert measured and all(0<=e['completed']<=e['total'] for e in measured)
    assert all(not e['cancellable'] for e in events if e.get('stage')=='committing')
    atomic_json(args.out,dict(status='PASS',scope='Controlled fixtures; actual updaters, feature rebuilds, validation, transaction and recovery',summary=journal['summary'],transaction=transaction,repeat=repeat,measured_progress_events=len(measured),all_original_hashes_restored=True))
    print('Mixed-outcome portable verification PASS',flush=True)

if __name__=='__main__':main()
