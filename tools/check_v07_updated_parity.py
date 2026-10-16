"""Verify actual parent/export predictions on a newly refreshed snapshot."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--parent',type=Path,required=True)
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--target',choices=('all','men','women'),default='all')
    args=parser.parse_args()
    parent,app,out=args.parent.resolve(),args.app.resolve(),args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    files=json.loads((app/'dataset_manifest.json').read_text())['files']
    assert len(files)==15 and all(digest(parent/e['path'])==digest(app/e['path']) for e in files)
    results=[]
    def run(label,cmd,cwd):
        with (out/(label+'.log')).open('w',encoding='utf-8') as stream:
            subprocess.run([sys.executable,*map(str,cmd)],cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=1800)
        return json.loads((out/(label+'.json')).read_text())
    for sex,names,division in [('men',['Islam Makhachev','Justin Gaethje'],'Lightweight'),
                                ('women',['Valentina Shevchenko','Manon Fiorot'],'Flyweight')]:
        if args.target not in ('all',sex):continue
        common=['--fighter-a',names[0],'--fighter-b',names[1],'--fight-date','2026-10-17']
        if sex=='men':
            source=[parent/'mens_ufc_model/src/prediction/predict_matchup.py',*common,'--weight-class',division,
                '--model-version','v3_bayes_smoothed','--training','data/processed/mens_training_rows_v3_bayes_smoothing_candidate.csv',
                '--as-of-date','2026-10-14','--out',out/(sex+'-parent.json')]
        else:
            source=[ROOT/'tools/run_parent_women.py','--parent',parent,*common,'--division',"Women's "+division,
                '--profiles','output_quality_fixed/ufc_womens_fighter_profiles.csv','--quiet-diagnostics',
                '--json-out',out/(sex+'-parent.json')]
        original=run(sex+'-parent',source,parent/('mens_ufc_model' if sex=='men' else 'womens_ufc_model'))
        public=[app/'ufc_matchup_analyzer.py','predict',sex,*common,'--division',division,'--workers','1',
                '--force-recalculate','--out',out/(sex+'-app.json')]
        if sex=='men':public+=['--as-of-date','2026-10-14']
        exported=run(sex+'-app',public,app)
        key='fighter_a_final_probability' if sex=='men' else 'fighter_a_win_probability'
        expected=original[key];actual=exported['fighter_a_win_probability']
        assert math.isclose(actual,expected,rel_tol=0,abs_tol=1e-12),(sex,actual,expected)
        if sex=='women':
            assert original['fold_audit']==exported['fold_audit']
            assert exported['model_version']=='v2_chronological_calibrated_ensemble'
        else:
            for field in ('fighter_a_raw_probability','fighter_a_reverse_adjusted_raw_probability','fighter_a_raw_avg_probability'):
                assert math.isclose(original[field],exported[field],rel_tol=0,abs_tol=1e-12),field
        results.append(dict(sex=sex,status='PASS',parent_probability=expected,app_probability=actual))
        atomic_json(out/'results.json',dict(status='RUNNING',all_15_dataset_hashes_match=True,cases=results))
        print(sex,'parent/export parity PASS',actual,flush=True)
    atomic_json(out/'results.json',dict(status='PASS',all_15_dataset_hashes_match=True,cases=results))


if __name__=='__main__':
    main()
