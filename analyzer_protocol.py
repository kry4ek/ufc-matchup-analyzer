"""Structured engine events. Human-readable engine logs are never parsed."""
from __future__ import annotations
import json
import os
from pathlib import Path
import time

_last = time.monotonic()
_stage = None
TIMINGS = {}

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
    emit(stage=stage, message=message, cancellable=True, **kwargs)
