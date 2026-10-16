"""Offline native UI review using frozen reports and disposable preferences."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import analyzer_gui as gui
from analyzer_support import atomic_json, digest
from tools.capture_window import capture


class Idle:
    busy=False;cancellable=False;started=0
    def poll(self):return []


def within(widget,parent,label):
    x=widget.winfo_rootx()-parent.winfo_rootx();y=widget.winfo_rooty()-parent.winfo_rooty()
    if not (x>=-1 and y>=-1 and x+widget.winfo_width()<=parent.winfo_width()+1 and y+widget.winfo_height()<=parent.winfo_height()+1):
        capture(parent,ROOT/'work/ui-polish/layout-failure.png')
        print('Layout failure:',label,flush=True)
    assert x>=-1 and y>=-1 and x+widget.winfo_width()<=parent.winfo_width()+1 and y+widget.winfo_height()<=parent.winfo_height()+1,(label,str(widget),x,y,widget.winfo_width(),widget.winfo_height(),parent.winfo_width(),parent.winfo_height())


def select_report(app,payload):
    sex=payload.get('calculation_request',{}).get('sex','men')
    division=payload.get('division','Lightweight').replace("Women's ",'')
    app.division.set(('Women' if sex=='women' else 'Men')+' — '+division);app.change_division()
    app.date.set(payload['fight_date'])
    for side in ('a','b'):app.names[side].set(payload['fighter_'+side])
    app.display_result(payload)
    app.ready=True;app.controls()
    app.freshness.set('Displayed snapshot through '+str(payload.get('evidence_quality',{}).get('data_through','not recorded')))


def main():
    p=argparse.ArgumentParser();p.add_argument('--men-fixture',type=Path,required=True);p.add_argument('--women-fixture',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    fixtures={sex:json.loads(path.read_text(encoding='utf-8')) for sex,path in [('men',args.men_fixture),('women',args.women_fixture)]}
    before=copy.deepcopy(fixtures);rows=[];native_scale=None
    gui.enable_dpi_awareness()
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        for percent in (100,125,150,200):
            window=gui.tk.Tk()
            if native_scale is None:native_scale=float(window.tk.call('tk','scaling'))
            window.tk.call('tk','scaling',(96/72)*percent/100)
            controller=Idle();app=gui.AnalyzerApp(window,root/str(percent),controller,False)
            try:
                select_report(app,fixtures['women'])
                # Test smaller displays even when the host has a large screen.
                minimum=window.minsize()
                for width,height in ((1366,768),(960,700)):
                    window.geometry(f'{max(width,minimum[0])}x{max(height,minimum[1])}+0+0')
                    for size in ('Small','Medium','Large'):
                        app.font_size.set(size);app.change_font()
                        for collapsed in (False,True):
                            if app.collapsed!=collapsed:app.toggle_inputs()
                            window.update();app.resize(type('Resize',(),{'widget':window})());window.update()
                            for tab in app.tabs.values():
                                app.notebook.select(tab);window.update()
                                for widget in (app.notebook,app.copy_button,app.save_button,app.input_toggle):within(widget,window,(percent,size,collapsed))
                                if tab is app.overview:
                                    within(app.overview_scroll,window,'Overview viewport')
                                    assert app.overview_scroll.canvas.winfo_height()>=40
                                    app.overview_scroll.reveal(type('Focus',(),{'widget':app.overview_tree})());window.update()
                                    app.overview_scroll.canvas.yview_moveto(1);window.update()
                                    assert app.overview_scroll.canvas.yview()[1]>.95
                                    app.overview_scroll.canvas.yview_moveto(0)
                                if tab is app.visual_tab:
                                    within(app.visual_panel.scroll,window,'Charts viewport')
                                    panel=app.visual_panel
                                    panel.trend.focus_set();window.update()
                                    panel.scroll.reveal(type('Focus',(),{'widget':panel.trend})());window.update()
                                    panel.step_point(1)
                                    if panel.point_positions:assert 'Bout ' in panel.inspection.get()
                                if tab is app.comparison:
                                    within(app.comparison_scroll,window,('Statistics viewport',percent,size,collapsed))
                                    app.comparison_scroll.reveal(type('Focus',(),{'widget':app.filter_entry})());window.update()
                                    within(app.filter_entry,app.comparison_scroll.canvas,'Metric filter')
                                    app.comparison_scroll.reveal(type('Focus',(),{'widget':app.details})());window.update()
                                    app.comparison_scroll.canvas.yview_moveto(1);window.update()
                                    assert app.comparison_scroll.canvas.yview()[1]>.95
                                    app.comparison_scroll.canvas.yview_moveto(0)
                            if not collapsed:
                                within(app.input_scroll,window,'Input viewport')
                                # Coverage can overflow; keyboard focus must scroll the controls into view.
                                for widget in app.name_boxes.values():
                                    app.input_scroll.reveal(type('Focus',(),{'widget':widget})());window.update()
                                    within(widget,app.input_scroll.canvas,'Input focus')
                            rows.append(dict(scale=percent,text=size,width=window.winfo_width(),height=window.winfo_height(),requested_width=width,requested_height=height,collapsed=collapsed,status='PASS'))
                # Running and commit-stage feedback at the smallest tested viewport.
                controller.busy=True;controller.started=time.monotonic();controller.cancellable=True;app.controls();window.update()
                assert app.cancel_button.winfo_viewable() and app.progress.winfo_viewable()
                within(app.cancel_button,window,'Cancel');within(app.progress,window,'Progress')
                controller.cancellable=False;app.controls();assert str(app.cancel_button['state'])=='disabled'
                controller.busy=False;app.controls()
            finally:controller.busy=False;app.destroy()
        # Native-display screenshots of both current frozen reports.
        window=gui.tk.Tk();window.tk.call('tk','scaling',native_scale);app=gui.AnalyzerApp(window,root/'screenshots',Idle(),False)
        try:
            window.geometry('1100x850+10+10')
            for sex,payload in fixtures.items():
                select_report(app,payload)
                if not app.collapsed:app.toggle_inputs()
                app.font_size.set('Medium');app.change_font()
                for name,tab in app.tabs.items():
                    app.notebook.select(tab);window.update()
                    app.status.set('Saved analysis · frozen report')
                    capture(window,args.out/f'{sex}-{name}.png')
                app.notebook.select(app.visual_tab);window.update()
                scroll=app.visual_panel.scroll
                scroll.canvas.yview_moveto(max(0,app.visual_panel.trend.winfo_y()-80)/max(1,scroll.content.winfo_height()));window.update()
                capture(window,args.out/f'{sex}-elo.png')
                app.notebook.select(app.overview);window.update()
                scroll=app.overview_scroll
                y=app.overview_tree.winfo_rooty()-scroll.content.winfo_rooty()
                scroll.canvas.yview_moveto(max(0,y-60)/max(1,scroll.content.winfo_height()));window.update()
                capture(window,args.out/f'{sex}-key-statistics.png')
            for name,callback in [('evidence',app.evidence_dialog),('history',app.show_history),('maintenance',app.maintenance_details)]:
                callback();window.update()
                dialogs=[w for w in window.winfo_children() if isinstance(w,gui.tk.Toplevel)]
                for dialog in dialogs:
                    capture(dialog,args.out/f'dialog-{name}.png');dialog.destroy()
        finally:app.destroy()
        # Reconstruct the baseline from the source snapshot taken before editing.
        old=ROOT/'work/ui-polish/before/analyzer_gui.py'
        if old.exists():
            spec=importlib.util.spec_from_file_location('ui_before',old);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            oldspec=importlib.util.spec_from_file_location('visual_before',old.with_name('analyzer_visuals.py'))
            oldvisual=importlib.util.module_from_spec(oldspec);oldspec.loader.exec_module(oldvisual)
            visual=sys.modules['analyzer_visuals'];sys.modules['analyzer_visuals']=oldvisual
            window=module.tk.Tk();window.tk.call('tk','scaling',native_scale);app=module.AnalyzerApp(window,root/'baseline',Idle(),False)
            try:
                window.geometry('1100x850+10+10')
                select_report(app,fixtures['women'])
                if not app.collapsed:app.toggle_inputs()
                for name,tab in [('overview',app.overview),('charts',app.visual_tab)]:
                    app.notebook.select(tab);window.update();capture(window,args.out/f'before-{name}.png')
            finally:app.destroy();sys.modules['analyzer_visuals']=visual
    assert fixtures==before,'Display mutated a frozen fixture'
    report=dict(status='PASS',layout_states=rows,fixture_hashes={str(p):digest(p) for p in (args.men_fixture,args.women_fixture)},
                method='Native Tk windows; scaling is simulated. Actual alternate Windows display scales were not changed.',
                screenshots=sorted(p.name for p in args.out.glob('*.png')))
    atomic_json(args.out/'verification.json',report)
    print(f'{len(rows)} layout states passed; both frozen reports unchanged.')


if __name__=='__main__':main()
