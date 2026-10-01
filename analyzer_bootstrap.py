"""Catch startup failures even when Tk cannot be imported by pythonw."""
import ctypes
import os
from pathlib import Path
import sys
import traceback

def main():
    sys.dont_write_bytecode=True
    root=Path(__file__).resolve().parent
    try:
        logs=root/'.runtime/logs';logs.mkdir(parents=True,exist_ok=True)
        with (logs/'gui-startup.log').open('w',encoding='utf-8',buffering=1) as stream:
            sys.stdout=sys.stderr=stream
            try:
                from analyzer_gui import main as gui_main
                return gui_main()
            except SystemExit as exc:
                return int(exc.code or 0)
            except BaseException:
                traceback.print_exc()
                raise
    except BaseException as exc:
        if os.name=='nt':ctypes.windll.user32.MessageBoxW(None,'The app could not start.\n\nExtract a fresh copy of the complete ZIP into a writable folder.\n\nDetails: '+str(exc)+'\n\nStartup log: app/.runtime/logs/gui-startup.log','UFC Matchup Analyzer',0x10)
        return 1

if __name__=='__main__':raise SystemExit(main())
