"""Stable maintenance errors and bounded, sanitized diagnostic text."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import re

@dataclass
class MaintenanceError(RuntimeError):
    code: str
    title: str
    message: str
    next_step: str = 'Open details to inspect the diagnostic log.'
    operation: str = ''
    stage: str = ''
    target: str = ''
    transaction_id: str = ''
    event_id: str = ''
    fight_id: str = ''
    event_name: str = ''
    fighter_a: str = ''
    fighter_b: str = ''
    retryable: bool = False
    installation_state: str = 'unchanged'
    diagnostics_path: str = ''
    audit_relative_path: str = ''

    def __post_init__(self):
        RuntimeError.__init__(self, self.message)

    def payload(self):
        return asdict(self)

STATES = {
    'unchanged': 'Your installed datasets are unchanged.',
    'rolled_back': 'Your previous datasets have been restored.',
    'committed': 'The validated datasets were installed.',
    'recovery_required': 'Dataset recovery is required. Use Help → Check installation before retrying.',
}

def diagnostic_text(error, version):
    """Copy only selected identifiers and a small log excerpt, never environment."""
    keys = ('code', 'operation', 'stage', 'target', 'transaction_id', 'event_id', 'fight_id', 'installation_state')
    lines = ['UFC Matchup Analyzer '+version] + [key+': '+str(error[key]) for key in keys if error.get(key)]
    path = Path(error.get('diagnostics_path') or '')
    try:
        if path.is_file():
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size-6000))
                lines += ['', stream.read(6000).decode('utf-8', errors='replace')]
    except OSError:
        lines.append('Diagnostic excerpt unavailable.')
    text = '\n'.join(lines)
    text = re.sub(r'(?i)(?:[A-Z]:[\\/](?:Users|Documents and Settings)[\\/])[^\\/\s]+', r'[drive]:\\Users\\[account]', text)
    text = re.sub(r'(?i)(authorization|api[_-]?key|password|token|secret)(\s*[:=]\s*)[^\s,;]+', r'\1\2[redacted]', text)
    text = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1[redacted]@', text)
    return text
