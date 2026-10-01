"""Real portable GUI maintenance checks on a disposable extracted ZIP."""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import threading
import time
import analyzer_gui as gui
from analyzer_support import ROOT,atomic_json,manifest

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--resume',action='store_true',help='Retain completed live/rebuild/recovery evidence and repeat later checks');args=p.parse_args()
    dialogs=[];gui.messagebox.showinfo=lambda *a,**k:dialogs.append(('info',str(a)));gui.messagebox.showerror=lambda *a,**k:dialogs.append(('error',str(a)));gui.messagebox.askyesno=lambda *a,**k:True
    gui.enable_dpi_awareness();window=gui.tk.Tk();app=gui.AnalyzerApp(window)
    report=json.loads(args.out.read_text()) if args.resume else dict(status='RUNNING',checks=[])
    stop_monitor=threading.Event();disk_peak=[0]
    def disk_monitor():
        while not stop_monitor.is_set():
            total=0
            for path in (ROOT/'.runtime').rglob('*'):
                try:
                    if path.is_file():total+=path.stat().st_size
                except OSError:pass
            disk_peak[0]=max(disk_peak[0],total)
            stop_monitor.wait(.25)
    monitor=threading.Thread(target=disk_monitor,daemon=True);monitor.start()
    def hashes():return {x['path']:hashlib.sha256((ROOT/x['path']).read_bytes()).hexdigest() for x in manifest()['files']}
    def wait(timeout=1800):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            window.update()
            if not app.controller.busy:
                if app.controller.process is None:time.sleep(.05);continue
                events=[json.loads(line) for line in app.controller.events_path.read_text(encoding='utf-8').splitlines()]
                terminal=[event for event in events if event['type'] in ('result','error')]
                if terminal:return terminal[-1]
            time.sleep(.05)
        raise TimeoutError(app.status.get())
    def operation(request):
        dialogs.clear();start=time.monotonic();app.start(request);event=wait();event['seconds']=round(time.monotonic()-start,2);return event
    def record(name,event):
        report['checks'].append(dict(name=name,type=event['type'],seconds=event.get('seconds'),status=event.get('payload',{}).get('status'),message=event.get('message'),summary=event.get('payload',{}).get('summary')))
        report['peak_additional_runtime_bytes']=max(disk_peak[0],report.get('peak_additional_runtime_bytes',0))
        report['disk_sampling_seconds']=.25
        atomic_json(args.out,report)
    server=None
    try:
        window.update();time.sleep(.1);window.update();initial=wait();assert initial['type']=='result' and initial['payload']['ready'],initial
        before=hashes()
        if args.resume:
            names={c['name'] for c in report['checks'] if c['type']=='result'}
            assert {'bounded live update','full local rebuild','GUI restore previous datasets'}<=names
            assert before=={item['path']:item['sha256'] for item in manifest()['files']},'Resume requires the exact restored snapshot'
            report['resumed_completed_maintenance_evidence']=True
        else:
            live=operation(dict(operation='update',max_events=1,from_date='2026-09-26'))
            record('bounded live update',live)
            assert live['type']=='result' and live['payload']['ready'],live
            if live['payload']['status']=='committed':
                undo=operation(dict(operation='recover'));assert undo['type']=='result' and undo['payload']['ready'],undo
            assert hashes()==before
            rebuild=operation(dict(operation='rebuild'));record('full local rebuild',rebuild)
            assert rebuild['type']=='result' and rebuild['payload']['ready'],rebuild
            app.restore();restored=wait();record('GUI restore previous datasets',restored)
            assert restored['type']=='result' and restored['payload']['ready'],restored
            assert hashes()==before,'Recovery did not restore every original dataset hash'
        for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):os.environ[name]='http://127.0.0.1:9'
        os.environ['NO_PROXY']=''
        failure=operation(dict(operation='update',max_events=1));record('actual network failure',failure)
        assert failure['type']=='error' and hashes()==before,failure
        class Malformed(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.end_headers();self.wfile.write(b'<html><body>malformed completed events page</body></html>')
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Malformed);threading.Thread(target=server.serve_forever,daemon=True).start()
        for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):os.environ[name]=f'http://127.0.0.1:{server.server_port}'
        failure=operation(dict(operation='update',max_events=1));record('actual malformed source page',failure)
        assert failure['type']=='error' and hashes()==before,failure
        dialogs.clear();app.division.set('Men — Lightweight');app.change_division();app.names['a'].set('Islam Makhachev');app.names['b'].set('Justin Gaethje');app.date.set('2026-10-10')
        request=app.prediction_request();request.update(use_cache=False,force_recalculate=True);app.start(request)
        deadline=time.monotonic()+90
        while not app.controller.cancellable and app.controller.busy and time.monotonic()<deadline:window.update();time.sleep(.05)
        assert app.controller.cancellable;app.cancel();cancelled=wait();record('real GUI analysis cancellation',cancelled)
        assert cancelled['type']=='error' and cancelled['code']=='cancelled' and hashes()==before,cancelled
        doctor=operation(dict(operation='doctor'));record('post-failure installation check',doctor)
        assert doctor['type']=='result' and doctor['payload']['ready'],doctor
        report.update(status='PASS',all_original_hashes_restored=True,peak_additional_runtime_bytes=max(disk_peak[0],report.get('peak_additional_runtime_bytes',0)),disk_sampling_seconds=.25);atomic_json(args.out,report)
    finally:
        stop_monitor.set();monitor.join(5)
        if server:server.shutdown();server.server_close()
        if app.controller.busy:app.controller.terminate()
        app.destroy()

if __name__=='__main__':main()
