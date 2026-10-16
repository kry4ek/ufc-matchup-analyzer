"""Alternating real-app benchmarks with fixed model semantics and raw parity."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest
from tools.check_v06_performance import equal

def main():
    p=argparse.ArgumentParser();p.add_argument('--reference',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--sex',choices=['men','women'],default='men');p.add_argument('--repeat',type=int,default=3)
    a=p.parse_args();a.out=a.out.resolve();a.out.parent.mkdir(parents=True,exist_ok=True)
    roots={name:path.resolve() for name,path in [('reference',a.reference),('candidate',a.candidate)]}
    for root in roots.values():
        atomic_json(root/'.runtime/ui_preferences.json',dict(history_enabled=False))
    files=['dataset_manifest.json','requirements.lock']
    for rel in files:
        if digest(roots['reference']/rel)!=digest(roots['candidate']/rel):raise ValueError('Benchmark inputs differ: '+rel)
    sex=a.sex;inputs=(['Islam Makhachev','Justin Gaethje','Lightweight'] if sex=='men'
                     else ['Valentina Shevchenko','Manon Fiorot','Flyweight'])
    report=dict(status='RUNNING',model_semantics='Same promoted policy; only performance implementation differs',
        conditions='No competing evaluation jobs; same reference machine/runtime/data, OS file cache not controlled',
        repetitions=[],summaries=[])
    for repeat in range(a.repeat):
        values={}
        for name in ('reference','candidate') if repeat%2==0 else ('candidate','reference'):
            root=roots[name];output=a.out.parent/f'{sex}-{name}-{repeat+1}.json';log=output.with_suffix('.log')
            command=[sys.executable,str(root/'ufc_matchup_analyzer.py'),'predict',sex,'--fighter-a',inputs[0],
                '--fighter-b',inputs[1],'--division',inputs[2],'--fight-date','2026-10-10','--workers','1','--force-recalculate','--out',str(output)]
            start=time.monotonic()
            with log.open('w',encoding='utf-8') as stream:subprocess.run(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT,check=True)
            value=json.loads(output.read_text());values[name]=value
            report['repetitions'].append(dict(method=name,repeat=repeat+1,wall_seconds=time.monotonic()-start,
                request_seconds=value['total_request_seconds'],initial_seconds=value['time_to_initial_seconds'],
                peak_mib=value.get('peak_process_tree_working_set_mib'),timings=value.get('stage_timings_seconds',{})))
            atomic_json(a.out,report);print(sex,name,repeat+1,value['total_request_seconds'],flush=True)
        if values['reference']['model_version']!=values['candidate']['model_version']:raise ValueError('Model policy changed during benchmark')
        for field in ('fighter_a_win_probability','fighter_b_win_probability','model_weights','model_predictions',
                      'fighter_a_comparison','fighter_b_comparison','metric_records'):
            if field in values['reference'] or field in values['candidate']:equal(values['reference'].get(field),values['candidate'].get(field),field)
    medians={name:statistics.median(r['request_seconds'] for r in report['repetitions'] if r['method']==name) for name in roots}
    report.update(status='PASS',medians=medians,reduction_percent=100*(1-medians['candidate']/medians['reference']))
    atomic_json(a.out,report);print(json.dumps(report['medians']),report['reduction_percent'])

if __name__=='__main__':main()
