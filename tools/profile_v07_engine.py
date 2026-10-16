"""Profile preparation in the disposable app, without fitting or updating data."""
import argparse
import cProfile
import json
import os
from pathlib import Path
import pstats
import runpy
import sys

def main():
    p=argparse.ArgumentParser();p.add_argument('--app',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();root=a.app.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(root));os.chdir(root/'mens_ufc_model')
    sys.argv=['engine','men','compare','--fighter-a','Islam Makhachev','--fighter-b','Justin Gaethje',
        '--fight-date','2026-10-10','--weight-class','Lightweight','--model-version','v3_bayes_smoothed','--out',str(out/'comparison.json')]
    profiler=cProfile.Profile();profiler.enable()
    try:runpy.run_path(str(root/'analyzer_engine_runner.py'),run_name='__main__')
    finally:
        profiler.disable();profiler.dump_stats(str(out/'profile.pstats'))
        with (out/'profile.txt').open('w',encoding='utf-8') as stream:pstats.Stats(profiler,stream=stream).sort_stats('cumulative').print_stats(45)

if __name__=='__main__':main()
