"""Exercise the owned Tk window at simulated DPI scales, without OS changes."""
import argparse
from pathlib import Path
import time
import sys
import analyzer_gui as gui
from analyzer_support import atomic_json

class Idle:
    busy=False;cancellable=False;started=0
    def poll(self):return []

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--screenshots',type=Path);p.add_argument('--fixture',type=Path);args=p.parse_args()
    gui.enable_dpi_awareness();rows=[];actual_dpi=None
    for percent in (100,125,150,200):
        window=gui.tk.Tk();window.tk.call('tk','scaling',(96/72)*(percent/100))
        app=gui.AnalyzerApp(window,controller=Idle(),autostart=False)
        app.notebook.select(2)
        if args.fixture:
            import json
            payload=json.loads(args.fixture.read_text(encoding='utf-8'))
            app.display_result(payload)
            report=gui.format_result(payload)
            app.set_text(report+'\nHorizontal-scroll QA line: '+'x'*300+'\n')
        window.update();time.sleep(.1);window.update()
        assert app.output.cget('wrap')=='none'
        # Tk determines the horizontal range from the lines currently in view.
        if args.fixture:app.output.see('end');window.update()
        app.output.xview_moveto(1);window.update();right_view=app.output.xview()
        if args.fixture:
            assert right_view[0]>0,('horizontal scroll did not move',percent,right_view)
        app.output.xview_moveto(0);window.update();assert app.output.xview()[0]==0
        app.output.yview_moveto(0);window.update()
        if sys.platform=='win32':
            import ctypes
            actual_dpi=ctypes.windll.user32.GetDpiForWindow(window.winfo_id())
        width,height=window.winfo_width(),window.winfo_height()
        controls=[app.division_box,app.date_entry,*app.name_boxes.values(),app.analyze_button,app.cancel_button,app.update_button,app.copy_button,app.save_button,app.progress,app.output]
        for widget in controls:
            x=widget.winfo_rootx()-window.winfo_rootx();y=widget.winfo_rooty()-window.winfo_rooty()
            assert 0<=x and 0<=y and x+widget.winfo_width()<=width and y+widget.winfo_height()<=height,(percent,str(widget),x,y,width,height,widget.winfo_width(),widget.winfo_height())
        assert app.output.winfo_height()>=50,(percent,app.output.winfo_height())
        minimum=window.minsize();window.geometry(f'{minimum[0]}x{minimum[1]}')
        app.status.set('Operation failed. Diagnostic log: '+str(gui.ROOT/'.runtime/transactions/20260930T172503-test/logs/men-update.log'))
        window.update();time.sleep(.1);window.update()
        for widget in controls:
            x=widget.winfo_rootx()-window.winfo_rootx();y=widget.winfo_rooty()-window.winfo_rooty()
            assert x+widget.winfo_width()<=window.winfo_width() and y+widget.winfo_height()<=window.winfo_height(),('resized',percent,str(widget),x,y,window.winfo_width(),window.winfo_height(),widget.winfo_width(),widget.winfo_height())
        window.geometry(f'{width}x{height}');app.status.set('Checking installation…');window.update()
        if args.fixture:
            if not app.collapsed:app.toggle_inputs()
            for tab,widgets in [(app.overview,[app.overview_tree,app.probability]),(app.comparison,[app.comparison_tree,app.filter_entry,app.details])]:
                app.notebook.select(tab);window.update()
                for widget in widgets:
                    x=widget.winfo_rootx()-window.winfo_rootx();y=widget.winfo_rooty()-window.winfo_rooty()
                    assert 0<=x and 0<=y and x+widget.winfo_width()<=window.winfo_width() and y+widget.winfo_height()<=window.winfo_height(),('result tab',percent,str(widget))
                    assert widget.winfo_height()>15,('collapsed result view',percent,str(widget))
            for size in ('Small','Medium','Large'):
                app.font_size.set(size);app.change_font();window.update()
                assert app.comparison_tree.winfo_height()>50,('text size',percent,size)
            app.font_size.set('Medium');app.change_font();app.notebook.select(2);window.update()
        # Focus traversal uses ttk/Tk's actual keyboard navigation order.
        for box in [app.division_box,app.date_entry,*app.name_boxes.values()]:
            next_name=window.tk.call('tk_focusNext',str(box));assert next_name
        rows.append(dict(scale_percent=percent,width=width,height=height,output_height=app.output.winfo_height(),status='PASS'))
        if args.screenshots:
            sys.path.append(str(Path(__file__).resolve().parent))
            from capture_window import capture
            capture(window,args.screenshots/(str(percent)+'.png'))
        app.destroy()
    atomic_json(args.out,dict(status='PASS',native_display_dpi=actual_dpi,method='Tk scaling simulation on the current Windows display; not a change to Windows display scaling',scales=rows))
    print('Tk layout and focus traversal PASS at 100/125/150/200% simulations')

if __name__=='__main__':main()
