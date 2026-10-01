"""Nonblocking worker controller used by Tk and integration tests."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from analyzer_support import ROOT,atomic_json
from analyzer_runtime import ProcessTree,python_executable,subprocess_options,runtime_environment

class WorkerController:
    def __init__(self,root=ROOT):
        self.root=Path(root);self.process=None;self.tree=None;self.finished=True
        self.buffer='';self.offset=0;self.cancellable=False;self.started=0;self.terminal=False

    @property
    def busy(self):return self.process is not None and not self.finished

    def start(self,request):
        if self.busy:raise RuntimeError('An operation is already running.')
        directory=self.root/'.runtime/jobs';directory.mkdir(parents=True,exist_ok=True)
        identifier=time.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
        from analyzer_history import fingerprint
        self.job_id=identifier;self.request_fingerprint=fingerprint(request)
        request=dict(request,job_id=identifier,request_fingerprint=self.request_fingerprint)
        self.request_path=directory/(identifier+'.json');self.events_path=directory/(identifier+'.jsonl');self.cancel_path=directory/(identifier+'.cancel')
        atomic_json(self.request_path,request)
        env=runtime_environment(self.root)
        command=[python_executable(),str(self.root/'analyzer_worker.py'),'--request',str(self.request_path),'--events',str(self.events_path),'--cancel',str(self.cancel_path)]
        self.process=subprocess.Popen(command,cwd=self.root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**subprocess_options())
        self.tree=ProcessTree(self.process)
        self.finished=False;self.buffer='';self.offset=0;self.started=time.monotonic();self.terminal=False;self.cancellable=False;self.cancel_requested=False
        self.request=dict(request)

    def poll(self):
        if not self.busy:return []
        events=[]
        if self.events_path.exists():
            with self.events_path.open('rb') as stream:
                stream.seek(self.offset);chunk=stream.read();self.offset=stream.tell()
            # Decode complete UTF-8 lines only; a write can split a multibyte character.
            self.buffer+=chunk.hex()
            raw=bytes.fromhex(self.buffer)
            lines=raw.split(b'\n');self.buffer=lines.pop().hex()
            for line in lines:
                if not line:continue
                event=json.loads(line.decode('utf-8'));events.append(event)
                if event.get('job_id')!=self.job_id or event.get('request_fingerprint')!=self.request_fingerprint:
                    events.pop();continue
                if event['type']=='progress':self.cancellable=event.get('cancellable',self.cancellable) and not self.cancel_requested
                if event['type'] in ('result','error'):self.terminal=True
        if self.process.poll() is not None:
            # Re-read once after process termination, when every final write is visible.
            if not self.terminal and self.events_path.exists() and self.events_path.stat().st_size>self.offset:
                events+=self.poll()
                return events
            if not self.terminal:
                events.append(dict(type='error',code='worker_exit',message='The operation stopped unexpectedly. Use Help → Check installation before retrying.',log=str(self.root/'.runtime/logs')))
            self.finished=True;self.cancellable=False;self.tree.close()
        return events

    def cancel(self):
        if not self.busy or not self.cancellable:return False
        self.cancel_path.write_text('cancel',encoding='ascii')
        self.cancel_requested=True;self.cancellable=False
        return True

    def terminate(self):
        if self.busy:
            self.tree.terminate();self.tree.close();self.finished=True;self.cancellable=False
