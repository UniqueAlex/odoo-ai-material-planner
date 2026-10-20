"""POSIX service-account store: authenticated encryption, private files, flock.

The encryption key is protected by the same OS account as Odoo, not a vendor
secret. A host administrator can access it. Back up the whole private directory
securely; a database-only backup does not contain these credentials.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import secrets

from .ai_engine import AnalysisError
from .secure_config import validate_settings


class PosixStore:
    def __init__(self, data_dir, database, company):
        self.directory = Path(data_dir) / "mdic-private-ai"
        self.scope = hashlib.sha256(f"{database}:{company}".encode()).hexdigest()
        self.key_name = self.scope + ".key"
        self.name = self.scope + ".fernet"

    @staticmethod
    def _check(fd, directory=False):
        info = os.fstat(fd)
        kind = stat.S_ISDIR if directory else stat.S_ISREG
        if (not kind(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
                or (not directory and info.st_nlink != 1)):
            raise AnalysisError("secure_storage")

    @contextmanager
    def _locked(self, create=False):
        import fcntl
        directory = lock = None
        try:
            if create:
                self.directory.mkdir(mode=0o700, exist_ok=True)
            try:
                directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            except FileNotFoundError:
                yield None
                return
            self._check(directory, directory=True)
            lock = os.open(self.scope + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                           0o600, dir_fd=directory)
            self._check(lock)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield directory
        except AnalysisError:
            raise
        except Exception:
            raise AnalysisError("secure_storage") from None
        finally:
            if lock is not None:
                os.close(lock)
            if directory is not None:
                os.close(directory)

    def _read_file(self, directory, name, limit=16000):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            self._check(stream.fileno())
            content = stream.read(limit + 1)
            if len(content) > limit:
                raise AnalysisError("secure_storage")
            return content

    def _write_file(self, directory, name, value):
        temporary = self.scope + "." + secrets.token_hex(12) + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass

    def read(self):
        with self._locked() as directory:
            if directory is None:
                return None
            token = self._read_file(directory, self.name)
            if token is None:
                return None
            key = self._read_file(directory, self.key_name, 128)
            if key is None:
                raise AnalysisError("secure_storage")
            from cryptography.fernet import Fernet
            value = json.loads(Fernet(key).decrypt(token))
            if value.pop("scope", None) != self.scope:
                raise AnalysisError("secure_storage")
            validate_settings(value["provider"], value["model"], value["key"])
            return value

    def save(self, provider, model, key):
        validate_settings(provider, model, key)
        from cryptography.fernet import Fernet
        with self._locked(create=True) as directory:
            current = self._read_file(directory, self.name)
            encryption_key = self._read_file(directory, self.key_name, 128)
            if encryption_key is None:
                if current is not None:
                    raise AnalysisError("secure_storage")
                encryption_key = Fernet.generate_key()
                self._write_file(directory, self.key_name, encryption_key)
            value = dict(provider=provider, model=model, key=key, scope=self.scope)
            self._write_file(directory, self.name, Fernet(encryption_key).encrypt(json.dumps(value).encode()))

    def remove(self):
        with self._locked() as directory:
            if directory is None:
                return
            for name in (self.name, self.key_name):
                # Refuse unsafe existing paths instead of following them.
                self._read_file(directory, name)
                try:
                    os.unlink(name, dir_fd=directory)
                except FileNotFoundError:
                    pass
            os.fsync(directory)
