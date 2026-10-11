"""Structured engine events. Human-readable engine logs are never parsed."""
from __future__ import annotations
import json
import os
from pathlib import Path
import time

_last = time.monotonic()
_stage = None
TIMINGS = {}
_emitted = {}
MAX_RECORD_BYTES = 65536

def validated_progress(event):
    """Allow only progress fields; children never supply worker identity or terminals."""
    if not isinstance(event, dict) or event.get('type', 'progress') != 'progress': return None
    if event.get('stage') in ('committing','complete'):return None
    result = {}
    for field in ('stage', 'message', 'target', 'phase', 'unit', 'detail'):
        if isinstance(event.get(field), str): result[field] = event[field][:2000]
    if not result.get('message'): return None
    for current, total in (('completed', 'total'), ('step_index', 'step_count')):
        a, b = event.get(current), event.get(total)
        if type(a) is int and type(b) is int and b > 0 and 0 <= a <= b:
            result[current], result[total] = a, b
    result['cancellable'] = True
    return result

class EventReader:
    """Incremental newline framing with bounded memory and partial UTF-8 support."""
    def __init__(self, path):
        self.path = Path(path); self.offset = 0; self.buffer = b''; self.discarding = False

    def read(self):
        result = []
        try:
            with self.path.open('rb') as stream:
                stream.seek(self.offset)
                while raw := stream.read(MAX_RECORD_BYTES):
                    self.offset += len(raw)
                    parts = (self.buffer+raw).split(b'\n'); self.buffer = parts.pop()
                    for line in parts:
                        if self.discarding:
                            self.discarding = False; continue
                        if len(line) > MAX_RECORD_BYTES: continue
                        try:
                            event = json.loads(line.decode('utf-8'))
                            if isinstance(event, dict): result.append(event)
                        except (ValueError, UnicodeError): pass
                    if len(self.buffer) > MAX_RECORD_BYTES:
                        self.buffer = b''; self.discarding = True
        except FileNotFoundError: pass
        return result

def emit(event_type='progress', **payload):
    global _last, _stage
    now = time.monotonic()
    if event_type == 'progress' and payload.get('stage') != _stage:
        if _stage:
            TIMINGS[_stage] = TIMINGS.get(_stage, 0) + now - _last
        _stage = payload.get('stage')
        _last = now
    path = os.environ.get('UFC_ENGINE_EVENTS')
    if path:
        with Path(path).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(type=event_type, **payload), ensure_ascii=False, allow_nan=False) + '\n')

def progress(stage, message, **kwargs):
    from numbers import Integral
    for field in ('completed','total','step_index','step_count'):
        if isinstance(kwargs.get(field), Integral):kwargs[field]=int(kwargs[field])
    identity = (stage, kwargs.get('phase'), kwargs.get('unit'))
    now = time.monotonic()
    forced = kwargs.pop('force', False)
    boundary = kwargs.get('completed') in (0, kwargs.get('total')) or forced
    if not boundary and now-_emitted.get(identity, 0) < .25: return
    _emitted[identity] = now
    emit(stage=stage, message=message, cancellable=True, **kwargs)

def source_failure(exc):
    """Updater entry points classify exception types, independent of display text."""
    import requests
    from analyzer_errors import MaintenanceError
    fetch = isinstance(exc, requests.exceptions.RequestException)
    code = 'source_fetch_failed' if fetch else 'source_malformed' if isinstance(exc, ValueError) else 'subprocess_failed'
    error = MaintenanceError(code, 'Could not download source data' if fetch else 'The source capture could not finish',
        'The source request failed.' if fetch else 'The updater could not safely read the completed event data.',
        'Check your internet connection and try again.' if fetch else 'Open details to inspect the source capture.', retryable=fetch)
    path = os.environ.get('UFC_ENGINE_ERROR')
    if path:Path(path).write_text(json.dumps(error.payload(),ensure_ascii=False),encoding='utf-8')
