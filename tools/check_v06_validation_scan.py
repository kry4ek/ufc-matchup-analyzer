"""Compare metadata scans without weakening the separate content hash checks."""
import argparse
import importlib.util
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import csv_info,manifest,atomic_json,digest

def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline-module',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    spec=importlib.util.spec_from_file_location('original_metadata_validation',args.baseline_module);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    report=dict(status='RUNNING',runs=[])
    for repetition in range(3):
        values={}
        for name,fn in [('old',old.csv_info),('new',csv_info)] if repetition%2==0 else [('new',csv_info),('old',old.csv_info)]:
            started=time.monotonic();values[name]=[fn(ROOT/e['path']) for e in manifest()['files']]
            seconds=time.monotonic()-started;report['runs'].append(dict(repetition=repetition+1,method=name,seconds=round(seconds,3)));atomic_json(args.out,report)
        assert values['old']==values['new'],'Metadata scan changed validation semantics'
    for entry in manifest()['files']:assert digest(ROOT/entry['path'])==entry['sha256']
    report['medians']={name:statistics.median(r['seconds'] for r in report['runs'] if r['method']==name) for name in ('old','new')}
    report.update(status='PASS',scope='All 15 CSV metadata results identical; all source hashes preserved. OS file cache may be warm.')
    atomic_json(args.out,report)
if __name__=='__main__':main()
