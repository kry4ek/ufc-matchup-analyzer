"""Beginner setup, usable on every supported Python platform."""
from __future__ import annotations
import argparse, os, pathlib, struct, subprocess, sys, venv
from analyzer_support import ROOT, ensure_data

def supported():return sys.version_info[:2]==(3,14) and struct.calcsize('P')==8

def main():
    p=argparse.ArgumentParser(description='Set up UFC Matchup Analyzer with 64-bit Python 3.14.')
    p.add_argument('--dataset-archive',type=pathlib.Path);p.add_argument('--wheelhouse',type=pathlib.Path,help='Optional folder of locked wheels for offline setup')
    p.add_argument('--check-only',action='store_true');a=p.parse_args()
    if not supported():print('ERROR: 64-bit Python 3.14 required. Install it from https://www.python.org/downloads/',file=sys.stderr);return 1
    if a.check_only:print('Supported Python: '+sys.version.split()[0]);return 0
    try:
        ensure_data(archive=a.dataset_archive)
        directory=ROOT/'.venv';interpreter=directory/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if interpreter.exists():
            result=subprocess.run([str(interpreter),'-I','-c','import sys,struct;sys.exit(0 if sys.version_info[:2]==(3,14) and struct.calcsize("P")==8 else 1)'])
            if result.returncode:raise RuntimeError('Existing .venv is incompatible. Rename/remove only .venv, then rerun setup.')
        else:
            print('Creating project-local Python environment …',flush=True);venv.EnvBuilder(with_pip=True).create(directory)
        cmd=[str(interpreter),'-m','pip','install','--only-binary=:all:','-r',str(ROOT/'requirements.lock')]
        if a.wheelhouse:cmd+=['--no-index','--find-links',str(a.wheelhouse.resolve())]
        subprocess.run(cmd,check=True,cwd=ROOT)
        subprocess.run([str(interpreter),'-m','pip','check'],check=True,cwd=ROOT)
        subprocess.run([str(interpreter),str(ROOT/'ufc_matchup_analyzer.py'),'doctor'],check=True,cwd=ROOT)
        print('\nSetup complete. On Windows double-click run.bat. On macOS/Linux run .venv/bin/python ufc_matchup_analyzer.py')
        return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:print('ERROR: '+str(exc),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
