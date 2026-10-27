"""Platform credential stores. Windows keeps its existing DPAPI format."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import secrets
from datetime import datetime, timezone

from .ai_engine import PROVIDERS, AnalysisError

LOCK = threading.RLock()


def revision(value):
    return value.get('revision') or hashlib.sha256(json.dumps(
        [value['provider'], value['model'], value['key']]).encode()).hexdigest()


def validation_update(value, level):
    if level not in ('connected', 'capable'):
        raise AnalysisError('configuration')
    result = dict(value.get('validation', {}))
    result[level] = datetime.now(timezone.utc).isoformat()
    if level == 'capable':
        result.setdefault('connected', result[level])
    return result


def validate_settings(provider, model, key=None):
    if provider not in PROVIDERS or not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", model):
        raise AnalysisError("configuration")
    if key is not None and (not isinstance(key, str) or not 10 <= len(key) <= 512
                            or any(ord(c) <= 32 or ord(c) >= 127 for c in key)):
        raise AnalysisError("configuration")


def private_acl(path):
    import win32api
    import win32con
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    system = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    acl = win32security.ACL()
    for allowed in (sid, system):
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION_DS, 3, win32con.GENERIC_ALL, allowed)
    win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, acl, None)


class WindowsStore:
    def __init__(self, data_dir, database, company):
        if os.name != "nt":
            raise AnalysisError("secure_storage")
        self.directory = Path(data_dir) / "mdic-private-ai"
        scope = hashlib.sha256(f"{database}:{company}".encode()).hexdigest()
        self.path = self.directory / (scope + ".dpapi")
        self.entropy = ("material-delay-impact:" + scope).encode()

    def read(self):
        with LOCK:
            if not self.path.exists():
                return None
            if self.path.is_symlink() or self.directory.is_symlink() or self.path.stat().st_size > 16000:
                raise AnalysisError("secure_storage")
            try:
                import win32crypt
                _, plain = win32crypt.CryptUnprotectData(self.path.read_bytes(), self.entropy, None, None, 1)
                value = json.loads(plain)
                validate_settings(value["provider"], value["model"], value["key"])
                return value
            except Exception:
                raise AnalysisError("secure_storage") from None

    def save(self, provider, model, key, *, validation=None, saved_revision=None):
        import win32crypt
        validate_settings(provider, model, key)
        with LOCK:
            if self.directory.is_symlink() or self.path.is_symlink():
                raise AnalysisError("secure_storage")
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            private_acl(self.directory)
            encrypted = win32crypt.CryptProtectData(json.dumps({"provider": provider, "model": model, "key": key,
                "revision": saved_revision or secrets.token_hex(16), "validation": validation or {}}).encode(),
                "MDIC AI configuration", self.entropy, None, None, 1)  # CURRENT USER, UI forbidden; never LOCAL_MACHINE.
            fd, temporary = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
            try:
                private_acl(temporary)
                with os.fdopen(fd, "wb") as stream:
                    fd = None
                    stream.write(encrypted)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if fd is not None:
                    os.close(fd)
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def mark_validation(self, expected_revision, level):
        with LOCK:
            current = self.read()
            if not current or revision(current) != expected_revision:
                return False
            self.save(current['provider'], current['model'], current['key'],
                      validation=validation_update(current, level), saved_revision=revision(current))
            return True

    def remove(self):
        with LOCK:
            if self.path.is_symlink() or self.directory.is_symlink():
                raise AnalysisError("secure_storage")
            self.path.unlink(missing_ok=True)


def Store(data_dir, database, company):
    if os.name == "nt":
        return WindowsStore(data_dir, database, company)
    if os.name == "posix":
        from .secure_posix import PosixStore
        return PosixStore(data_dir, database, company)
    raise AnalysisError("secure_storage")
