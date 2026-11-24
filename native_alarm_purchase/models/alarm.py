from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.native_alarm.models.instrumentation import logged_operation
from odoo.tools import format_datetime


class NativeAlarm(models.Model):
    _inherit = 'native.alarm'

    purchase_arrival_tracking = fields.Boolean(string='Follow expected arrival', copy=False, readonly=True)
    purchase_arrival_date = fields.Datetime(string='Tracked expected arrival', copy=False, readonly=True)
    purchase_arrival_offset = fields.Integer(string='Arrival reminder offset (seconds)', copy=False, readonly=True)

    @api.model_create_multi
    @logged_operation('PURCHASE_ARRIVAL_SCHEDULE')
    def create(self, vals_list):
        prepared = []
        for incoming in vals_list:
            vals = dict(incoming)
            tracking = vals.get('purchase_arrival_tracking', self.env.context.get('default_purchase_arrival_tracking'))
            vals.pop('purchase_arrival_date', None)
            vals.pop('purchase_arrival_offset', None)
            if tracking:
                model_id = vals.get('model_id') or self.env.context.get('default_model_id')
                res_id = vals.get('res_id') or self.env.context.get('default_res_id')
                if self.env['ir.model'].browse(model_id).model != 'purchase.order' or not res_id:
                    raise ValidationError(_('Arrival tracking requires a purchase order.'))
                order = self.env['purchase.order'].browse(res_id).exists()
                if not order:
                    raise UserError(_('The purchase order no longer exists.'))
                order.check_access('read')
                if not order._arrival_alarm_eligible():
                    raise ValidationError(_('A confirmed order with an expected arrival and an outstanding receipt is required.'))
                alarm_at = fields.Datetime.to_datetime(vals.get('alarm_at') or
                            self.env.context.get('default_alarm_at') or order.date_planned)
                vals.update(purchase_arrival_tracking=True, purchase_arrival_date=order.date_planned,
                            purchase_arrival_offset=int((alarm_at - order.date_planned).total_seconds()),
                            alarm_at=alarm_at)
            prepared.append(vals)
        return super().create(prepared)

    def write(self, vals):
        if {'purchase_arrival_tracking', 'purchase_arrival_date', 'purchase_arrival_offset'} & vals.keys():
            raise AccessError(_('Arrival tracking is managed by the purchase alarm connector.'))
        if {'model_id', 'res_id'} & vals.keys() and self.filtered('purchase_arrival_tracking'):
            raise AccessError(_('A tracked arrival alarm cannot be retargeted.'))
        if 'alarm_at' in vals and vals['alarm_at']:
            tracked = self.filtered('purchase_arrival_tracking')
            for alarm in tracked:
                alarm.check_access('write')
                alarm.flush_recordset()
                self.env.cr.execute('SELECT id FROM native_alarm WHERE id = %s FOR UPDATE', [alarm.id])
                alarm.invalidate_recordset(['purchase_arrival_date'])
                offset = int((fields.Datetime.to_datetime(vals['alarm_at']) - alarm.purchase_arrival_date).total_seconds())
                super(NativeAlarm, alarm).write(dict(vals, purchase_arrival_offset=offset))
            remainder = self - tracked
            return super(NativeAlarm, remainder).write(vals) if remainder else True
        return super().write(vals)

    def _respond(self, operation, expected_revision=None):
        self.ensure_one()
        if not self.purchase_arrival_tracking:
            return super()._respond(operation, expected_revision)
        self.check_access('write')
        self.flush_recordset()
        self.env.cr.execute('SELECT id FROM native_alarm WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset(['purchase_arrival_offset'])
        offset = self.purchase_arrival_offset
        result = super()._respond(operation, expected_revision)
        # Snooze and repeat change the next ring, not the user's chosen offset.
        if result and self.purchase_arrival_offset != offset:
            super(NativeAlarm, self).write({'purchase_arrival_offset': offset})
        return result

    def _is_deliverable(self, source=None, enabled_models=None):
        self.ensure_one()
        if not super()._is_deliverable(source=source, enabled_models=enabled_models):
            return False
        if self.purchase_arrival_tracking:
            try:
                order = source if source is not None else self._source(self.user_id)
                return order._name == 'purchase.order' and order._arrival_alarm_eligible()
            except (AccessError, UserError):
                return False
        return True

    def _payload(self):
        payload = super()._payload()
        if self.purchase_arrival_tracking and self.purchase_arrival_date:
            # The recipient's language and timezone apply even to a companion
            # account; the source was already checked by _deliverable_alarms.
            recipient_env = self.with_user(self.user_id).with_context(tz=self.user_id.tz or 'UTC')
            payload['name'] = _('%(name)s — Expected arrival: %(arrival)s',
                                name=self.name,
                                arrival=format_datetime(recipient_env.env, self.purchase_arrival_date))
        return payload

    @logged_operation('PURCHASE_ARRIVAL_SYNC')
    def _sync_purchase_arrivals(self):
        # Run only at player synchronization, never inside purchase transactions.
        # Lock as the base response does so a simultaneous snooze cannot be lost.
        for alarm in self.filtered(lambda a: a.purchase_arrival_tracking and a.state == 'scheduled'):
            self.env.cr.execute('SELECT id FROM native_alarm WHERE id = %s FOR UPDATE', [alarm.id])
            alarm.invalidate_recordset(['state', 'alarm_at', 'purchase_arrival_date', 'purchase_arrival_offset', 'revision'])
            if alarm.state != 'scheduled':
                continue
            try:
                order = alarm._source(alarm.user_id)
                if not order._arrival_alarm_eligible() or order.date_planned == alarm.purchase_arrival_date:
                    continue
                # Invoke the base write directly: it increments revision and keeps all
                # existing constraints. No purchase record is modified.
                recipient_alarm = alarm.with_user(alarm.user_id).with_context(
                    allowed_company_ids=[alarm.company_id.id])
                super(NativeAlarm, recipient_alarm).write({'purchase_arrival_date': order.date_planned,
                    'alarm_at': order.date_planned + timedelta(seconds=alarm.purchase_arrival_offset)})
            except (AccessError, UserError):
                continue

    @api.model
    def browser_schedule(self):
        alarms = self.search([('user_id', '=', self.env.uid), ('company_id', '=', self.env.company.id),
                              ('state', '=', 'scheduled'), ('purchase_arrival_tracking', '=', True),
                              ('delivery', 'in', ['browser', 'both'])])
        alarms._sync_purchase_arrivals()
        return super().browser_schedule()

