"""Alternating end-to-end measurements; caches and conditions are explicit."""
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

def main():
    p=argparse.ArgumentParser();p.add_argument('--reference',type=Path,required=True);p.add_argument('--candidate',type=Path,default=ROOT)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--mode',choices=['startup','compare','predict'],default='startup');p.add_argument('--sex',choices=['men','women'],default='men');p.add_argument('--repeat',type=int,default=3)
    a=p.parse_args();a.out=a.out.resolve();a.out.parent.mkdir(parents=True,exist_ok=True)
    roots={'reference':a.reference.resolve(),'candidate':a.candidate.resolve()}
    if digest(roots['reference']/'dataset_manifest.json')!=digest(roots['candidate']/'dataset_manifest.json'):
        # Version metadata may differ; bytes of each source dataset must agree.
        specs=[json.loads((r/'dataset_manifest.json').read_text())['files'] for r in roots.values()]
        if [(v['path'],v['sha256']) for v in specs[0]]!=[(v['path'],v['sha256']) for v in specs[1]]:raise ValueError('Datasets differ')
    report=dict(status='RUNNING',mode=a.mode,sex=a.sex,conditions='Same runtime/hardware/data, alternating order. OS file caches uncontrolled. Startup structural cache warmed after first candidate scan; fresh compare/predict bypass app computation and saved-result caches.',runs=[])
    for repetition in range(a.repeat):
        pair={}
        for name in (('reference','candidate') if repetition%2==0 else ('candidate','reference')):
            root=roots[name];output=a.out.with_name(a.out.stem+f'-{name}-{repetition+1}.json');log=output.with_suffix('.log')
            if a.mode=='startup':
                code="import sys,time,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); t=time.monotonic(); from analyzer_worker import installation_report; v=installation_report(Path(sys.argv[1])); Path(sys.argv[2]).write_text(json.dumps(dict(seconds=time.monotonic()-t,ready=v['ready'])))"
                command=[sys.executable,'-X','utf8','-u','-c',code,str(root),str(output)]
            else:
                fighters=('Islam Makhachev','Justin Gaethje','Lightweight') if a.sex=='men' else ('Valentina Shevchenko','Manon Fiorot','Flyweight')
                command=[sys.executable,'-X','utf8','-u',str(root/'ufc_matchup_analyzer.py'),a.mode,a.sex,'--fighter-a',fighters[0],'--fighter-b',fighters[1],'--division',fighters[2],'--fight-date','2026-10-10','--workers','1','--force-recalculate','--out',str(output)]
            start=time.monotonic()
            with log.open('w',encoding='utf-8') as stream:result=subprocess.run(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT)
            if result.returncode:raise RuntimeError('Benchmark failed: '+str(log))
            value=json.loads(output.read_text(encoding='utf-8'));pair[name]=value
            report['runs'].append(dict(method=name,repetition=repetition+1,wall_seconds=time.monotonic()-start,
                seconds=value.get('seconds',value.get('total_request_seconds')),initial=value.get('time_to_initial_seconds'),
                stages=value.get('stage_timings_seconds',{}),peak_mib=value.get('peak_process_tree_working_set_mib')))
            atomic_json(a.out,report);print(a.mode,a.sex,name,repetition+1,report['runs'][-1]['seconds'],flush=True)
        if a.mode!='startup':
            from tools.check_v06_performance import equal
            for field in ('fighter_a_win_probability','fighter_b_win_probability','fighter_a_comparison','fighter_b_comparison','metric_records'):
                equal(pair['reference'].get(field),pair['candidate'].get(field),field)
    medians={name:statistics.median(v['seconds'] for v in report['runs'] if v['method']==name) for name in roots}
    report.update(status='PASS',medians=medians,reduction_percent=100*(1-medians['candidate']/medians['reference']))
    atomic_json(a.out,report)
if __name__=='__main__':main()
