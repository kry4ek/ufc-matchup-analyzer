"""Actual correction rebuild/promotion/restore on a marked disposable app copy."""
import argparse
import copy
import datetime as dt
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import manifest,digest,atomic_json,data_health
from analyzer_corrections import read_rows,SOURCE_PATHS,diff_capture,apply,validate_preview
from analyzer_history import fingerprint
from analyzer_maintenance import recover

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    if not (ROOT.parent/'DISPOSABLE_V05_CHECK').exists():raise ValueError('Use a marked disposable app copy.')
    baseline={e['path']:digest(ROOT/e['path']) for e in manifest()['files']}
    report=dict(status='RUNNING',cases=[])
    for outcome in ('no_contest','draw'):
        captures={};changes=[];ids={}
        for sex in ('men','women'):
            tables={rel:read_rows(ROOT/rel) for rel in SOURCE_PATHS[sex]}
            base=tables[SOURCE_PATHS[sex][0]]
            fight=max((r for r in base if r['result'] in ('win_loss','win')),key=lambda r:r['event_date'])
            fid=fight['fight_id'];ids[sex]=fid
            chosen=[r for r in base if (r['event_id']==fight['event_id'] if sex=='men' else r['event_name']==fight['event_name'] and r['event_date']==fight['event_date'])]
            event=dict(event_id=fight.get('event_id','fixture'),event_name=fight.get('event_name','CONTROLLED CORRECTION'),event_date=fight['event_date'][:10])
            fresh={SOURCE_PATHS[sex][0]:copy.deepcopy(chosen)}
            if sex=='men':
                event=next(r for r in read_rows(ROOT/'mens_ufc_model/data/raw/ufcstats_men/events.csv') if r['event_id']==fight['event_id'])
                fresh[SOURCE_PATHS[sex][1]]=copy.deepcopy([r for r in tables[SOURCE_PATHS[sex][1]] if r['event_id']==fight['event_id']])
                for r in fresh[SOURCE_PATHS[sex][0]]:
                    if r['fight_id']==fid:r.update(result=outcome,winner_id='',loser_id='')
                for r in fresh[SOURCE_PATHS[sex][1]]:
                    if r['fight_id']==fid:r.update(result=outcome,won='')
            else:
                for r in fresh[SOURCE_PATHS[sex][0]]:
                    if r['fight_id']==fid:r.update(result='nc' if outcome=='no_contest' else 'draw',result_marker='NC' if outcome=='no_contest' else 'D',won='')
            captures[sex]=dict(events=[event],tables=fresh)
            changes.extend(dict(sex=sex,**c) for c in diff_capture(ROOT,sex,captures[sex]))
        identifier=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-1234abcd'
        value=dict(schema=1,id=identifier,created_at=dt.datetime.now(dt.timezone.utc).isoformat(),start='2026-09-01',end='2026-09-26',baseline=baseline,captures=captures,changes=changes)
        value['integrity']=fingerprint(value);atomic_json(ROOT/'.runtime/corrections'/identifier/'preview.json',value)
        result=apply(ROOT,identifier,progress=lambda **e:print(e['message'],flush=True));assert result['status']=='committed',result
        for sex in ('men','women'):
            summary=result['summary'][sex];assert summary['binary_training_rows_removed']==2,summary
            rel='mens_ufc_model/data/processed/mens_training_rows_v3_bayes_smoothing_candidate.csv' if sex=='men' else 'womens_ufc_model/output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv'
            assert not any(r['fight_id']==ids[sex] for r in read_rows(ROOT/rel))
        assert all(c['status']=='PASS' for c in data_health(ROOT))
        try:validate_preview(ROOT,identifier)
        except ValueError:pass
        else:raise AssertionError('Stale preview accepted after source changed')
        recover(ROOT,result['transaction'])
        assert baseline=={e['path']:digest(ROOT/e['path']) for e in manifest()['files']}
        report['cases'].append(dict(outcome=outcome,status='PASS',summary=result['summary'],all_hashes_restored=True));atomic_json(args.out,report)
        print(outcome+' actual correction/rebuild/restore PASS',flush=True)
    report['status']='PASS';atomic_json(args.out,report)

if __name__=='__main__':main()
