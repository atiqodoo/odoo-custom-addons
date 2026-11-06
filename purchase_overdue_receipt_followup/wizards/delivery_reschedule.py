import logging

from odoo import _, api, Command, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PurchaseDeliveryReschedule(models.TransientModel):
    _name = 'purchase.delivery.reschedule'
    _description = 'Revise outstanding purchase delivery promises'
    _check_company_auto = True

    order_id = fields.Many2one('purchase.order', required=True, readonly=True, check_company=True)
    company_id = fields.Many2one(related='order_id.company_id', store=True)
    # Mode is staged independently: editing a dialog must not revise the PO early.
    arrival_mode = fields.Selection([
        ('vendor', 'Current Vendor Defaults'), ('duration', 'Order Lead Time Override'), ('fixed', 'Fixed Expected Arrival'),
    ], required=True)
    days = fields.Integer()
    hours = fields.Float()
    calendar_id = fields.Many2one('resource.calendar', required=True, check_company=True)
    use_preferred_time = fields.Boolean()
    preferred_time = fields.Float()
    fixed_arrival = fields.Datetime()
    reason = fields.Text()
    line_ids = fields.One2many('purchase.delivery.reschedule.line', 'wizard_id')

    @api.model
    def _open(self, order):
        order.check_access('write')
        wizard = self.create({
            'order_id': order.id, 'arrival_mode': order.delivery_mode,
            'days': order.delivery_days, 'hours': order.delivery_hours,
            'calendar_id': order.delivery_calendar_id.id or order.company_id.receipt_followup_calendar_id.id,
            'use_preferred_time': order.delivery_use_preferred_time, 'preferred_time': order.delivery_preferred_time,
            'fixed_arrival': order.delivery_fixed_arrival,
            'line_ids': [Command.create({'order_line_id': line.id, 'manual_arrival': line.delivery_manual_arrival,
                                        'fixed_arrival': line.delivery_fixed_arrival})
                         for line in order.order_line.filtered(lambda item: not item.display_type and item.product_id
                             and (not item.move_ids or any(move.state not in ('done', 'cancel') for move in item.move_ids)))],
        })
        return {'type': 'ir.actions.act_window', 'name': _('Reschedule Outstanding Delivery'),
                'res_model': self._name, 'res_id': wizard.id, 'view_mode': 'form', 'target': 'new'}

    def action_apply(self):
        self.ensure_one()
        self.check_access('read')
        _logger.debug('[OVERDUE_RECEIPT][DELIVERY_RESCHEDULE][START] order_id=%s user_id=%s', self.order_id.id, self.env.uid)
        try:
            result = self._apply_revision()
            _logger.debug('[OVERDUE_RECEIPT][DELIVERY_RESCHEDULE][END] order_id=%s user_id=%s', self.order_id.id, self.env.uid)
            return result
        except Exception:
            _logger.exception('[OVERDUE_RECEIPT][DELIVERY_RESCHEDULE][ERROR] order_id=%s user_id=%s', self.order_id.id, self.env.uid)
            raise

    def _apply_revision(self):
        self.ensure_one()
        self.check_access('read')
        order = self.order_id
        order.check_access('write')
        if order.company_id not in self.env.companies or order.state != 'purchase':
            raise UserError(_('Choose an unlocked confirmed order in an allowed company.'))
        outstanding = order.order_line.filtered(lambda line: not line.display_type and line.product_id
            and (not line.move_ids or any(move.state not in ('done', 'cancel') for move in line.move_ids)))
        if not outstanding:
            raise UserError(_('No outstanding delivery lines remain on this order.'))
        if not (self.reason or '').strip():
            raise ValidationError(_('Record why the delivery promise is being changed.'))
        if self.days < 0 or self.hours < 0:
            raise ValidationError(_('Delivery days and hours cannot be negative.'))
        with self.env.cr.savepoint():
            # Existing confirmed POs keep their previous standard promise when
            # first opted into the new delivery planner.
            order._capture_standard_promises(order.date_approve)
            values = {
                'delivery_mode': self.arrival_mode, 'delivery_days': self.days, 'delivery_hours': self.hours,
                'delivery_calendar_id': self.calendar_id.id, 'delivery_use_preferred_time': self.use_preferred_time,
                'delivery_preferred_time': self.preferred_time, 'delivery_fixed_arrival': self.fixed_arrival,
                'delivery_change_reason': self.reason.strip(),
            }
            if self.arrival_mode == 'vendor':
                values.update(order._delivery_policy_values())
            order._write_delivery_internal(values)
            for row in self.line_ids:
                if row.order_line_id.order_id != order:
                    raise ValidationError(_('All rescheduled lines must belong to this purchase order.'))
                if row.order_line_id not in outstanding:
                    continue
                row.order_line_id._write_delivery_override({
                    'delivery_manual_arrival': row.manual_arrival, 'delivery_fixed_arrival': row.fixed_arrival,
                })
            order._apply_delivery_plan(order.date_approve, final=True)
            order.message_post(body=_('Outstanding delivery promises revised. Reason: %s') % self.reason.strip())
        return {'type': 'ir.actions.act_window_close'}


class PurchaseDeliveryRescheduleLine(models.TransientModel):
    _name = 'purchase.delivery.reschedule.line'
    _description = 'Purchase delivery revision line'

    wizard_id = fields.Many2one('purchase.delivery.reschedule', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='wizard_id.company_id', store=True)
    order_line_id = fields.Many2one('purchase.order.line', required=True, readonly=True)
    product_id = fields.Many2one(related='order_line_id.product_id')
    manual_arrival = fields.Boolean(string='Line Arrival Override')
    fixed_arrival = fields.Datetime(string='Line Agreed Arrival')
