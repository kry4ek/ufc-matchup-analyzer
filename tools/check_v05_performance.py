"""Measured cross-matchup reuse and cached/uncached prediction parity."""
import argparse
import contextlib
import json
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json
from analyzer_cache import clear_cache,cache_size
from ufc_matchup_analyzer import parser,predict

def comparable(value):
    return {k:v for k,v in value.items() if not any(x in k for x in ('seconds','timings','generated_at','history_id','fingerprint','summary','metric_records','fight_evidence','cache','version','working_set','memory_measurement','calculation_request','reused'))}

def assert_equal(a,b,path=''):
    if isinstance(a,dict):
        assert set(a)==set(b),(path,set(a)^set(b))
        for k in a:assert_equal(a[k],b[k],path+'/'+k)
    elif isinstance(a,list):
        assert len(a)==len(b),path
        for i,(x,y) in enumerate(zip(a,b)):assert_equal(x,y,path+'/'+str(i))
    elif isinstance(a,(int,float)) and isinstance(b,(int,float)):
        assert abs(a-b)<=1e-12,(path,a,b)
    else:assert a==b,(path,a,b)

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--repeat',type=int,default=3);args=p.parse_args()
    report=dict(status='RUNNING',runs=[],checks=[])
    args.out.parent.mkdir(parents=True,exist_ok=True)
    cases={'men':[('Islam Makhachev','Justin Gaethje'),('Charles Oliveira','Dustin Poirier')],
           'women':[('Valentina Shevchenko','Manon Fiorot'),('Alexa Grasso','Rose Namajunas')]}
    for sex,pairs in cases.items():
        clear_cache(ROOT)
        expected={}
        for repeat in range(args.repeat):
            for kind,(a,b) in [('cold',pairs[0]),('warm-different',pairs[1])]:
                cli=parser().parse_args(['predict',sex,'--fighter-a',a,'--fighter-b',b,'--division','Lightweight' if sex=='men' else 'Flyweight','--fight-date','2026-10-10','--workers','1'])
                if kind=='cold':cli.force_recalculate=True
                start=time.monotonic()
                with (args.out.parent/(sex+'-'+kind+'-'+str(repeat)+'.log')).open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream):value=predict(cli)
                run=dict(sex=sex,kind=kind,repeat=repeat+1,seconds=round(time.monotonic()-start,3),time_to_comparison=value['time_to_comparison_seconds'],hits=value.get('compute_cache_hits'),peak_mib=value.get('peak_process_tree_working_set_mib'),cache_bytes=cache_size(ROOT))
                report['runs'].append(run);atomic_json(args.out,report)
                atomic_json(args.out.parent/(sex+'-'+kind+'-'+str(repeat)+'.json'),value)
                if kind in expected:assert_equal(comparable(expected[kind]),comparable(value))
                expected[kind]=value
                print(json.dumps(run),flush=True)
        # Fresh computation of the second pair verifies actual cache reuse, not only repeat determinism.
        cli=parser().parse_args(['predict',sex,'--fighter-a',pairs[1][0],'--fighter-b',pairs[1][1],'--division','Lightweight' if sex=='men' else 'Flyweight','--fight-date','2026-10-10','--workers','1'])
        cli.force_recalculate=True
        with (args.out.parent/(sex+'-uncached-second.log')).open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream):fresh=predict(cli)
        assert_equal(comparable(expected['warm-different']),comparable(fresh))
        baseline=json.loads((ROOT/'work/v05-validation'/('baseline-'+sex+'.json')).read_text(encoding='utf-8'))
        assert_equal(comparable(baseline),comparable(expected['cold']))
        cold=statistics.median(r['seconds'] for r in report['runs'] if r['sex']==sex and r['kind']=='cold')
        warm=statistics.median(r['seconds'] for r in report['runs'] if r['sex']==sex and r['kind']=='warm-different')
        report['checks'].append(dict(sex=sex,baseline_parity='PASS',cached_parity='PASS',cold_median_seconds=cold,warm_median_seconds=warm,reduction_percent=round((1-warm/cold)*100,2),target_pass=warm<=cold*.5))
        atomic_json(args.out,report)
    report['status']='PASS' if all(c['target_pass'] for c in report['checks']) else 'TARGET_MISSED'
    atomic_json(args.out,report)

if __name__=='__main__':main()
