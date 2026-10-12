"""Atomic local records and a heartbeat independent of the model request loop."""
import base64
import ctypes
import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_text(path, text):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    name=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='\n',dir=path.parent,
                                         prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
            name=Path(stream.name); stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if name is not None: name.unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_text(path,json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def pid_alive(pid):
    if type(pid) is not int or pid<=0: return False
    if os.name=='nt':
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return False
        code=ctypes.c_ulong()
        try:return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


def read_status(path):
    status=json.loads(Path(path).read_text(encoding='utf-8'))
    if status.get('state')=='running':
        heartbeat=status.get('heartbeat_at')
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(heartbeat)).total_seconds() if heartbeat else float('inf')
        if not pid_alive(status.get('pid')) or age>30:
            status={**status,'state':'interrupted','observed_reason':'owner absent or heartbeat stale'}
    return status


class RunStatus:
    def __init__(self,path):
        self.path=Path(path);self.lock_path=self.path.with_suffix(self.path.suffix+'.lock')
        self.value={'state':'running','pid':os.getpid(),'generation_id':uuid.uuid4().hex,'started_at':utc_now()}
        self.guard=threading.Lock();self.stop=threading.Event()
        self._owner_guard=None

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        # Keep the guard file in place: deleting it lets contenders lock different files.
        owner_guard=self.lock_path.with_name(self.lock_path.name+'.guard').open('a+b')
        try:
            owner_guard.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(owner_guard.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(owner_guard.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except (BlockingIOError,PermissionError) as error:
                raise RuntimeError('collection output already has a live owner') from error
            if self.lock_path.exists():
                prior=json.loads(self.lock_path.read_text(encoding='utf-8'))
                if pid_alive(prior.get('pid')):raise RuntimeError('collection output already has a live owner')
                self.lock_path.replace(self.lock_path.with_name(self.lock_path.name+'.abandoned-'+uuid.uuid4().hex))
            fd=os.open(self.lock_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(self.value,stream)
                self.update()
                self.thread=threading.Thread(target=self._heartbeat,daemon=True);self.thread.start()
            except BaseException:
                self.lock_path.unlink(missing_ok=True)
                raise
        except BaseException:
            owner_guard.close()
            raise
        # A rejected reentry must not replace the active owner's handle.
        self._owner_guard=owner_guard
        return self

    def _heartbeat(self):
        while not self.stop.wait(5):self.update()

    def update(self,**changes):
        with self.guard:
            self.value.update(changes);self.value['heartbeat_at']=utc_now();atomic_json(self.path,self.value)

    def __exit__(self,kind,error,traceback):
        self.stop.set();self.thread.join()
        try:
            if kind:
                code=130 if issubclass(kind,KeyboardInterrupt) else (error.code if issubclass(kind,SystemExit) and type(error.code) is int else 1)
                self.update(state='interrupted' if issubclass(kind,KeyboardInterrupt) else 'failed',exit_code=code,finished_at=utc_now())
        finally:
            try:
                self.lock_path.unlink(missing_ok=True)
            finally:
                self._owner_guard.close()
                self._owner_guard=None


def redact(text,secrets=()):
    for secret in secrets:
        if secret:text=text.replace(secret,'[REDACTED]')
    text=re.sub(r'(?i)Bearer\s+[A-Za-z0-9._-]+','Bearer [REDACTED]',text)
    return re.sub(r'\bsk-[A-Za-z0-9_-]{12,}','[REDACTED]',text)


class ObservationStore:
    def __init__(self,directory,secrets=()):self.directory=Path(directory);self.secrets=secrets
    def save(self,text,raw_streams=None,**metadata):
        value={'text':text,**metadata}
        raw_redacted = False
        if raw_streams:
            value['raw_streams'] = {}
            for name, raw in raw_streams.items():
                # Latin-1 is a reversible byte mapping here, not output decoding.
                safe = redact(raw.decode('latin-1'),
                    tuple(s.encode('utf-8').decode('latin-1') for s in self.secrets if s)).encode('latin-1')
                changed = safe != raw
                raw_redacted = raw_redacted or changed
                prefix = safe[:65536]
                value['raw_streams'][name] = {
                    'source_bytes': len(raw), 'source_sha256': hashlib.sha256(raw).hexdigest(),
                    'capture_limit_bytes': 65536, 'captured_bytes': len(prefix),
                    'captured_sha256': hashlib.sha256(prefix).hexdigest(),
                    'base64': base64.b64encode(prefix).decode('ascii'),
                    'truncated': len(safe) > len(prefix), 'redacted': changed,
                    'capture_complete': not changed and len(raw) <= len(prefix),
                }
        original=json.dumps(value,ensure_ascii=False,sort_keys=True)
        def scrub(value):
            if isinstance(value,dict):
                return {k:('[REDACTED]' if k.lower().replace('_','') in ('apikey','authorization','accesstoken','refreshtoken','password') else scrub(v)) for k,v in value.items()}
            if isinstance(value,list):return [scrub(v) for v in value]
            return value
        sanitized=redact(json.dumps(scrub(value),ensure_ascii=False,sort_keys=True),self.secrets)
        data=json.loads(sanitized)
        data.update(text_sha256=hashlib.sha256(data['text'].encode()).hexdigest(),
                    original_text_sha256=hashlib.sha256(text.encode()).hexdigest(),redacted=sanitized!=original or raw_redacted)
        body=json.dumps(data,ensure_ascii=False,sort_keys=True)
        digest=hashlib.sha256(body.encode()).hexdigest();path=self.directory/(digest+'.json')
        atomic_text(path,body)
        return {'path':self.directory.name+'/'+path.name,'sha256':digest,
                'text_sha256':data['text_sha256'],'redacted':data['redacted']}


def load_observation(root,reference):
    root=Path(root).resolve();path=(root/reference['path']).resolve()
    if not path.is_relative_to(root):raise ValueError('observation path leaves artifact directory')
    body=path.read_bytes()
    if hashlib.sha256(body).hexdigest()!=reference['sha256']:raise ValueError('observation hash mismatch')
    data=json.loads(body)
    if hashlib.sha256(data['text'].encode()).hexdigest()!=reference['text_sha256']:raise ValueError('text hash mismatch')
    return data
