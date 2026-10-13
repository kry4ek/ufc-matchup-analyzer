"""Compare original/optimized parent history construction with all-state parity."""
import argparse
from collections import deque
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest

def equal(a,b,path=''):
    if isinstance(a,dict):
        assert set(a)==set(b),(path,'keys')
        for k in a:equal(a[k],b[k],path+'/'+str(k))
    elif isinstance(a,(list,tuple,deque)):
        assert len(a)==len(b),path
        for i,(x,y) in enumerate(zip(a,b)):equal(x,y,path+'/'+str(i))
    elif isinstance(a,float) and isinstance(b,float):
        assert math.isnan(a) and math.isnan(b) or abs(a-b)<=1e-12,(path,a,b)
    else:assert a==b,(path,a,b)

def main():
    import pandas as pd
    p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--repeat',type=int,default=3);a=p.parse_args()
    parent=a.parent.resolve();sys.path.insert(0,str(parent/'mens_ufc_model'))
    from src.features import mens_live_v2_features as new
    path=parent/'work/v06-research-baseline/mens_ufc_model/src/features/mens_live_v2_features.py'
    spec=importlib.util.spec_from_file_location('original_live_v2',path);old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
    fights=pd.read_csv(parent/'mens_ufc_model/data/raw/ufcstats_men/fights.csv')
    stats=pd.read_csv(parent/'mens_ufc_model/data/raw/ufcstats_men/fight_stats.csv')
    old_context=old.prepare_live_v2_context(fights,stats);new_context=new.prepare_live_v2_context(fights,stats)
    report=dict(status='RUNNING',repetitions=[],baseline_sha256=digest(path),optimized_sha256=digest(parent/'mens_ufc_model/src/features/mens_live_v2_features.py'),parity=[])
    for date in ('2020-01-01','2026-10-10'):
        for repeat in range(a.repeat):
            results={}
            for name,module,context in [('original',old,old_context),('optimized',new,new_context)] if repeat%2==0 else [('optimized',new,new_context),('original',old,old_context)]:
                started=time.monotonic();results[name]=module._recompute_state_before(context,pd.Timestamp(date))
                seconds=time.monotonic()-started
                report['repetitions'].append(dict(date=date,repeat=repeat+1,method=name,seconds=round(seconds,3)))
                atomic_json(a.out,report);print(date,name,round(seconds,3),flush=True)
            equal(results['original'],results['optimized']);report['parity'].append(dict(date=date,repeat=repeat+1,status='PASS',scope='All fighter histories, global and division totals'))
            atomic_json(a.out,report)
    report['summary']=[]
    for date in ('2020-01-01','2026-10-10'):
        times={method:statistics.median(r['seconds'] for r in report['repetitions'] if r['date']==date and r['method']==method) for method in ('original','optimized')}
        report['summary'].append(dict(date=date,**times,reduction_percent=round((1-times['optimized']/times['original'])*100,2)))
    report['status']='PASS';atomic_json(a.out,report)
if __name__=='__main__':main()
