"""Sequential expensive checks, one active worker, durable per-suite outputs."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'work/v0.8/final-benchmarks';out.mkdir(parents=True,exist_ok=True)
cases=[('startup','men',5)]+[(mode,sex,3) for mode in ('compare','predict') for sex in ('men','women')]
for mode,sex,repeats in cases:
    path=out/(mode+'-'+sex+'.json')
    if path.exists():
        import json
        if json.loads(path.read_text()).get('status')=='PASS':continue
        raise RuntimeError('Partial prior case exists; inspect checkpoint before rerunning: '+str(path))
    command=[sys.executable,'-X','utf8','-u',str(ROOT/'tools/check_v08_performance.py'),'--reference',str(ROOT/'work/v0.8/reference'),'--candidate',str(ROOT/'work/v0.8/candidate'),'--mode',mode,'--sex',sex,'--repeat',str(repeats),'--out',str(path)]
    with path.with_suffix('.log').open('w',encoding='utf-8') as stream:
        subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
    print(mode,sex,'PASS',flush=True)
