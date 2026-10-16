"""Run a parent predictor with explicit import paths under embedded Python."""
import argparse
from pathlib import Path
import runpy
import sys

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--baseline',action='store_true')
    a,rest=p.parse_known_args()
    directory=a.parent/'womens_ufc_model'
    source=(a.parent/'work/v07-research-baseline/womens_ufc_model/predict_matchup_advanced.py'
            if a.baseline else directory/'predict_matchup_advanced.py')
    sys.path.insert(0,str(directory.resolve()))
    sys.argv=[str(source),*rest]
    runpy.run_path(str(source),run_name='__main__')

if __name__=='__main__':main()
