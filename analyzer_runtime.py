"""Local operation locking, cancellation and quiet subprocess lifecycle."""
from __future__ import annotations

import contextlib
import atexit
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from analyzer_support import ROOT,atomic_json


class Cancelled(RuntimeError):
    pass


_held = {}
_temp_aliases = {}

def windows_short_path(directory):
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetShortPathNameW.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD]
    buffer=ctypes.create_unicode_buffer(32768)
    return buffer.value if kernel.GetShortPathNameW(str(directory),buffer,len(buffer)) else ''

def _remove_alias(name,target):
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.DefineDosDeviceW.argtypes=[wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR]
    return kernel.DefineDosDeviceW(1|2|4|8,name,target)

def release_temp_aliases():
    for name,record in list(_temp_aliases.items()):
        if _remove_alias(name,record['target']):
            Path(record['record']).unlink(missing_ok=True)
            _temp_aliases.pop(name,None)

atexit.register(release_temp_aliases)

def ascii_temp_directory(directory):
    """joblib's resource-tracker IPC requires ASCII, even on Unicode Windows."""
    directory=Path(directory).resolve()
    if os.name!='nt' or str(directory).isascii():return str(directory)
    short=windows_short_path(directory)
    if short and short.isascii():return short
    # If 8.3 names are disabled, use a local DOS-device alias. Files still live
    # inside the app's own temp folder; this is not a mapped/network drive.
    import ctypes
    from ctypes import wintypes
    for name,record in _temp_aliases.items():
        if record['directory']==str(directory):return '\\\\.\\'+name+'\\'
    name='UFCMA_'+str(os.getpid())+'_'+uuid.uuid4().hex[:12]
    target='\\??\\'+('UNC\\'+str(directory)[2:] if str(directory).startswith('\\\\') else str(directory))
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.DefineDosDeviceW.argtypes=[wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR]
    if not kernel.DefineDosDeviceW(1|8,name,target):raise RuntimeError('Windows could not prepare the local worker folder. Try extracting the app into a simple local folder name.')
    record_path=directory.parent/'temp_aliases'/(name+'.json')
    record=dict(pid=os.getpid(),name=name,target=target,directory=str(directory),record=str(record_path))
    try:atomic_json(record_path,record)
    except OSError:
        _remove_alias(name,target);raise
    _temp_aliases[name]=record
    return '\\\\.\\'+name+'\\'

def cleanup_stale_temp_aliases(root,process_alive):
    if os.name!='nt':return
    import re
    expected=str((Path(root)/'.runtime/tmp').resolve())
    for path in (Path(root)/'.runtime/temp_aliases').glob('*.json'):
        record=json.loads(path.read_text(encoding='utf-8'))
        if not re.fullmatch(r'UFCMA_[0-9]+_[a-f0-9]{12}',record.get('name','')) or record.get('directory')!=expected:continue
        target='\\??\\'+('UNC\\'+expected[2:] if expected.startswith('\\\\') else expected)
        if record.get('target')==target and not process_alive(record.get('pid')):
            _remove_alias(record['name'],target);path.unlink(missing_ok=True)


@contextlib.contextmanager
def operation_lock(root=ROOT, operation='analysis'):
    """An OS lock survives crashes safely and is shared by CLI and GUI workers."""
    root = Path(root).resolve()
    identity = (os.getpid(), str(root))
    if identity in _held:
        yield
        return
    path = root / '.runtime/operation.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+b')
    locked = False
    try:
        if path.stat().st_size == 0:
            stream.write(b' ')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Another analysis or dataset operation is running in this app folder. Wait for it to finish.') from exc
        locked = True
        _held[identity] = stream
        stream.seek(1)
        stream.truncate()
        stream.write(json.dumps(dict(pid=os.getpid(), operation=operation)).encode())
        stream.flush()
        yield
    finally:
        if locked:
            stream.seek(1)
            stream.truncate()
            stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)
            _held.pop(identity, None)
        stream.close()


def python_executable():
    """pythonw drives Tk; command workers use python.exe with a hidden console."""
    path = Path(sys.executable)
    sibling = path.with_name('python.exe')
    return str(sibling if path.name.lower() == 'pythonw.exe' and sibling.exists() else path)


def subprocess_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}

def runtime_environment(root=ROOT):
    directory=Path(root)/'.runtime/tmp'
    directory.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    temp=ascii_temp_directory(directory)
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',TEMP=temp,TMP=temp,JOBLIB_TEMP_FOLDER=temp)
    return env


class ProcessTree:
    """A Windows job owns descendants; closing it also handles unexpected exits."""
    def __init__(self, process):
        self.process = process
        self.job = None
        if os.name != 'nt':
            return
        import ctypes
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO), ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if handle and kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) and kernel.AssignProcessToJobObject(handle, int(process._handle)):
            self.job, self.kernel = handle, kernel
        elif handle:
            kernel.CloseHandle(handle)

    def terminate(self):
        if self.job:
            self.kernel.TerminateJobObject(self.job, 130)
        elif os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **subprocess_options())
        else:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)
        if self.job:
            # TerminateJobObject is asynchronous. Wait for descendants as well as
            # the direct child before reporting cancellation to the user.
            import ctypes
            import struct
            accounting=ctypes.create_string_buffer(48)
            deadline=time.monotonic()+10
            while self.kernel.QueryInformationJobObject(self.job,1,accounting,48,None):
                if struct.unpack_from('<I',accounting.raw,40)[0]==0:break
                if time.monotonic()>=deadline:raise RuntimeError('Windows has not finished stopping the worker processes. Wait before retrying.')
                time.sleep(.05)

    def close(self):
        if self.job:
            self.kernel.CloseHandle(self.job)
            self.job = None


def check_cancel(cancel=None):
    if cancel and cancel():
        raise Cancelled('Cancelled. Your installed datasets were not changed.')


def run_logged_process(command, cwd, log, cancel=None, timeout=1800):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    env = runtime_environment()
    env['LOKY_MAX_CPU_COUNT']='1'
    check_cancel(cancel)
    with log.open('w', encoding='utf-8') as stream:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, **subprocess_options())
        tree = ProcessTree(process)
        started = time.monotonic()
        try:
            while process.poll() is None:
                check_cancel(cancel)
                if time.monotonic() - started > timeout:
                    raise RuntimeError('This step took too long. Check your connection or open the diagnostic log: ' + str(log))
                time.sleep(.15)
            if process.returncode:
                raise RuntimeError(f'Operation failed (exit {process.returncode}). Diagnostic log: {log}')
        except BaseException:
            tree.terminate()
            raise
        finally:
            tree.close()
