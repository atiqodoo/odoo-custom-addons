"""Collection promises and authorized, company-scoped overdue reminders."""
import logging
import math
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)
_CONFIG_FIELDS = {
    'cod_collection_promises_enabled', 'cod_collection_delay_days',
    'cod_collection_hour', 'cod_collection_timezone',
    'cod_reminder_interval_minutes', 'cod_reminder_refresh_seconds',
}


class PosConfig(models.Model):
    _inherit = 'pos.config'

    cod_collection_promises_enabled = fields.Boolean(string='COD Collection Promises and Reminders')
    cod_collection_delay_days = fields.Integer(string='Collection Days After Dispatch', default=0)
    cod_collection_hour = fields.Float(string='Default Collection Time', default=18.0)
    cod_collection_timezone = fields.Selection(
        selection=lambda self: [(tz, tz) for tz in pytz.all_timezones],
        string='Collection Timezone', required=True,
        default=lambda self: self.env.user.tz or 'UTC',
    )
    cod_reminder_interval_minutes = fields.Integer(string='Repeat Reminder After (minutes)', default=10)
    cod_reminder_refresh_seconds = fields.Integer(string='Reminder Refresh (seconds)', default=60)

    @api.constrains(*sorted(_CONFIG_FIELDS))
    def _check_cod_promise_settings(self):
        for config in self:
            if config.cod_collection_delay_days < 0:
                raise ValidationError(_('Collection days after dispatch cannot be negative.'))
            if (not math.isfinite(config.cod_collection_hour)
                    or not 0 <= config.cod_collection_hour < 24):
                raise ValidationError(_('Collection time must be between 00:00 and 23:59.'))
            if config.cod_reminder_interval_minutes <= 0 or config.cod_reminder_refresh_seconds <= 0:
                raise ValidationError(_('COD reminder intervals must be positive.'))

    def _cod_check_settings_access(self, vals):
        if _CONFIG_FIELDS.intersection(vals) and not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_('Only POS managers can configure COD collection promises.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._cod_check_settings_access(vals)
        controlled = any(_CONFIG_FIELDS.intersection(vals) for vals in vals_list)
        if controlled:
            _logger.debug('[COD][PROMISE_SETTINGS_CREATE][START] user_id=%s count=%s', self.env.uid, len(vals_list))
        try:
            configs = super().create(vals_list)
        except Exception:
            if controlled:
                _logger.debug('[COD][PROMISE_SETTINGS_CREATE][ERROR] user_id=%s', self.env.uid)
            raise
        if controlled:
            _logger.debug('[COD][PROMISE_SETTINGS_CREATE][END] config_ids=%s', configs.ids)
        return configs

    def write(self, vals):
        self._cod_check_settings_access(vals)
        if not _CONFIG_FIELDS.intersection(vals):
            return super().write(vals)
        _logger.debug('[COD][PROMISE_SETTINGS][START] config_ids=%s user_id=%s', self.ids, self.env.uid)
        try:
            result = super().write(vals)
        except Exception:
            _logger.debug('[COD][PROMISE_SETTINGS][ERROR] config_ids=%s', self.ids)
            raise
        _logger.debug('[COD][PROMISE_SETTINGS][END] config_ids=%s', self.ids)
        return result

    def _cod_promise_access(self):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('POS access is required.'))
        self.check_access('read')
        if self.company_id not in self.env.companies:
            raise AccessError(_('Select a POS in an allowed company.'))

    def cod_promise_defaults(self):
        self._cod_promise_access()
        _logger.debug('[COD][PROMISE_DEFAULTS][START] config_id=%s', self.id)
        try:
            now = fields.Datetime.now()
            zone = pytz.timezone(self.cod_collection_timezone)
            local_now = pytz.UTC.localize(now).astimezone(zone)
            due_date = local_now.date() + timedelta(days=self.cod_collection_delay_days)
            minutes = min(round(self.cod_collection_hour * 60), 1439)
            # Return wall-clock defaults: cashier can correct a past cutoff or DST gap.
            due_local = datetime.combine(due_date, time(minutes // 60, minutes % 60))
            result = {
                'enabled': self.cod_enabled and self.cod_collection_promises_enabled,
                'timezone': zone.zone, 'server_now': fields.Datetime.to_string(now),
                'date': due_date.isoformat(), 'hour': due_local.hour,
                'minute': due_local.minute,
            }
        except Exception:
            _logger.debug('[COD][PROMISE_DEFAULTS][ERROR] config_id=%s', self.id)
            raise
        _logger.debug('[COD][PROMISE_DEFAULTS][END] config_id=%s', self.id)
        return result


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cod_collection_promises_enabled = fields.Boolean(related='pos_config_id.cod_collection_promises_enabled', readonly=False)
    cod_collection_delay_days = fields.Integer(related='pos_config_id.cod_collection_delay_days', readonly=False)
    cod_collection_hour = fields.Float(related='pos_config_id.cod_collection_hour', readonly=False)
    cod_collection_timezone = fields.Selection(related='pos_config_id.cod_collection_timezone', readonly=False)
    cod_reminder_interval_minutes = fields.Integer(related='pos_config_id.cod_reminder_interval_minutes', readonly=False)
    cod_reminder_refresh_seconds = fields.Integer(related='pos_config_id.cod_reminder_refresh_seconds', readonly=False)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    cod_promised_payment_at = fields.Datetime(string='Promised COD Collection', index=True, copy=False)

    @api.model
    def sync_from_ui(self, orders):
        """Validate new promises before stock/accounting side effects, preserving retries."""
        for payload in orders:
            if not payload.get('is_cod'):
                continue
            session = self.env['pos.session'].browse(payload.get('session_id')).exists()
            if not session:
                raise ValidationError(_('A valid POS session is required for COD dispatch.'))
            config = session.config_id
            config._cod_promise_access()
            existing = self._get_open_order(payload)
            if (existing and existing.is_cod and existing.cod_ar_move_id
                    and round(existing.amount_total, 2) == round(float(payload.get('amount_total') or 0), 2)
                    and existing.partner_id.id == payload.get('partner_id')):
                # A duplicate dispatch must never replace a saved promise.
                payload['cod_promised_payment_at'] = fields.Datetime.to_string(existing.cod_promised_payment_at) if existing.cod_promised_payment_at else False
                continue
            if not config.cod_collection_promises_enabled and not payload.get('cod_promised_payment_at'):
                continue
            _logger.debug('[COD][PROMISE_VALIDATE][START] config_id=%s session_id=%s', config.id, session.id)
            try:
                due = fields.Datetime.to_datetime(payload.get('cod_promised_payment_at'))
                if not due or due <= fields.Datetime.now():
                    raise ValidationError(_('Select a promised collection date and time later than dispatch time.'))
            except (TypeError, ValueError):
                _logger.debug('[COD][PROMISE_VALIDATE][ERROR] config_id=%s invalid_datetime=True', config.id)
                raise ValidationError(_('Enter a valid promised collection date and time.'))
            except Exception:
                _logger.debug('[COD][PROMISE_VALIDATE][ERROR] config_id=%s', config.id)
                raise
            _logger.debug('[COD][PROMISE_VALIDATE][END] config_id=%s', config.id)
        return super().sync_from_ui(orders)

    @api.model
    def cod_overdue_reminders(self, config_id, offset=0, limit=40):
        config = self.env['pos.config'].browse(config_id).exists()
        if not config:
            raise AccessError(_('Select an accessible POS.'))
        config._cod_promise_access()
        offset, limit = max(int(offset), 0), min(max(int(limit), 1), 100)
        _logger.debug('[COD][OVERDUE_REMINDERS][START] config_id=%s company_id=%s', config.id, config.company_id.id)
        try:
            now = fields.Datetime.now()
            domain = [
                ('company_id', '=', config.company_id.id), ('is_cod', '=', True),
                ('state', 'not in', ['draft', 'cancel']),
                ('cod_state', 'in', ['pending', 'partial', 'out_for_delivery', 'delivered']),
                ('cod_ar_move_id', '!=', False), ('cod_promised_payment_at', '!=', False),
            ]
            orders = self.search(domain, order='cod_promised_payment_at, id') if (
                config.cod_enabled and config.cod_collection_promises_enabled
            ) else self.browse()
            # Reuse the collection contract, including discounts, deposits and cheque adjustments.
            balances = {order.id: order._cod_open_amount() for order in orders}
            orders = orders.filtered(lambda order: order.currency_id.compare_amounts(balances[order.id], 0) > 0)
            future = orders.filtered(lambda order: order.cod_promised_payment_at > now)
            orders = orders - future
            if offset >= len(orders):
                offset = 0
            rows = [{
                'id': order.id, 'name': order.pos_reference or order.name,
                'customer': order.partner_id.display_name,
                'employee': order.delivery_employee_id.name or '',
                'promised_at': fields.Datetime.to_string(order.cod_promised_payment_at),
                'open_amount': balances[order.id], 'currency_id': order.currency_id.id,
            } for order in orders[offset:offset + limit]]
            result = {'rows': rows, 'count': len(orders), 'offset': offset, 'limit': limit,
                      'checked_at': fields.Datetime.to_string(now), 'timezone': config.cod_collection_timezone,
                      'next_due_in_seconds': (future[0].cod_promised_payment_at - now).total_seconds() if future else None}
        except Exception:
            _logger.debug('[COD][OVERDUE_REMINDERS][ERROR] config_id=%s', config.id)
            raise
        _logger.debug('[COD][OVERDUE_REMINDERS][END] config_id=%s count=%s', config.id, len(orders))
        return result
