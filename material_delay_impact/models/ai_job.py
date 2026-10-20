from odoo import api, fields, models


class AIJob(models.Model):
    _name = "mdic.ai.job"
    _description = "Private temporary AI request state"
    _log_access = False

    # No access.csv grants, menus or public RPC methods. Authenticated purchase
    # methods recheck business access before using the private SQL store.
    job_key = fields.Char(required=True)
    scope_hash = fields.Char(required=True)
    owner_uid = fields.Integer(required=True)
    state = fields.Char(required=True)
    payload = fields.Json()
    response = fields.Json()
    claim = fields.Char()
    expires_at = fields.Datetime(required=True)
    lease_until = fields.Datetime()

    def init(self):
        self.env.cr.execute("CREATE UNIQUE INDEX IF NOT EXISTS mdic_ai_job_key ON mdic_ai_job(job_key)")
        self.env.cr.execute("CREATE INDEX IF NOT EXISTS mdic_ai_job_expiry ON mdic_ai_job(expires_at)")

    @api.autovacuum
    def _gc_ai_jobs(self):
        from ..tasks import Store
        with self.env.registry.cursor() as cr:
            Store(self.env.registry.cursor)._lock(cr)
            cr.commit()
