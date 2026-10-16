"""Capture the native Overview with populated frozen evidence."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from capture_window import capture

class Idle:
    busy=False;cancellable=False;started=0
    def poll(self):return []

def main():
    p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--size',choices=['Small','Medium','Large'],default='Medium')
    p.add_argument('--app',type=Path)
    p.add_argument('--view',choices=['overview','comparison','recent','visual','report'],default='overview');a=p.parse_args()
    if a.app:sys.path.insert(0,str(a.app.resolve()))
    import analyzer_gui as gui
    folder=tempfile.TemporaryDirectory()
    root=a.app.resolve() if a.app else Path(folder.name)
    preferences=root/'.runtime/ui_preferences.json'
    original=preferences.read_bytes() if preferences.exists() else None
    gui.enable_dpi_awareness();window=gui.tk.Tk()
    app=gui.AnalyzerApp(window,root=root,controller=Idle(),autostart=False)
    try:
        payload=json.loads(a.fixture.read_text(encoding='utf-8'))
        sex=payload['calculation_request']['sex']
        if a.app:
            from analyzer_catalog import FighterCatalog
            app.catalogs[sex]=FighterCatalog(sex,root)
        app.division.set(('Women' if sex=='women' else 'Men')+' — '+payload['division'].replace("Women's ",''))
        app.change_division();app.date.set(payload['fight_date'])
        for side in ('a','b'):
            name=payload['fighter_'+side];identity=payload.get('fighter_'+side+'_id')
            if a.app:app.select_suggestion(side,(name,identity))
            else:app.names[side].set(name)
        window.geometry('1100x850');app.ready=bool(a.app);app.display_result(payload)
        if not app.collapsed:app.toggle_inputs()
        app.font_size.set(a.size);app.change_font()
        tab={'overview':app.overview,'comparison':app.comparison,'visual':app.visual_tab,'report':app.report_tab}.get(a.view)
        if a.view=='recent':tab=app.recent_tab
        app.notebook.select(tab);window.update()
        app.status.set('Saved analysis — frozen report')
        app.freshness.set('Saved dataset snapshot through '+str(payload['evidence_quality']['data_through']))
        app.overview_scroll.canvas.yview_moveto(0);window.update();capture(window,a.out)
    finally:
        app.destroy()
        if original is None:preferences.unlink(missing_ok=True)
        else:preferences.write_bytes(original)
        folder.cleanup()

if __name__=='__main__':main()
