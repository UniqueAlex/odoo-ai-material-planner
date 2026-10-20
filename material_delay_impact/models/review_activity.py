"""Native activities remain the only source of assignment, completion and feedback."""
import re
from datetime import datetime, timezone
from urllib.parse import urlencode
from pytz import UnknownTimeZoneError
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from . import snapshot, reallocation_adapter
from ..review_contract import option_key, targets, decision_context


class ReviewActivity(models.Model):
    _inherit = 'mail.activity'

    mdic_line_id = fields.Many2one('purchase.order.line', index=True, ondelete='cascade', copy=False)
    mdic_option_key = fields.Char(index=True, copy=False)
    mdic_target_key = fields.Char(index=True, copy=False)
    mdic_revision = fields.Char(copy=False)
    mdic_arrival = fields.Datetime(copy=False)
    mdic_role = fields.Char(copy=False)
    mdic_decision = fields.Selection([('adopt', 'Adopt'), ('reject', 'Reject'), ('defer', 'Defer decision')], string='Plan decision', copy=False)
    mdic_outcome = fields.Selection([
        ('unknown', 'To verify'), ('met', 'This arrangement is feasible'), ('not_met', 'This arrangement is not feasible')],
        string='Arrangement feasibility', default='unknown', copy=False,
        help='Answer for this specific arrangement. A transfer review confirms permission to move materials. Completing a review does not approve the whole plan.')
    _mdic_pending_unique = models.UniqueIndex(
        '(mdic_line_id, mdic_option_key, mdic_target_key, mdic_revision) WHERE active AND mdic_line_id IS NOT NULL',
        'A pending review already exists for this target. Refresh review progress.')

    def action_mdic_complete(self):
        self.ensure_one()
        self.check_access('write')
        if not self.mdic_line_id or not self.active or not (self.feedback or '').strip():
            raise UserError(_('Enter the verification conclusion, evidence and next step before completing.'))
        self.action_feedback(feedback=self.feedback)
        return {'type': 'ir.actions.act_window_close'}

    @api.readonly
    def action_mdic_open_plan(self):
        self.ensure_one()
        self.check_access('read')
        if not self.mdic_line_id:
            raise UserError(_('This activity has no material plan.'))
        order = self.mdic_line_id.order_id
        arrival = self.mdic_arrival.replace(tzinfo=timezone.utc).isoformat()
        if all(self.env.user.has_group(g) for g in ('purchase.group_purchase_user', 'stock.group_stock_user', 'mrp.group_mrp_user')):
            order._mdic_review_line(self.mdic_line_id.id)
        else:
            order._mdic_shared_tasks(self.mdic_line_id.id, arrival)
        return {'type': 'ir.actions.act_url', 'target': 'self',
                'url': '/odoo/action-material_delay_impact?' + urlencode({
                    'active_id': order.id, 'mdic_line': self.mdic_line_id.id,
                    'mdic_arrival': arrival, 'mdic_tz': self.env.user.tz or 'UTC'})}

    @api.constrains('mdic_line_id', 'mdic_option_key', 'mdic_target_key', 'mdic_revision', 'mdic_arrival', 'res_model_id', 'res_id')
    def _mdic_check_link(self):
        for task in self.filtered('mdic_line_id'):
            line = task.mdic_line_id
            line.check_access('read')
            # Activity validation needs document access, not the full calculation
            # scope audit (which is performed before preparing a review).
            line.order_id.check_access('read')
            if line.company_id.id not in self.env.companies.ids:
                raise UserError(_('Invalid review company.'))
            if task.res_model != 'purchase.order' or task.res_id != line.order_id.id or not task.mdic_arrival:
                raise UserError(_('Invalid review document.'))
            if any(not re.fullmatch('[0-9a-f]{64}', v or '') for v in
                   (task.mdic_option_key, task.mdic_target_key, task.mdic_revision)):
                raise UserError(_('Invalid review identity.'))


class PurchaseReview(models.Model):
    _inherit = 'purchase.order'

    def _mdic_review_line(self, line_id):
        self.ensure_one()
        snapshot.checked_order(self.env, self.id)
        line = self.env['purchase.order.line'].browse(line_id).exists() if type(line_id) is int else self.env['purchase.order.line']
        line.check_access('read')
        if len(line) != 1 or line.order_id != self:
            raise UserError(_('Invalid review purchase line.'))
        return line

    @api.readonly
    def mdic_review_context(self, line_id, arrival, key, target, revision):
        self._mdic_review_line(line_id)
        value = self._mdic_read(lambda env: reallocation_adapter.request(env, self.id, line_id, arrival, recommend=True))
        if value.get('review_revision') != revision:
            raise UserError(_('The review scenario changed. Analyze again.'))
        option = next((o for o in value['automatic']['alternatives'] if option_key(o) == key), None)
        item = next((t for t in targets(option) if t['key'] == target), None) if option else None
        if target == 'decision' and option:
            from ..review_contract import digest
            item = {'key': digest('decision'), 'role': 'decision'}
        if not item:
            raise UserError(_('The review target is no longer available.'))
        return {'default_mdic_line_id': line_id, 'default_mdic_option_key': key,
                'default_mdic_target_key': item['key'], 'default_mdic_revision': revision,
                'default_mdic_role': item['role'],
                'default_mdic_arrival': fields.Datetime.to_string(datetime.fromisoformat(arrival).astimezone(timezone.utc).replace(tzinfo=None))}

    @api.readonly
    def mdic_review_progress(self, line_id, arrival=None, revision=None):
        self._mdic_review_line(line_id)
        freshness = 'unknown'
        if arrival and revision:
            try:
                current = self._mdic_read(lambda env: reallocation_adapter.request(env, self.id, line_id, arrival, recommend=True))
                freshness = 'unchanged' if current['review_revision'] == revision else 'changed'
            except UserError:
                freshness = 'unknown'
        tasks = self.env['mail.activity'].with_context(active_test=False).search([
            ('res_model', '=', 'purchase.order'), ('res_id', '=', self.id), ('mdic_line_id', '=', line_id)],
            order='write_date desc, id desc', limit=201)
        return {'freshness': freshness, 'truncated': len(tasks) > 200, 'tasks': [{
            'id': t.id, 'option_key': t.mdic_option_key, 'target_key': t.mdic_target_key,
            'revision': t.mdic_revision, 'arrival': fields.Datetime.to_string(t.mdic_arrival),
            'role': t.mdic_role, 'summary': t.summary or '', 'owner': t.user_id.display_name or '',
            'assigned_to_me': t.user_id.id == self.env.uid,
            'due': fields.Date.to_string(t.date_deadline), 'done': not t.active,
            'completed': fields.Date.to_string(t.date_done), 'updated': fields.Datetime.to_string(t.write_date),
            'feedback': t.feedback or '', 'outcome': t.mdic_outcome or 'unknown', 'decision': t.mdic_decision or ''} for t in tasks[:200]]}

    def mdic_record_decision(self, line_id, arrival, key, revision, choice, reason, display_timezone=None):
        line = self._mdic_review_line(line_id)
        self.check_access('write')
        if choice not in ('adopt', 'reject', 'defer') or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise UserError(_('请选择Plan decision并填写原因（最多 2000 字）。'))
        # Serialize decisions for this line, including different candidate cards.
        self.env.cr.execute('SELECT id FROM purchase_order_line WHERE id=%s FOR UPDATE', [line.id])
        ctx = self.mdic_review_context(line_id, arrival, key, 'decision', revision)
        value = self._mdic_read(lambda env: reallocation_adapter.request(env, self.id, line_id, arrival, recommend=True))
        option = next(o for o in value['automatic']['alternatives'] if option_key(o) == key)
        if value.get('review_revision') != revision:
            raise UserError(_('The review scenario changed. Analyze again.'))
        try:
            detail = decision_context(value, option, arrival, display_timezone or self.env.user.tz or 'UTC',
                                      self.env.lang, self.id, line_id)
        except (ValueError, TypeError, UnknownTimeZoneError, AttributeError):
            raise UserError(_('Select a valid display timezone.')) from None
        records = self.env['mail.activity'].with_context(active_test=False).search([
            ('mdic_line_id', '=', line_id), ('mdic_revision', '=', revision)], order='id desc')
        if choice == 'adopt':
            for target in targets(option):
                task = next((t for t in records if t.mdic_option_key == key and t.mdic_target_key == target['key']), None)
                if not task or task.active or task.mdic_outcome != 'met':
                    raise UserError(_('仍有核实目标未完成或条件未满足，请先完成核实，也可记录暂缓或Reject。'))
            latest = {}
            for task in records.filtered(lambda t: t.mdic_decision and not t.active):
                latest.setdefault(task.mdic_option_key, task.mdic_decision)
            if any(k != key and v == 'adopt' for k, v in latest.items()):
                raise UserError(_('当前情景已有其他采用方案，请先将原方案记录为Reject或暂缓。'))
        labels = dict(self.env['mail.activity']._fields['mdic_decision']._description_selection(self.env))
        # Completed decisions may still be buffered in the ORM in this transaction.
        # Flush their archive flag before the pending-target unique index is checked.
        records.flush_recordset(['active'])
        task = self.env['mail.activity'].with_context(**ctx).create({
            'res_model_id': self.env['ir.model']._get_id('purchase.order'), 'res_id': self.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id, 'user_id': self.env.uid,
            'date_deadline': fields.Date.context_today(self),
            'summary': ' · '.join([_('Plan decision：') + labels[choice], detail['title'], detail['arrival_label'] + ': ' + detail['stamp']]),
            'note': Markup('').join(Markup('<p>%s</p>') % text for text in detail['lines']) +
                    Markup('<p><a href="%s">%s</a></p>') % (detail['url'], detail['link_label']),
            'mdic_decision': choice, 'feedback': reason.strip()})
        task.action_mdic_complete()
        return True

    @api.readonly
    def mdic_review_open(self, line_id, activity_id):
        self._mdic_review_line(line_id)
        task = self.env['mail.activity'].with_context(active_test=False).browse(activity_id).exists()
        task.check_access('read')
        if len(task) != 1 or task.mdic_line_id.id != line_id or task.res_model != 'purchase.order' or task.res_id != self.id:
            raise UserError(_('Review task is unavailable.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'mail.activity', 'res_id': task.id,
                'views': [[self.env.ref('material_delay_impact.mdic_review_activity_form').id, 'form']], 'target': 'new',
                'context': {'active_test': False}}
