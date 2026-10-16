"""Check numeric conversion and complete dated histories against the original."""
import argparse
from decimal import Decimal
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json
from tools.check_v06_performance import equal

def main():
    p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    import numpy as np
    import pandas as pd
    sys.path.insert(0,str(a.parent/'mens_ufc_model'))
    from src.features import mens_features as features,mens_live_v3_bayes_features as live
    source=a.parent/'work/v07-performance-baseline/mens_ufc_model/src/features/mens_features.py'
    spec=importlib.util.spec_from_file_location('original_mens_features_v07',source);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    tests=[None,True,False,0,1,-2,1.25,float('nan'),float('inf'),float('-inf'),np.int64(5),np.uint64(2**64-1),
        np.float32(.1),np.float64(float('nan')),np.bool_(True),pd.NA,pd.NaT,Decimal('1.25'),'', 'n/a',' 3.5 ','nan','1e20',2**64,10**100]
    for value in tests:
        for default in (0.0,-3.0,float('nan')):
            x=old._num(value,default);y=features._num(value,default)
            assert x==y or math.isnan(x) and math.isnan(y),(repr(value),x,y)
    fights=pd.read_csv(a.parent/'mens_ufc_model/data/raw/ufcstats_men/fights.csv')
    stats=pd.read_csv(a.parent/'mens_ufc_model/data/raw/ufcstats_men/fight_stats.csv')
    context=live._prepare_base_rate_context(fights,stats);optimized=features._num
    results=[]
    try:
        for date in ('2000-01-01','2020-01-01','2026-10-10'):
            features._num=old._num;original=live._recompute_base_state_before(context,pd.Timestamp(date))
            features._num=optimized;candidate=live._recompute_base_state_before(context,pd.Timestamp(date))
            equal(original,candidate)
            results.append(dict(date=date,fighters=len(candidate),status='PASS'))
            atomic_json(a.out,dict(status='RUNNING',scalar_cases=len(tests)*3,histories=results))
            print(date,'all',len(candidate),'fighter histories identical',flush=True)
    finally:features._num=optimized
    atomic_json(a.out,dict(status='PASS',scalar_cases=len(tests)*3,histories=results))

if __name__=='__main__':main()
