"""Observe only the new package's native window and startup worker result."""
import argparse
import ctypes
from ctypes import wintypes as wt
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--package',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--cleanup-only',action='store_true');args=parser.parse_args()
    package=args.package.resolve();user=ctypes.WinDLL('user32');kernel=ctypes.WinDLL('kernel32')
    callback_type=ctypes.WINFUNCTYPE(wt.BOOL,wt.HWND,wt.LPARAM)
    user.EnumWindows.argtypes=[callback_type,wt.LPARAM];user.IsWindowVisible.argtypes=[wt.HWND]
    user.GetWindowThreadProcessId.argtypes=[wt.HWND,ctypes.POINTER(wt.DWORD)]
    user.PostMessageW.argtypes=[wt.HWND,wt.UINT,wt.WPARAM,wt.LPARAM]
    kernel.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD];kernel.OpenProcess.restype=wt.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wt.HANDLE,wt.DWORD,wt.LPWSTR,ctypes.POINTER(wt.DWORD)]
    kernel.CloseHandle.argtypes=[wt.HANDLE]
    def windows():
        found=[]
        @callback_type
        def inspect(hwnd,_):
            if not user.IsWindowVisible(hwnd):return True
            pid=wt.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid));handle=kernel.OpenProcess(0x1000,False,pid.value)
            if handle:
                try:
                    text=ctypes.create_unicode_buffer(32768);length=wt.DWORD(len(text))
                    if kernel.QueryFullProcessImageNameW(handle,0,text,ctypes.byref(length)):
                        path=Path(text.value).resolve()
                        if path.is_relative_to(package) and path.name.lower()=='pythonw.exe':found.append(hwnd)
                finally:kernel.CloseHandle(handle)
            return True
        user.EnumWindows(inspect,0);return found
    if args.cleanup_only:
        deadline=time.monotonic()+20
        while windows() and time.monotonic()<deadline:
            for hwnd in reversed(windows()):user.PostMessageW(hwnd,0x10,0,0)
            time.sleep(.2)
        if windows():raise RuntimeError('Owned EXE window still open')
        print('Owned launcher window closed; CLI/native QA processes untouched',flush=True);return
    args.out.unlink(missing_ok=True)
    start=time.monotonic();wall=time.time();first=None;report=None;record=None
    subprocess.Popen([str(package/'UFC Matchup Analyzer.exe')],cwd=package)
    try:
        while time.monotonic()-start<180:
            if windows() and first is None:first=time.monotonic()-start
            for path in (package/'app/.runtime/jobs').glob('*.jsonl'):
                if path.stat().st_mtime<wall-1:continue
                for line in path.read_text(encoding='utf-8').splitlines():
                    try:value=json.loads(line)
                    except ValueError:continue
                    if value.get('type')=='error':raise ValueError(value.get('message'))
                    if value.get('type')=='result' and value.get('operation')=='startup':report=value['payload']
            if report is not None:break
            time.sleep(.05)
        if not report or not report.get('ready') or first is None:raise ValueError('Native package did not become ready with a visible owned window')
        assert report['version']=='0.8.0'
        record=dict(status='PASS',first_visible_seconds=first,compute_ready_seconds=time.monotonic()-start,version=report['version'],
            scope='Actual native EXE on the available Windows computer; separate writable folder. Not a clean OS or alternative physical DPI test.')
        # A worker writes its result just before exit. Let Tk consume the terminal
        # event before asking it to close a formerly non-cancellable startup.
        time.sleep(.75)
    finally:
        for hwnd in windows():user.PostMessageW(hwnd,0x10,0,0)
        deadline=time.monotonic()+20
        while windows() and time.monotonic()<deadline:time.sleep(.1)
        if windows():raise RuntimeError('Owned application window did not close gracefully')
    if record:
        record['closed_gracefully']=True;atomic_json(args.out,record)
        print('Native EXE ready and closed; first window %.3f s'%first,flush=True)
if __name__=='__main__':main()
