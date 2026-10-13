"""Cancel a real worker after initial evidence and verify its partial reports."""
import argparse
import json
from pathlib import Path
import sys
import time

def main():
    p=argparse.ArgumentParser();p.add_argument('--app-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    root=args.app_root.resolve();sys.path.insert(0,str(root))
    from analyzer_controller import WorkerController
    from analyzer_results import format_result
    from analyzer_reporting import format_html
    from analyzer_support import atomic_json
    from analyzer_history import History
    results=[]
    for sex,names,division in [('men',('Islam Makhachev','Justin Gaethje'),'Lightweight'),('women',('Valentina Shevchenko','Manon Fiorot'),'Flyweight')]:
        controller=WorkerController(root);started=time.monotonic();initial=None;terminal=None;cancelled=False
        controller.start(dict(operation='predict',sex=sex,fighter_a=names[0],fighter_b=names[1],division=division,fight_date='2026-10-10',workers=1))
        try:
            while controller.busy and time.monotonic()-started<120:
                for event in controller.poll():
                    if event['type']=='initial_ready':initial=event['payload'];initial_seen=time.monotonic()-started
                    if event['type'] in ('error','result'):terminal=event
                if initial and not cancelled and controller.cancellable:cancelled=controller.cancel()
                time.sleep(.03)
            assert not controller.busy and initial and cancelled,(sex,terminal)
            assert terminal['type']=='error' and terminal['code']=='cancelled',terminal
            initial['result_state']='cancelled';text=format_result(initial);html=format_html(initial)
            assert 'partial evidence' in text and 'cancelled' in text and not initial.get('fighter_a_win_probability')
            assert all(r['event_date']<'2026-10-10' for side in ('fighter_a','fighter_b') for r in initial['recent_fights'][side])
            assert not History(root).entries()
            results.append(dict(sex=sex,initial_seen_seconds=round(initial_seen,3),request_time_to_initial=initial['time_to_initial_seconds'],cancelled_partial_export='PASS'))
            atomic_json(args.out,dict(status='RUNNING',runs=results,measurement_scope='Functional cancellation check; other evaluation work may be running.'))
        finally:controller.terminate()
    atomic_json(args.out,dict(status='PASS',runs=results,measurement_scope='Functional cancellation check; other evaluation work may be running.'))
if __name__=='__main__':main()
