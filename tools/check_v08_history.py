"""Near-capacity history stays responsive and opens only selected full payloads."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import analyzer_gui as gui
from analyzer_history import History,fingerprint
from analyzer_support import atomic_json
from tools.check_v08_ui import Idle,children

def main():
    result={};out=ROOT/'work/v0.8/history-ui.json'
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);history=History(root)
        payload=json.loads((ROOT/'work/v0.8/ui/men-fixture.json').read_text(encoding='utf-8'))
        for i in range(50):
            p=copy.deepcopy(payload);p['review_padding']='x'*850000;p['generated_at']=f'2026-10-15T12:00:{i:02d}+00:00'
            entry=dict(schema=1,id=uuid.uuid4().hex,created_at=p['generated_at'],request=p['calculation_request'],context={},cache_key=fingerprint(dict(request=p['calculation_request'],context={})),payload=p)
            entry['integrity']=fingerprint(entry);atomic_json(history.directory/(entry['id']+'.json'),entry)
        result['history_bytes']=sum(p.stat().st_size for p in history.directory.glob('*.json'))
        assert result['history_bytes']<=50*1024**2
        gui.enable_dpi_awareness();window=gui.tk.Tk();app=gui.AnalyzerApp(window,root,Idle(),False)
        try:
            window.update();start=time.monotonic();app.show_history();result['open_dialog_callback_seconds']=time.monotonic()-start
            dialog=[w for w in window.winfo_children() if isinstance(w,gui.tk.Toplevel)][-1]
            tree=next(w for w in children(dialog) if isinstance(w,gui.ttk.Treeview))
            intervals=[];last=time.monotonic();deadline=last+30
            while len(tree.get_children())!=50 and time.monotonic()<deadline:
                window.update();now=time.monotonic();intervals.append(now-last);last=now;time.sleep(.005)
            assert len(tree.get_children())==50
            result['max_event_loop_gap_seconds']=max(intervals)
            tree.selection_set(tree.get_children()[0]);start=time.monotonic()
            next(w for w in children(dialog) if isinstance(w,gui.ttk.Button) and w.cget('text')=='Open').invoke();window.update()
            result['open_selected_seconds']=time.monotonic()-start
            assert app.result and app.result['review_padding']==payload.get('review_padding','x'*850000)
            result['status']='PASS';atomic_json(out,result)
        finally:app.destroy()
    print(json.dumps(result),flush=True)
if __name__=='__main__':main()
