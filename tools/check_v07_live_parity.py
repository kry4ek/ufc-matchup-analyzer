"""Check dated live input rows against stored historical prefight rows."""
import argparse
import contextlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json

def main():
    p=argparse.ArgumentParser();p.add_argument('--app',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out=a.out.resolve();root=a.app.resolve();directory=root/'womens_ufc_model'
    import pandas as pd
    sys.path.insert(0,str(directory))
    spec=importlib.util.spec_from_file_location('parity_women',directory/'predict_matchup_advanced.py')
    engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
    data=pd.read_csv(directory/'output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv')
    dates=['2023-10-07','2024-04-13','2025-05-10','2025-11-15','2026-09-12']
    selected=[]
    for date in dates:
        subset=data[data.event_date==date]
        if not subset.empty:selected.append(subset.sort_values(['fight_id','fighter_a']).iloc[0])
    results=[];original=os.getcwd()
    try:
        os.chdir(directory)
        for row in selected:
            args_list=['--fighter-a',row.fighter_a,'--fighter-b',row.fighter_b,'--division',row.division,
                '--fight-date',row.event_date,'--profiles',str(directory/'output_quality_fixed/ufc_womens_fighter_profiles.csv'),'--quiet-diagnostics']
            sys.argv=['engine',*args_list];args=engine.parse_args();args.comparison_only=True
            with contextlib.redirect_stdout(open(os.devnull,'w')):prepared=engine.prepare_matchup(args)
            forward=prepared['pred_row_forward'].iloc[0]
            features=prepared['feature_cols'];differences=[]
            for feature in features:
                actual=forward.get(feature);expected=row.get(feature)
                if pd.isna(actual) and pd.isna(expected):continue
                if isinstance(expected,str) or isinstance(actual,str):match=actual==expected
                else:match=not(pd.isna(actual) or pd.isna(expected)) and math.isclose(float(actual),float(expected),rel_tol=1e-10,abs_tol=1e-10)
                if not match:differences.append(dict(feature=feature,live=None if pd.isna(actual) else str(actual),stored=None if pd.isna(expected) else str(expected)))
            results.append(dict(fight_id=row.fight_id,date=row.event_date,features=len(features),differences=differences,status='FAIL' if differences else 'PASS'))
            atomic_json(a.out,dict(status='FAIL' if any(r['differences'] for r in results) else 'PASS',cases=results))
            print(row.event_date,row.fighter_a,'vs',row.fighter_b,'differences',len(differences),flush=True)
    finally:os.chdir(original)
    if any(r['differences'] for r in results):raise SystemExit(1)

if __name__=='__main__':main()
