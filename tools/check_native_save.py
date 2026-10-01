"""Control only the native Save dialogs owned by this QA process."""
import argparse,ctypes,json,os,sys,time,threading
from ctypes import wintypes as wt
from pathlib import Path
import analyzer_gui as gui
from analyzer_results import format_result,result_filename
from analyzer_support import atomic_json

user=ctypes.WinDLL('user32',use_last_error=True)
CALLBACK=ctypes.WINFUNCTYPE(wt.BOOL,wt.HWND,wt.LPARAM)
user.GetWindowThreadProcessId.argtypes=[wt.HWND,ctypes.POINTER(wt.DWORD)]
user.GetClassNameW.argtypes=[wt.HWND,wt.LPWSTR,ctypes.c_int]
user.GetWindowTextW.argtypes=[wt.HWND,wt.LPWSTR,ctypes.c_int]
user.GetDlgCtrlID.argtypes=[wt.HWND]
user.SendMessageW.argtypes=[wt.HWND,wt.UINT,wt.WPARAM,wt.LPARAM]
user.SendMessageW.restype=wt.LPARAM
user.EnumWindows.argtypes=[CALLBACK,wt.LPARAM]
user.EnumChildWindows.argtypes=[wt.HWND,CALLBACK,wt.LPARAM]
user.PostMessageW.argtypes=[wt.HWND,wt.UINT,wt.WPARAM,wt.LPARAM]
def text(hwnd,method):
    buffer=ctypes.create_unicode_buffer(2048);method(hwnd,buffer,len(buffer));return buffer.value
def dialogs():
    found=[]
    @CALLBACK
    def collect(hwnd,_):
        pid=wt.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value==os.getpid() and text(hwnd,user.GetClassNameW)=='#32770':found.append(hwnd)
        return True
    user.EnumWindows(collect,0);return found
def children(hwnd):
    found=[]
    @CALLBACK
    def collect(child,_):
        found.append(dict(hwnd=child,kind=text(child,user.GetClassNameW),id=user.GetDlgCtrlID(child),text=text(child,user.GetWindowTextW)));return True
    user.EnumChildWindows(hwnd,collect,0);return found
class Idle:
    busy=False;cancellable=False;started=0
    def poll(self):return []

parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--fixture',type=Path,required=True);args=parser.parse_args()
out=args.out
if out.parent.exists() and any(out.parent.iterdir()):raise ValueError('Choose a new, empty QA output folder')
out.parent.mkdir(parents=True,exist_ok=True)
gui.enable_dpi_awareness();window=gui.tk.Tk();app=gui.AnalyzerApp(window,controller=Idle(),autostart=False)
payload=json.loads(args.fixture.read_text(encoding='utf-8'));payload['fighter_a']='José Test';app.result=payload;app.result_text=format_result(payload)
app.preferences['save_directory']=str(out.parent.resolve());window.update()
filename=result_filename(payload);expected=app.result_text;saved=out.parent/filename
report=dict(status='RUNNING',checks=[])
try:
    for scenario in ('save','overwrite-cancel','cancel'):
        observed=[];failures=[];start=time.monotonic();phase=[0];finished=threading.Event()
        def operate():
            try:
                current=dialogs()
                if not current:
                    if time.monotonic()-start>20:raise RuntimeError('Native Save dialog did not appear')
                    return
                for dialog in current:
                    controls=children(dialog)
                    edits=[x for x in controls if x['kind']=='Edit']
                    if phase[0]==0 and edits:
                        matching=next((x for x in edits if filename in x['text']),None)
                        if matching is None:raise AssertionError(('Save default missing',[(x['id'],x['text']) for x in edits]))
                        observed.append('default filename confirmed')
                        if scenario=='cancel':user.PostMessageW(dialog,0x111,2,0);phase[0]=2;return
                        # The dialog already points at our dedicated QA folder.
                        user.PostMessageW(dialog,0x111,1,0);phase[0]=1
                        if scenario=='save':return
                        return
                    if scenario=='overwrite-cancel' and phase[0]==1:
                        no_button=next((x for x in controls if x['kind']=='Button' and x['text'].replace('&','').casefold()=='no'),None)
                        if no_button:
                            observed.append('native overwrite confirmation displayed')
                            user.PostMessageW(no_button['hwnd'],0xf5,0,0);phase[0]=2;return
                    elif scenario=='overwrite-cancel' and phase[0]==2 and edits:
                        user.PostMessageW(dialog,0x111,2,0);phase[0]=3;return
                if time.monotonic()-start>20:raise RuntimeError('Native dialog did not reach expected state')
            except Exception as exc:
                failures.append(str(exc))
                for dialog in dialogs():
                    for control in children(dialog):
                        if control['kind']=='Button' and control['text'].replace('&','').casefold()=='no':user.PostMessageW(control['hwnd'],0xf5,0,0)
                    user.PostMessageW(dialog,0x111,2,0)
        def loop():
            time.sleep(.5)
            while not finished.is_set():
                operate();time.sleep(.2)
        before=saved.read_bytes() if saved.exists() else None
        thread=threading.Thread(target=loop,daemon=True);thread.start();app.save();finished.set();thread.join(5)
        assert not failures,failures
        assert observed,scenario
        if scenario=='save':
            assert saved.read_text(encoding='utf-8')==expected
            assert b'Jos\xc3\xa9 Test' in saved.read_bytes()
            saved.write_text('keep original',encoding='utf-8')
        else:assert saved.read_bytes()==before
        report['checks'].append(dict(scenario=scenario,observations=observed,status='PASS'))
        atomic_json(out,report)
    report['status']='PASS';atomic_json(out,report);print('Native Save default, UTF-8 output, overwrite decline, and Cancel PASS')
finally:
    for dialog in dialogs():user.PostMessageW(dialog,0x10,0,0)
    app.destroy()
