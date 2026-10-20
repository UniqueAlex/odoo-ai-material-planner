"""Database-backed requests, short transactions and no automatic paid retries."""
import hashlib
import json
import secrets
from .ai_engine import AnalysisError

TTL = 600
RETENTION = 86400
LEASE = 180
MAX_JOBS = 2048
MAX_USER_PENDING = 32
LOCK_ID = 684120731


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


class Store:
    def __init__(self, cursor):
        self.cursor = cursor

    def _lock(self, cr):
        cr.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cr.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_ID])
        cr.execute("""UPDATE mdic_ai_job SET state='done',
            response='{"status":"failed","code":"interrupted"}'::jsonb,
            payload=NULL, claim=NULL,
            expires_at=(now() AT TIME ZONE 'UTC') + interval '24 hours'
            WHERE state='running' AND lease_until < (now() AT TIME ZONE 'UTC')""")
        cr.execute("""DELETE FROM mdic_ai_job WHERE state != 'running'
            AND expires_at < (now() AT TIME ZONE 'UTC')""")

    def _insert(self, cr, key, scope, payload, lifetime):
        cr.execute("SELECT count(*) FROM mdic_ai_job")
        if cr.fetchone()[0] >= MAX_JOBS:
            raise AnalysisError("busy")
        cr.execute("SELECT count(*) FROM mdic_ai_job WHERE owner_uid=%s AND state='ready'", [scope[1]])
        if cr.fetchone()[0] >= MAX_USER_PENDING:
            raise AnalysisError("busy")
        cr.execute("""INSERT INTO mdic_ai_job
            (job_key, scope_hash, owner_uid, state, payload, expires_at)
            VALUES (%s,%s,%s,'ready',%s::jsonb,
                (now() AT TIME ZONE 'UTC') + %s * interval '1 second')""",
            [key, digest(scope), scope[1], json.dumps(payload), lifetime])

    def put(self, scope, task):
        token = secrets.token_urlsafe(32)
        # Preserve large local calculations; refuse their paid analysis later.
        if len(json.dumps(task)) > 128000:
            task = {"scope_error": "scope_limit"}
        with self.cursor() as cr:
            self._lock(cr)
            cr.execute("""DELETE FROM mdic_ai_job WHERE id IN (
                SELECT id FROM mdic_ai_job WHERE owner_uid=%s AND state='ready'
                ORDER BY expires_at DESC OFFSET %s)""", [scope[1], MAX_USER_PENDING - 1])
            self._insert(cr, digest(token), scope, task, TTL)
            cr.commit()
        return token

    def _claim(self, key, scope, create=False):
        with self.cursor() as cr:
            self._lock(cr)
            cr.execute("SELECT scope_hash,state,payload,response FROM mdic_ai_job WHERE job_key=%s", [key])
            row = cr.fetchone()
            if row is None and create:
                self._insert(cr, key, scope, {}, TTL)
                row = (digest(scope), "ready", {}, None)
            if row is None or row[0] != digest(scope):
                cr.commit()
                raise AnalysisError("expired")
            if row[1] == "done":
                cr.commit()
                return None, row[3], None
            if row[1] == "running":
                cr.commit()
                raise AnalysisError("busy")
            cr.execute("""SELECT count(*),count(*) FILTER (WHERE owner_uid=%s)
                FROM mdic_ai_job WHERE state='running'""", [scope[1]])
            count, own = cr.fetchone()
            if count >= 2 or own:
                cr.commit()
                raise AnalysisError("busy")
            claim = secrets.token_hex(16)
            cr.execute("""UPDATE mdic_ai_job SET state='running',claim=%s,
                lease_until=(now() AT TIME ZONE 'UTC') + %s * interval '1 second',
                expires_at=(now() AT TIME ZONE 'UTC') + %s * interval '1 second'
                WHERE job_key=%s""", [claim, LEASE, RETENTION, key])
            cr.commit()
            return row[2], None, claim

    def _finish(self, key, claim, result):
        encoded = json.dumps(result)
        if len(encoded) > 512000:
            result = {"status": "failed", "code": "format"}
            encoded = json.dumps(result)
        with self.cursor() as cr:
            cr.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            cr.execute("""UPDATE mdic_ai_job SET state='done',response=%s::jsonb,
                payload=NULL,claim=NULL,lease_until=NULL
                WHERE job_key=%s AND state='running' AND claim=%s RETURNING id""",
                [encoded, key, claim])
            saved = cr.fetchone()
            cr.commit()
        if not saved:
            return {"status": "failed", "code": "interrupted"}
        return result

    def run(self, scope, operation, *, token=None, identity=None):
        if token is not None:
            if not isinstance(token, str) or not 20 <= len(token) <= 100:
                raise AnalysisError("expired")
            key = digest(token)
        else:
            key = digest(["request-v1", scope, identity])
        payload, cached, claim = self._claim(key, scope, create=token is None)
        if claim is None:
            return {**cached, "cache_hit": True}
        try:
            result = operation(payload)
        except AnalysisError as exc:
            result = {"status": "failed", "code": exc.code,
                      **({"detail": exc.detail} if exc.detail else {})}
        except Exception:
            # The provider may have accepted a request before the failure.
            result = {"status": "failed", "code": "interrupted"}
        return self._finish(key, claim, result)
