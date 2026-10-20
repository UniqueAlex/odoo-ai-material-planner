from datetime import datetime, timezone
import json
import pytz
import re

from odoo import _, api, models
from odoo.exceptions import UserError

from . import snapshot, reallocation_adapter
from .. import ai_engine, secure_config, tasks, reallocation_ai
from odoo.tools import config

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def _mdic_read(self, callback):
        self.ensure_one()
        # Fresh primary cursor: all relevant facts share a snapshot, and the
        # database rejects accidental writes even without a read replica.
        with self.env.registry.cursor() as cr:
            cr.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cr.execute("SHOW transaction_read_only")
            if cr.fetchone()[0] != "on":
                raise UserError(_("The read-only material snapshot could not be opened."))
            read_env = api.Environment(cr, self.env.uid, dict(self.env.context), su=False)
            return callback(read_env)

    @api.readonly
    def action_material_delay(self):
        self._mdic_read(lambda env: snapshot.checked_order(env, self.id))
        return {"type": "ir.actions.client", "tag": "material_delay_impact",
                "name": _("Delay impact"), "params": {"order_id": self.id},
                "context": {"active_model": "purchase.order", "active_id": self.id}}

    @api.readonly
    def mdic_options(self):
        return self._mdic_read(lambda env: snapshot.options(env, self.id))

    @api.readonly
    def mdic_reallocation_recommend(self, line_id, assumed_arrival_at, with_ai=False, display_timezone='UTC', request_id=None):
        from .. import recommendation_ai
        if type(with_ai) is not bool:
            raise UserError(_("Select a valid recommendation mode."))
        try:
            if not isinstance(display_timezone,str) or len(display_timezone)>64:raise ValueError()
            pytz.timezone(display_timezone)
        except (ValueError,pytz.UnknownTimeZoneError):
            raise UserError(_("Select a valid timezone.")) from None
        value=self._mdic_read(lambda env: reallocation_adapter.request(
            env,self.id,line_id,assumed_arrival_at,recommend=True))
        value['ai_recommendation']={'status':'not_requested'}
        if recommendation_ai.no_adjustment_needed(value):
            value['ai_recommendation']={'status':'not_needed','reason':'no_adjustment_needed','modules':[]}
            return value
        if not with_ai:return value
        if not value['automatic']['alternatives']:
            value['ai_recommendation']={'status':'not_needed'}
            return value
        if not recommendation_ai.RECOMMENDATION_ENABLED:
            value['ai_recommendation']={'status':'failed','code':'prose_review_pending'}
            return value
        company=self._mdic_ai_access()
        try:
            recommendation_ai.contract(value,display_timezone)
            saved=self._mdic_store(company).read()
            if not saved:raise ai_engine.AnalysisError('configuration')
            identity=self._mdic_request_identity('recommend',value['recommendation_facts_key'],saved,
                                                 display_timezone,request_id)
            value['ai_recommendation']=self._mdic_jobs().run(self._mdic_scope(line_id),
                lambda _: recommendation_ai.run(value,saved['provider'],saved['model'],
                    self._mdic_language(),saved['key'],display_timezone),identity=identity)
        except ai_engine.AnalysisError as exc:
            value['ai_recommendation']={'status':'failed','code':exc.code}
        return value

    @api.readonly
    def mdic_reallocation(self, line_id, assumed_arrival_at, receiver_ref=None,
                          transfers=None, expected_facts_key=None):
        return self._mdic_read(lambda env: reallocation_adapter.request(
            env, self.id, line_id, assumed_arrival_at, receiver_ref, transfers, expected_facts_key))

    @api.readonly
    def mdic_reallocation_ai(self, line_id, assumed_arrival_at, transfers, expected_facts_key, display_timezone='UTC', request_id=None):
        try:
            if not isinstance(display_timezone,str) or len(display_timezone)>64:
                raise ValueError()
            pytz.timezone(display_timezone)
        except (ValueError,pytz.UnknownTimeZoneError):
            raise UserError(_("Select a valid timezone.")) from None
        value=self.mdic_reallocation(line_id,assumed_arrival_at,transfers=transfers,expected_facts_key=expected_facts_key)
        if not reallocation_ai.INTERPRETATION_ENABLED:
            return {'status':'failed','code':'prose_review_pending'}
        company=self._mdic_ai_access()
        try:
            reallocation_ai.contract(value,display_timezone)
            saved=self._mdic_store(company).read()
            if not saved:raise ai_engine.AnalysisError('configuration')
            identity=self._mdic_request_identity('manual',[expected_facts_key,transfers],saved,
                                                 display_timezone,request_id)
            return self._mdic_jobs().run(self._mdic_scope(line_id),
                lambda _: reallocation_ai.run(value,saved['provider'],saved['model'],
                    self._mdic_language(),saved['key'],display_timezone),identity=identity)
        except ai_engine.AnalysisError as exc:
            return {'status':'failed','code':exc.code}

    @api.readonly
    def mdic_analyze(self, line_id, assumed_arrival_at, display_timezone=None):
        if type(line_id) is not int or line_id <= 0 or not isinstance(assumed_arrival_at, str) or len(assumed_arrival_at) > 64:
            raise UserError(_("Select a purchase line and a valid arrival date and time."))
        try:
            parsed = datetime.fromisoformat(assumed_arrival_at)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timezone required")
            parsed = parsed.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            raise UserError(_("The arrival date must include a valid timezone.")) from None
        display_timezone = display_timezone or self.env.user.tz or "UTC"
        try:
            if not isinstance(display_timezone, str) or len(display_timezone) > 64:
                raise ValueError()
            pytz.timezone(display_timezone)
        except (ValueError, pytz.UnknownTimeZoneError):
            raise UserError(_("Select a valid timezone.")) from None
        report, task = self._mdic_read(lambda env: snapshot.calculate(env, self.id, line_id, parsed, with_ai=True))
        task["context"]["display_timezone"] = display_timezone
        report["ai_token"] = self._mdic_jobs().put(self._mdic_scope(line_id), task)
        report["ai_config"] = self.mdic_ai_status()
        return report

    def _mdic_language(self):
        return ai_engine.report_language(self.env.context.get("lang") or self.env.user.lang or "en_US")

    def _mdic_scope(self, line_id):
        return (self.env.cr.dbname, self.env.uid, tuple(sorted(self.env.companies.ids)),
                self.id, line_id, self._mdic_language())

    def _mdic_store(self, company):
        return secure_config.Store(config["data_dir"], self.env.cr.dbname, company)

    def _mdic_jobs(self):
        return tasks.Store(self.env.registry.cursor)

    def _mdic_request_identity(self, kind, facts, saved, timezone_name, request_id):
        if request_id is not None and (not isinstance(request_id,str) or
                not re.fullmatch(r"[A-Za-z0-9_-]{16,80}",request_id)):
            raise ai_engine.AnalysisError("parameters")
        return [kind,facts,timezone_name,saved["provider"],saved["model"],
                tasks.digest(saved["key"]),request_id]

    def _mdic_ai_access(self):
        return self._mdic_read(lambda env: snapshot.checked_order(env, self.id).company_id.id)

    @api.readonly
    def mdic_ai_status(self):
        company = self._mdic_ai_access()
        try:
            saved = self._mdic_store(company).read()
        except ai_engine.AnalysisError as exc:
            return {"configured": False, "code": exc.code, "can_manage": self.env.user.has_group("base.group_system")}
        return {"configured": bool(saved), "provider": saved["provider"] if saved else "deepseek",
                "model": saved["model"] if saved else "deepseek-flash",
                "can_manage": self.env.user.has_group("base.group_system")}

    def mdic_ai_save(self, provider, model, key):
        company = self._mdic_ai_access()
        if not self.env.user.has_group("base.group_system"):
            return {"status": "failed", "code": "admin"}
        try:
            secure_config.validate_settings(provider, model)
            store = self._mdic_store(company)
            if not key:
                previous = store.read()
                if not previous or previous["provider"] != provider:
                    raise ai_engine.AnalysisError("configuration")
                key = previous["key"]
            store.save(provider, model, key)
            return {"status": "saved", **self.mdic_ai_status()}
        except ai_engine.AnalysisError as exc:
            return {"status": "failed", "code": exc.code, **({"detail": exc.detail} if exc.detail else {})}
        except Exception:
            return {"status": "failed", "code": "secure_storage"}

    def mdic_ai_remove(self):
        company = self._mdic_ai_access()
        if not self.env.user.has_group("base.group_system"):
            return {"status": "failed", "code": "admin"}
        try:
            self._mdic_store(company).remove()
            return {"status": "removed", **self.mdic_ai_status()}
        except Exception:
            return {"status": "failed", "code": "secure_storage"}

    @api.readonly
    def mdic_ai_test(self, request_id=None):
        company = self._mdic_ai_access()
        if not self.env.user.has_group("base.group_system"):
            return {"status": "failed", "code": "admin"}
        try:
            saved = self._mdic_store(company).read()
            if not saved:
                raise ai_engine.AnalysisError("configuration")
            identity=self._mdic_request_identity("connection",company,saved,"UTC",request_id)
            return self._mdic_jobs().run(self._mdic_scope(0),
                lambda _: ai_engine.test_connection(saved["provider"],saved["model"],saved["key"]),identity=identity)
        except ai_engine.AnalysisError as exc:
            return {"status": "failed", "code": exc.code}

    @api.readonly
    def mdic_ai_analyze(self, token, line_id):
        if type(line_id) is not int or line_id <= 0:
            return {"status": "failed", "code": "expired"}
        company = self._mdic_ai_access()
        # Repeat access checks now, without taking a new set of business facts.
        self._mdic_read(lambda env: env["purchase.order.line"].browse(line_id).check_access("read"))
        try:
            def perform(task):
                if task.get("scope_error") or len(task["tools"]["read_material_demands"]) > 20:
                    raise ai_engine.AnalysisError("scope_limit")
                saved = self._mdic_store(company).read()
                if not saved:
                    raise ai_engine.AnalysisError("configuration")
                result = ai_engine.run(task, saved["provider"], saved["model"], self._mdic_language(), saved["key"])
                result["generated_at"] = datetime.now(timezone.utc).isoformat()
                return result
            return self._mdic_jobs().run(self._mdic_scope(line_id), perform, token=token)
        except ai_engine.AnalysisError as exc:
            return {"status": "failed", "code": exc.code, **({"detail": exc.detail} if exc.detail else {})}
        except (ValueError, TypeError, KeyError, AttributeError):
            return {"status": "failed", "code": "format"}
