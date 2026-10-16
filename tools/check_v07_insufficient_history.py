"""Actual native failure keeps partial evidence without inventing a prediction."""
import argparse
import json
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.app.resolve()))
    import analyzer_gui as gui
    from analyzer_support import atomic_json
    from analyzer_history import History
    errors=[]
    gui.messagebox.showerror=lambda *a,**kw:errors.append(str(a))
    gui.messagebox.showinfo=lambda *a,**kw:None
    gui.enable_dpi_awareness()
    window=gui.tk.Tk();app=gui.AnalyzerApp(window)
    def wait():
        until=time.monotonic()+300
        while time.monotonic()<until:
            window.update()
            if not app.controller.busy:return
            time.sleep(.04)
        raise TimeoutError(app.status.get())
    try:
        window.update();wait();assert app.ready
        history=History(args.app).directory
        before={p.name:p.read_bytes() for p in history.glob('*.json')}
        app.division.set('Women — Bantamweight');app.change_division()
        app.names['a'].set('Ronda Rousey');app.names['b'].set('Liz Carmouche');app.date.set('2013-03-01')
        request=app.prediction_request(1);request.update(force_recalculate=True,use_cache=False)
        app.start(request);wait()
        assert errors and app.result['result_state']=='failed'
        assert app.result.get('evidence_quality')
        assert not any(k in app.result for k in ('fighter_a_win_probability','fighter_b_win_probability','predicted_winner'))
        assert before=={p.name:p.read_bytes() for p in history.glob('*.json')}
        text=app.result_text
        assert 'no completed prediction' in text.lower()
        app.copy();window.update();assert window.clipboard_get()==text
        atomic_json(args.out,dict(status='PASS',result_state=app.result['result_state'],probability_absent=True,
            evidence_preserved=True,partial_kind='initial' if app.result.get('quick_comparison') else 'advanced',
            history_unchanged=True,partial_copy_matches=True,error=errors))
        print('Insufficient-history native failure PASS',flush=True)
    finally:
        app.controller.terminate();app.destroy()


if __name__=='__main__':
    main()
