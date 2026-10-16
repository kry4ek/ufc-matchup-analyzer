"""Import/view/export/undo one genuine old report without modifying its source."""
import argparse
import copy
from pathlib import Path
import sys

def main():
    p=argparse.ArgumentParser();p.add_argument('--app',type=Path,required=True);p.add_argument('--previous',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(a.app.resolve()))
    from analyzer_migration import preview,apply,undo,source_root
    from analyzer_history import History
    from analyzer_support import atomic_json,digest
    from analyzer_results import format_result
    from analyzer_reporting import format_html
    import analyzer_gui as gui
    value=preview(a.app,a.previous)
    selected=next((row for row in value['rows'] if row['status']=='valid'),None)
    if selected is None:raise ValueError('No valid previous report available for the requested import check')
    entry=selected['entry'];source=source_root(a.previous)/'.runtime/history'/selected['name']
    before=digest(source);original=copy.deepcopy(entry['payload'])
    destination=History(a.app);prior={v['id'] for v in destination.entries()}
    apply(a.app,value['id'],selected_ids=[entry['id']])
    imported=destination.load(entry['id'])
    assert imported['payload']==original
    class Idle:
        busy=False;cancellable=False;started=0
        def poll(self):return []
    window=gui.tk.Tk();app=gui.AnalyzerApp(window,a.app,Idle(),False)
    try:
        app.display_result(imported['payload']);window.update()
        assert app.result==original
        assert 'Not recorded in this saved analysis' in app.recent_form_panel.caption.get()
        a.out.parent.mkdir(parents=True,exist_ok=True)
        (a.out.parent/'legacy.txt').write_text(format_result(app.result),encoding='utf-8')
        (a.out.parent/'legacy.html').write_text(format_html(app.result),encoding='utf-8')
    finally:app.destroy()
    undo(a.app)
    assert {v['id'] for v in destination.entries()}==prior
    assert digest(source)==before
    atomic_json(a.out,dict(status='PASS',source_unchanged=True,payload_unchanged=True,legacy_gaps_not_backfilled=True,offline_exports=True,undo_restored_destination=True))
    print('Genuine legacy import/view/export/undo PASS',flush=True)
if __name__=='__main__':main()
