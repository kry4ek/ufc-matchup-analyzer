"""Verify the HTML action in this process's real Windows Save dialog."""
import argparse,ctypes,json,sys,time
from pathlib import Path
import analyzer_gui as gui
from analyzer_results import result_filename,format_result
from analyzer_support import atomic_json
from analyzer_reporting import format_html

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fixture',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    sys.path.append(str(Path(__file__).resolve().parent))
    # Import the dialog inspection helpers without executing their QA main body.
    helper=Path(__file__).with_name('check_native_save.py').read_text();namespace={}
    exec(helper[:helper.index('parser=argparse.ArgumentParser();')],namespace)
    user=namespace['user'];user.GetParent.argtypes=[ctypes.c_void_p];user.GetParent.restype=ctypes.c_void_p
    class Idle:
        busy=False;cancellable=False;started=0
        def poll(self):return []
    args.out.parent.mkdir(parents=True,exist_ok=True);gui.enable_dpi_awareness();window=gui.tk.Tk();app=gui.AnalyzerApp(window,controller=Idle(),autostart=False)
    payload=json.loads(args.fixture.read_text());app.display_result(payload);app.preferences['save_directory']=str(args.out.parent.resolve())
    started=time.monotonic();observations=[];errors=[]
    def operate():
        try:
            for dialog in namespace['dialogs']():
                controls=namespace['children'](dialog)
                expected=Path(result_filename(payload)).with_suffix('.html').name
                if any(c['kind']=='Edit' and c['text']==expected for c in controls):
                    assert any(c['kind']=='ComboBox' and 'HTML report' in c['text'] for c in controls),controls
                    observations.append('Native HTML filename and file type confirmed')
                    user.PostMessageW(dialog,0x111,1,0);return
            if time.monotonic()-started>20:raise AssertionError('Could not select the native HTML file type')
            window.after(100,operate)
        except Exception as exc:
            errors.append(str(exc))
            for dialog in namespace['dialogs']():user.PostMessageW(dialog,0x111,2,0)
    try:
        window.after(100,operate);app.save_menu.invoke(1);window.update();assert not errors,errors
        name=Path(result_filename(payload)).with_suffix('.html').name;destination=args.out.parent/name
        assert destination.exists(),('Native HTML choice did not produce .html',observations,list(args.out.parent.glob('*')))
        assert destination.read_text(encoding='utf-8')==format_html(payload)
        atomic_json(args.out,dict(status='PASS',observations=observations,filename=name,utf8_complete_html=True))
    finally:app.destroy()

if __name__=='__main__':main()
