"""Real candidate prediction, cache corruption and historical/reverse checks."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json

def main():
    p=argparse.ArgumentParser();p.add_argument('--app',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    root=a.app.resolve();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=True)
    results=[]
    def run(label,fighters,date='2026-10-10'):
        output=a.out/(label+'.json');log=a.out/(label+'.log')
        cmd=[sys.executable,str(root/'ufc_matchup_analyzer.py'),'predict','women','--fighter-a',fighters[0],
            '--fighter-b',fighters[1],'--division','Flyweight','--fight-date',date,'--workers','1','--out',str(output)]
        with log.open('w',encoding='utf-8') as stream:subprocess.run(cmd,cwd=root,stdout=stream,stderr=subprocess.STDOUT,check=True)
        value=json.loads(output.read_text());assert value['model_version']=='v2_chronological_calibrated_ensemble'
        assert value['fold_audit']['status']=='PASS';assert value['reliability_label']=='Not validated for this policy'
        assert 'reliability_score' not in value
        assert value['evidence_quality']['scope']=='complete'
        results.append(dict(case=label,status='PASS',probability=value['fighter_a_win_probability'],cache_hits=value.get('compute_cache_hits',[])))
        atomic_json(a.out/'checks.json',dict(status='RUNNING',cases=results));print(label,'PASS',flush=True)
        return value
    fighters=['Valentina Shevchenko','Manon Fiorot']
    first=run('forward',fighters);warm=run('warm',fighters)
    assert 'fitted_womens_ensemble' in warm['compute_cache_hits']
    assert abs(first['fighter_a_win_probability']-warm['fighter_a_win_probability'])<=1e-12
    reverse=run('reverse',list(reversed(fighters)))
    assert abs(first['fighter_a_win_probability']-reverse['fighter_b_win_probability'])<=1e-12
    models=[]
    for path in (root/'.runtime/compute_cache').glob('*.json'):
        info=json.loads(path.read_text())
        if info.get('kind')=='fitted_womens_ensemble':models.append(path.with_suffix('.bin'))
    assert models
    for path in models:path.write_bytes(b'controlled corrupt cache fixture')
    recovered=run('corrupt-cache-recovered',fighters)
    assert 'fitted_womens_ensemble' not in recovered['compute_cache_hits']
    assert abs(first['fighter_a_win_probability']-recovered['fighter_a_win_probability'])<=1e-12
    historical=run('historical',fighters,'2020-01-01')
    assert historical['actual_max_training_event_date_used']<'2020-01-01'
    atomic_json(a.out/'checks.json',dict(status='PASS',cases=results))

if __name__=='__main__':main()
