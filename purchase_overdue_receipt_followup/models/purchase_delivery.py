import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

DELIVERY_INPUT_FIELDS = {
    'delivery_mode', 'delivery_days', 'delivery_hours', 'delivery_calendar_id',
    'delivery_use_preferred_time', 'delivery_preferred_time', 'delivery_fixed_arrival',
}
DELIVERY_AUDIT_FIELDS = {
    'delivery_policy_id', 'delivery_day_hours', 'delivery_start_at', 'delivery_original_arrival',
    'delivery_current_arrival', 'delivery_snapshot', 'delivery_revision_user_id', 'delivery_revision_at',
}


class PurchaseOrderDelivery(models.Model):
    _inherit = 'purchase.order'

    delivery_mode = fields.Selection([
        ('vendor', 'Vendor Default'), ('duration', 'RFQ Lead Time Override'), ('fixed', 'Fixed Expected Arrival'),
    ], default='vendor', required=True, tracking=True, copy=True)
    delivery_policy_id = fields.Many2one('purchase.vendor.delivery.policy', readonly=True, copy=False,
                                        check_company=True, ondelete='restrict')
    delivery_days = fields.Integer(string='Lead-time Days', default=0)
    delivery_hours = fields.Float(string='Additional Working Hours', default=0)
    delivery_day_hours = fields.Float(string='Hours per Lead-time Day', readonly=True, copy=False)
    delivery_total_hours = fields.Float(compute='_compute_delivery_total_hours', string='Total Working Hours')
    delivery_calendar_id = fields.Many2one('resource.calendar', string='Receiving Calendar', check_company=True,
        domain="[('company_id', 'in', [False, company_id]), ('flexible_hours', '=', False)]")
    delivery_timezone = fields.Selection(related='delivery_calendar_id.tz', string='Arrival Timezone')
    delivery_use_preferred_time = fields.Boolean(string='Preferred Arrival Time')
    delivery_preferred_time = fields.Float(string='Arrival Time')
    delivery_preview_start = fields.Datetime(string='Preview Start', default=fields.Datetime.now, copy=False)
    delivery_draft_arrival = fields.Datetime(string='Estimated Draft Arrival', compute='_compute_draft_arrival')
    delivery_fixed_arrival = fields.Datetime(string='Agreed Fixed Arrival', tracking=True)
    delivery_start_at = fields.Datetime(string='Calculation Start', readonly=True, copy=False)
    delivery_original_arrival = fields.Datetime(string='Original Promised Arrival', readonly=True, copy=False)
    delivery_current_arrival = fields.Datetime(string='Current Expected Arrival', readonly=True, copy=False, tracking=True)
    delivery_snapshot = fields.Json(string='Delivery Calculation Snapshot', readonly=True, copy=False)
    delivery_revision_user_id = fields.Many2one('res.users', readonly=True, copy=False)
    delivery_revision_at = fields.Datetime(readonly=True, copy=False)
    delivery_change_reason = fields.Text(string='Rescheduling Reason', copy=False)

    @api.depends('delivery_days', 'delivery_hours', 'delivery_day_hours')
    def _compute_delivery_total_hours(self):
        for order in self:
            order.delivery_total_hours = order.delivery_days * order.delivery_day_hours + order.delivery_hours

    @api.constrains('delivery_days', 'delivery_hours', 'delivery_fixed_arrival', 'delivery_mode')
    def _check_delivery_inputs(self):
        for order in self:
            if order.delivery_days < 0 or order.delivery_hours < 0:
                raise ValidationError(_('Delivery days and hours cannot be negative.'))
            if order.delivery_mode == 'fixed' and not order.delivery_fixed_arrival:
                raise ValidationError(_('Choose the agreed fixed arrival date and time.'))

    def _delivery_policy_values(self):
        self.ensure_one()
        return self.env['purchase.delivery.planning']._policy_values(self.partner_id, self.company_id)

    @api.depends('state', 'partner_id', 'company_id', 'date_order', 'delivery_preview_start', 'delivery_mode',
                 'delivery_days', 'delivery_hours', 'delivery_day_hours', 'delivery_calendar_id',
                 'delivery_use_preferred_time', 'delivery_preferred_time', 'delivery_fixed_arrival',
                 'delivery_policy_id.days', 'delivery_policy_id.hours', 'delivery_policy_id.calendar_id',
                 'delivery_policy_id.preferred_time', 'delivery_policy_id.use_preferred_time',
                 'company_id.delivery_hours_per_day', 'company_id.receipt_followup_calendar_id')
    def _compute_draft_arrival(self):
        for order in self:
            if order.state not in ('draft', 'sent', 'to approve') or not order.partner_id or not order.company_id:
                order.delivery_draft_arrival = False
                continue
            start = order.delivery_preview_start or order.date_order or fields.Datetime.now()
            handler = (getattr(order, '_delivery_preview_%s' % order.delivery_mode, None)
                       or getattr(order, '_delivery_arrival_%s' % order.delivery_mode, None))
            # Incomplete interactive inputs are validated on Preview/approval;
            # do not block opening a new draft before its fixed date is entered.
            if order.delivery_mode == 'fixed':
                order.delivery_draft_arrival = order.delivery_fixed_arrival
            elif order.delivery_mode != 'vendor' and not order.delivery_calendar_id:
                order.delivery_draft_arrival = False
            elif handler:
                order.delivery_draft_arrival = handler(start)
            else:
                order.delivery_draft_arrival = False

    def _delivery_preview_vendor(self, start):
        """Pure preview; safe for onchange/NewId records and cached per order."""
        values = self._delivery_policy_values()
        if not values['delivery_policy_id']:
            return False
        return self.env['purchase.delivery.planning']._calculate(
            self.company_id, self.env['resource.calendar'].browse(values['delivery_calendar_id']), start,
            values['delivery_days'], values['delivery_hours'], values['delivery_day_hours'],
            values['delivery_use_preferred_time'], values['delivery_preferred_time'])

    @api.onchange('delivery_mode', 'delivery_days', 'delivery_hours', 'delivery_calendar_id',
                 'delivery_use_preferred_time', 'delivery_preferred_time', 'delivery_fixed_arrival',
                 'delivery_preview_start', 'partner_id', 'company_id')
    def _onchange_draft_delivery_arrival(self):
        for order in self.filtered(lambda item: item.state in ('draft', 'sent', 'to approve')):
            arrival = order.delivery_draft_arrival
            if arrival:
                for line in order.order_line.filtered(lambda item: not item.display_type and item.product_id):
                    line.date_planned = line.delivery_fixed_arrival if line.delivery_manual_arrival else arrival
                order.date_planned = min(order.order_line.filtered(
                    lambda item: not item.display_type and item.date_planned).mapped('date_planned') or [arrival])

    @api.onchange('date_planned')
    def onchange_date_planned(self):
        result = super().onchange_date_planned()
        # Odoo's header-date onchange normally assigns one date to every line.
        # Keep explicitly agreed split-delivery promises when that callback runs.
        for line in self.order_line.filtered(lambda item: item.delivery_manual_arrival and item.delivery_fixed_arrival):
            line.date_planned = line.delivery_fixed_arrival
        return result

    def _sync_draft_delivery_arrival(self):
        for order in self.filtered(lambda item: item.state in ('draft', 'sent', 'to approve')):
            _logger.debug('[OVERDUE_RECEIPT][DRAFT_DELIVERY][START] order_id=%s', order.id)
            try:
                arrival = order.delivery_draft_arrival
                if not arrival:
                    _logger.debug('[OVERDUE_RECEIPT][DRAFT_DELIVERY][END] order_id=%s outcome=standard_odoo', order.id)
                    continue
                lines = order.order_line.filtered(lambda item: not item.display_type and item.product_id)
                for line in lines:
                    expected = line.delivery_fixed_arrival if line.delivery_manual_arrival else arrival
                    if expected:
                        line._apply_delivery_arrival(expected)
                order._write_delivery_internal({'date_planned': min(lines.mapped('date_planned') or [arrival])})
                _logger.debug('[OVERDUE_RECEIPT][DRAFT_DELIVERY][END] order_id=%s arrival=%s', order.id, order.date_planned)
            except Exception:
                _logger.exception('[OVERDUE_RECEIPT][DRAFT_DELIVERY][ERROR] order_id=%s', order.id)
                raise

    @api.onchange('partner_id', 'company_id')
    def _onchange_delivery_vendor(self):
        for order in self.filtered(lambda item: item.state in ('draft', 'sent') and item.delivery_mode == 'vendor'):
            if order.partner_id and order.company_id:
                order.update(order._delivery_policy_values())

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for values in values_list:
            if DELIVERY_AUDIT_FIELDS.intersection(values):
                raise AccessError(_('Delivery calculation history is maintained by the delivery planner.'))
            values = dict(values)
            partner = self.env['res.partner'].browse(values.get('partner_id'))
            company = self.env['res.company'].browse(values.get('company_id')) or self.env.company
            if partner:
                defaults = self.env['purchase.delivery.planning']._policy_values(partner, company)
                for key, value in defaults.items():
                    values.setdefault(key, value)
            prepared.append(values)
        orders = super().create(prepared)
        orders._sync_draft_delivery_arrival()
        return orders

    def write(self, values):
        if DELIVERY_AUDIT_FIELDS.intersection(values):
            raise AccessError(_('Delivery calculation history is maintained by the delivery planner.'))
        values = dict(values)
        confirmed = self.filtered(lambda order: order.state in ('purchase', 'done'))
        if 'date_planned' in values and any(
            order._has_managed_delivery() and fields.Datetime.to_datetime(values['date_planned']) != order.date_planned
            for order in confirmed
        ):
            raise UserError(_('Use Reschedule Delivery to revise the expected arrival on this planned order.'))
        delivery_change = DELIVERY_INPUT_FIELDS.intersection(values)
        if delivery_change and any(order.state == 'done' for order in confirmed):
            raise UserError(_('Unlock the purchase order before rescheduling delivery.'))
        if confirmed and delivery_change and not (values.get('delivery_change_reason') or '').strip():
            raise ValidationError(_('Provide a new rescheduling reason when changing confirmed delivery terms.'))
        result = super().write(values)
        if delivery_change:
            for order in confirmed:
                order._apply_delivery_plan(order.date_approve, final=True)
        if (DELIVERY_INPUT_FIELDS | {'partner_id', 'company_id', 'delivery_preview_start', 'date_order'}).intersection(values):
            (self - confirmed)._sync_draft_delivery_arrival()
        return result

    def _has_managed_delivery(self):
        self.ensure_one()
        return bool(self.delivery_snapshot and self.delivery_snapshot.get('mode') not in (False, 'standard'))

    def _delivery_arrival_vendor(self, start):
        """No policy preserves standard Odoo scheduling. Existing snapshots stay frozen."""
        if not self.delivery_original_arrival:
            self._write_delivery_internal(self._delivery_policy_values())
        if not self.delivery_policy_id:
            return False
        return self._delivery_arrival_duration(start)

    def _delivery_arrival_duration(self, start):
        return self.env['purchase.delivery.planning']._calculate(
            self.company_id, self.delivery_calendar_id, start, self.delivery_days, self.delivery_hours,
            self.delivery_day_hours, self.delivery_use_preferred_time, self.delivery_preferred_time)

    def _delivery_arrival_fixed(self, start):
        planner = self.env['purchase.delivery.planning']
        planner._validate_calendar(self.delivery_calendar_id, self.company_id)
        if not self.delivery_fixed_arrival or self.delivery_fixed_arrival < start:
            raise ValidationError(_('Agreed fixed arrival cannot be earlier than the calculation start / PO confirmation.'))
        if not planner._is_valid_arrival(self.delivery_calendar_id, self.delivery_fixed_arrival):
            raise ValidationError(_('Agreed fixed arrival is outside receiving hours. Choose an open receiving date/time.'))
        return self.delivery_fixed_arrival

    def _write_delivery_internal(self, values):
        # Private, not callable by RPC; normal write rights and all parent
        # business validations still apply. No sudo or context bypass flag.
        return super(PurchaseOrderDelivery, self).write(values)

    def _capture_standard_promises(self, start):
        self.ensure_one()
        self.check_access('write')
        if self.delivery_original_arrival or not self.date_planned:
            return
        for line in self.order_line.filtered(lambda item: not item.display_type and item.product_id):
            if not line.delivery_original_arrival and line.date_planned:
                line._write_delivery_override({'delivery_original_arrival': line.date_planned})
        self._write_delivery_internal({
            'delivery_original_arrival': self.date_planned, 'delivery_current_arrival': self.date_planned,
            'delivery_start_at': start,
            'delivery_snapshot': {'mode': 'standard', 'start': fields.Datetime.to_string(start),
                                  'arrival': fields.Datetime.to_string(self.date_planned)},
        })

    def _apply_delivery_plan(self, start, final=False):
        self.ensure_one()
        self.check_access('write')
        _logger.debug('[OVERDUE_RECEIPT][DELIVERY_APPLY][START] order_id=%s mode=%s final=%s', self.id, self.delivery_mode, final)
        try:
            # Selection additions extend the workflow by defining the matching
            # handler through Odoo inheritance, without growing a dispatch chain.
            handler = getattr(self, '_delivery_arrival_%s' % self.delivery_mode, None)
            if not handler:
                raise UserError(_('No planner is registered for this arrival mode.'))
            arrival = handler(start)
            lines = self.order_line.filtered(lambda line: not line.display_type and line.product_id
                and (not line.move_ids or any(move.state not in ('done', 'cancel') for move in line.move_ids)))
            standard_dates = not arrival
            if not arrival and not lines.filtered('delivery_manual_arrival'):
                if final:
                    self._capture_standard_promises(start)
                _logger.debug('[OVERDUE_RECEIPT][DELIVERY_APPLY][END] order_id=%s outcome=standard_odoo', self.id)
                return
            if standard_dates:
                self.env['purchase.delivery.planning']._validate_calendar(self.delivery_calendar_id, self.company_id)
            arrivals = []
            for line in lines:
                expected = (line.delivery_fixed_arrival if line.delivery_manual_arrival
                            else line.date_planned if standard_dates else arrival)
                planner = self.env['purchase.delivery.planning']
                if (not standard_dates or line.delivery_manual_arrival) and (
                    not expected or expected < start or not planner._is_valid_arrival(self.delivery_calendar_id, expected)
                ):
                    raise ValidationError(_('A product line arrival is missing, earlier than confirmation, or outside receiving hours.'))
                line._apply_delivery_arrival(expected, final=final)
                arrivals.append(expected)
            current = min(arrivals) if arrivals else arrival
            audit = {
                'delivery_start_at': start, 'delivery_current_arrival': current,
                'delivery_snapshot': {
                    'mode': self.delivery_mode, 'policy_id': self.delivery_policy_id.id,
                    'days': self.delivery_days, 'hours': self.delivery_hours, 'day_hours': self.delivery_day_hours,
                    'calendar_id': self.delivery_calendar_id.id, 'timezone': self.delivery_calendar_id.tz,
                    'preferred_enabled': self.delivery_use_preferred_time, 'preferred_time': self.delivery_preferred_time,
                    'start': fields.Datetime.to_string(start), 'arrival': fields.Datetime.to_string(current),
                },
            }
            if final:
                if not self.delivery_original_arrival:
                    audit['delivery_original_arrival'] = current
                audit.update(delivery_revision_user_id=self.env.uid, delivery_revision_at=fields.Datetime.now())
            self._write_delivery_internal(audit)
            _logger.debug('[OVERDUE_RECEIPT][DELIVERY_APPLY][END] order_id=%s arrival=%s final=%s', self.id, current, final)
        except Exception:
            _logger.exception('[OVERDUE_RECEIPT][DELIVERY_APPLY][ERROR] order_id=%s', self.id)
            raise

    def action_preview_delivery(self):
        self.ensure_one()
        self.check_access('write')
        if self.state not in ('draft', 'sent', 'to approve'):
            raise UserError(_('Use rescheduling on confirmed orders.'))
        self._apply_delivery_plan(self.delivery_preview_start or fields.Datetime.now())
        return False

    def action_restore_vendor_delivery(self):
        self.ensure_one()
        self.check_access('write')
        if self.state not in ('draft', 'sent', 'to approve'):
            raise UserError(_('To revise a confirmed order, enter a rescheduling reason and change its delivery terms.'))
        self._write_delivery_internal(dict(self._delivery_policy_values(), delivery_mode='vendor',
                                          delivery_snapshot=False, delivery_start_at=False, delivery_current_arrival=False))
        if not self.delivery_policy_id:
            for line in self.order_line.filtered(lambda item: not item.display_type and item.product_id
                                                 and not item.delivery_manual_arrival):
                seller = line.product_id.with_company(self.company_id)._select_seller(
                    partner_id=self.partner_id, quantity=line.product_qty,
                    date=(self.date_order or fields.Datetime.now()).date(), uom_id=line.product_uom)
                line._update_date_planned(line._get_date_planned(seller))
        self._apply_delivery_plan(self.delivery_preview_start or fields.Datetime.now())
        return False

    def action_reschedule_delivery(self):
        self.ensure_one()
        self.check_access('write')
        if self.state != 'purchase':
            raise UserError(_('Only an unlocked confirmed purchase order can be rescheduled.'))
        return self.env['purchase.delivery.reschedule']._open(self)

    def button_approve(self, force=False):
        candidates = self.filtered(lambda order: order.state not in ('purchase', 'done', 'cancel'))
        result = super().button_approve(force=force)
        for order in candidates.filtered(lambda item: item.state in ('purchase', 'done')):
            order._apply_delivery_plan(order.date_approve, final=True)
        return result


class PurchaseOrderLineDelivery(models.Model):
    _inherit = 'purchase.order.line'

    delivery_manual_arrival = fields.Boolean(string='Line Arrival Override', copy=True)
    delivery_fixed_arrival = fields.Datetime(string='Line Agreed Arrival', copy=True)
    delivery_original_arrival = fields.Datetime(string='Original Promised Arrival', readonly=True, copy=False)

    def _get_date_planned(self, seller, po=False):
        standard = super()._get_date_planned(seller, po=po)
        order = po or self.order_id
        if order and order.state in ('draft', 'sent', 'to approve'):
            if self.delivery_manual_arrival and self.delivery_fixed_arrival:
                return self.delivery_fixed_arrival
            return order.delivery_draft_arrival or standard
        return standard

    def write(self, values):
        if 'delivery_original_arrival' in values:
            raise AccessError(_('Original delivery promises are maintained by the delivery planner.'))
        changing = {'delivery_manual_arrival', 'delivery_fixed_arrival'}.intersection(values)
        confirmed = self.order_id.filtered(lambda order: order.state in ('purchase', 'done'))
        if 'date_planned' in values and any(
            line.order_id in confirmed and line.order_id._has_managed_delivery()
            and fields.Datetime.to_datetime(values['date_planned']) != line.date_planned for line in self
        ):
            raise UserError(_('Use Reschedule Delivery to revise an agreed product-line arrival.'))
        if changing and confirmed:
            raise UserError(_('Use the Reschedule Delivery dialog to revise confirmed line arrivals.'))
        return super().write(values)

    @api.model_create_multi
    def create(self, values_list):
        if any('delivery_original_arrival' in values for values in values_list):
            raise AccessError(_('Original delivery promises are maintained by the delivery planner.'))
        return super().create(values_list)

    def _apply_delivery_arrival(self, arrival, final=False):
        self.ensure_one()
        values = {}
        if final and not self.delivery_original_arrival:
            values['delivery_original_arrival'] = arrival
        open_moves = self.move_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
        # Do not rewrite the purchase line's historical date after a partial receipt.
        if not self.move_ids.filtered(lambda move: move.state == 'done'):
            values['date_planned'] = arrival
        if values:
            super(PurchaseOrderLineDelivery, self).write(values)
        if final and open_moves:
            open_moves.write({'date': arrival, 'date_deadline': arrival})

    def _write_delivery_override(self, values):
        return super(PurchaseOrderLineDelivery, self).write(values)
