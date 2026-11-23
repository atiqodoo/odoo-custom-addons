"""Immutable COD payment arrangements and controlled POS re-promising."""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)


class PosCodPromiseArrangement(models.Model):
    _name = 'pos.cod.promise.arrangement'
    _description = 'COD Customer Payment Arrangement'
    _order = 'order_id, sequence desc, id desc'

    order_id = fields.Many2one('pos.order', required=True, index=True, ondelete='cascade')
    sequence = fields.Integer(required=True, readonly=True)
    arrangement_type = fields.Selection([
        ('dispatch', 'Initial Dispatch Promise'),
        ('legacy', 'Legacy Order First Promise'),
        ('repromise', 'Re-promise'),
    ], required=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', related='order_id.partner_id', store=True, index=True)
    company_id = fields.Many2one('res.company', related='order_id.company_id', store=True, index=True)
    session_id = fields.Many2one('pos.session', required=True, readonly=True, index=True, ondelete='restrict')
    config_id = fields.Many2one('pos.config', related='session_id.config_id', store=True, index=True)
    arranged_by_id = fields.Many2one('res.users', required=True, readonly=True, index=True)
    arranged_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now, index=True)
    previous_promised_at = fields.Datetime(readonly=True)
    promised_at = fields.Datetime(required=True, readonly=True, index=True)
    arrangement_note = fields.Text(required=True, readonly=True)
    customer_commitment = fields.Boolean(required=True, readonly=True, default=True, index=True)
    promised_amount = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    amount_paid_at_arrangement = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    amount_collected_by_due = fields.Monetary(readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='order_id.currency_id', store=True)
    outcome = fields.Selection([
        ('active', 'Active'),
        ('kept', 'Kept On Time'),
        ('partially_kept', 'Partially Kept'),
        ('broken', 'Broken'),
        ('late_paid', 'Paid Late'),
        ('returned', 'Returned'),
        ('cancelled', 'Cancelled'),
    ], required=True, readonly=True, default='active', index=True)
    commitment_result = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failure', 'Failure'),
        ('excluded', 'Excluded'),
    ], compute='_compute_commitment_result', store=True, index=True)
    resolved_at = fields.Datetime(readonly=True)

    _sql_constraints = [
        ('sequence_positive', 'CHECK(sequence > 0)', 'Arrangement sequence must be positive.'),
        ('order_sequence_unique', 'UNIQUE(order_id, sequence)',
         'Each COD arrangement must have a unique sequence.'),
    ]

    @api.depends('outcome', 'customer_commitment')
    def _compute_commitment_result(self):
        for arrangement in self:
            if not arrangement.customer_commitment or arrangement.outcome in ('returned', 'cancelled'):
                arrangement.commitment_result = 'excluded'
            elif arrangement.outcome == 'active':
                arrangement.commitment_result = 'pending'
            elif arrangement.outcome == 'kept':
                arrangement.commitment_result = 'success'
            else:
                arrangement.commitment_result = 'failure'

    def _amount_collected_by(self, deadline):
        self.ensure_one()
        collections = self.order_id.cod_collection_ids.filtered(
            lambda item: item.kind == 'payment'
            and item.create_date
            and item.create_date <= deadline
        )
        return max(sum(collections.mapped('amount')) - self.amount_paid_at_arrangement, 0)

    def _finalize_expired(self, now=None):
        now = now or fields.Datetime.now()
        for arrangement in self.sudo().filtered(
                lambda item: item.outcome == 'active' and item.promised_at <= now):
            collected = arrangement._amount_collected_by(arrangement.promised_at)
            outcome = 'partially_kept' if arrangement.currency_id.compare_amounts(collected, 0) > 0 else 'broken'
            arrangement.write({
                'outcome': outcome,
                'amount_collected_by_due': collected,
                'resolved_at': now,
            })

    def _record_order_resolution(self, kind):
        """Update only the latest arrangement after a collection/return event."""
        for order in self.mapped('order_id'):
            arrangement = self.sudo().search([
                ('order_id', '=', order.id),
            ], order='sequence desc', limit=1)
            if not arrangement:
                continue
            now = fields.Datetime.now()
            collected = arrangement._amount_collected_by(arrangement.promised_at)
            values = {'amount_collected_by_due': collected}
            if order.cod_state == 'returned':
                values.update(outcome='returned', resolved_at=now)
            elif order.currency_id.compare_amounts(order._cod_open_amount(), 0) <= 0:
                values.update(
                    outcome='kept' if now <= arrangement.promised_at else 'late_paid',
                    resolved_at=now,
                )
            elif now > arrangement.promised_at:
                values.update(
                    outcome='partially_kept' if collected else 'broken',
                    resolved_at=now,
                )
            arrangement.write(values)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    cod_arrangement_ids = fields.One2many(
        'pos.cod.promise.arrangement', 'order_id', string='Customer Payment Arrangements', copy=False
    )
    cod_arrangement_count = fields.Integer(compute='_compute_cod_arrangement_count')

    def _compute_cod_arrangement_count(self):
        counts = self.env['pos.cod.promise.arrangement']._read_group(
            [('order_id', 'in', self.ids)], ['order_id'], ['__count']
        ) if self.ids else []
        count_by_order = {order.id: count for order, count in counts}
        for order in self:
            order.cod_arrangement_count = count_by_order.get(order.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders.filtered(lambda item: item.is_cod and item.cod_promised_payment_at):
            order._cod_create_arrangement({
                'arrangement_type': 'dispatch',
                'session_id': order.session_id.id,
                'promised_at': order.cod_promised_payment_at,
                'arrangement_note': _('Initial promise captured at COD dispatch.'),
            })
        return orders

    def _cod_create_arrangement(self, values):
        self.ensure_one()
        _logger.debug(
            '[COD][ARRANGEMENT_CREATE][START] order_id=%s type=%s user_id=%s',
            self.id, values.get('arrangement_type'), self.env.uid,
        )
        try:
            sequence = self.env['pos.cod.promise.arrangement'].sudo().search_count([
                ('order_id', '=', self.id),
            ]) + 1
            arrangement = self.env['pos.cod.promise.arrangement'].sudo().create({
                'order_id': self.id,
                'sequence': sequence,
                'arrangement_type': values['arrangement_type'],
                'session_id': values['session_id'],
                'arranged_by_id': self.env.uid,
                'arranged_at': values.get('arranged_at') or fields.Datetime.now(),
                'previous_promised_at': values.get('previous_promised_at'),
                'promised_at': values['promised_at'],
                'arrangement_note': values['arrangement_note'],
                'customer_commitment': values.get('customer_commitment', True),
                'promised_amount': values.get('promised_amount', self._cod_open_amount()),
                'amount_paid_at_arrangement': values.get(
                    'amount_paid_at_arrangement', self._cod_paid_total()
                ),
                'outcome': values.get('outcome', 'active'),
                'amount_collected_by_due': values.get('amount_collected_by_due', 0),
                'resolved_at': values.get('resolved_at'),
            })
        except Exception:
            _logger.debug('[COD][ARRANGEMENT_CREATE][ERROR] order_id=%s', self.id)
            raise
        _logger.debug(
            '[COD][ARRANGEMENT_CREATE][END] arrangement_id=%s order_id=%s type=%s note_length=%s',
            arrangement.id, self.id, arrangement.arrangement_type, len(arrangement.arrangement_note or ''),
        )
        return arrangement

    @api.model
    def cod_set_payment_arrangement(self, payload):
        payload = payload or {}
        order_id = int(payload.get('order_id') or 0)
        config_id = int(payload.get('config_id') or 0)
        session_id = int(payload.get('session_id') or 0)
        note = (payload.get('note') or '').strip()
        _logger.debug(
            '[COD][ARRANGEMENT_SET][START] order_id=%s config_id=%s session_id=%s user_id=%s note_length=%s',
            order_id, config_id, session_id, self.env.uid, len(note),
        )
        try:
            config = self.env['pos.config'].browse(config_id).exists()
            session = self.env['pos.session'].browse(session_id).exists()
            order = self.browse(order_id).exists()
            if not config or not session or not order:
                raise ValidationError(_('The COD order, POS, or current session is unavailable.'))
            config._cod_promise_access()
            order.check_access('read')
            if session.config_id != config or session.state not in ('opened', 'closing_control'):
                raise ValidationError(_('Use an open session for the selected POS.'))
            if order.company_id != config.company_id or order.company_id not in self.env.companies:
                raise AccessError(_('The COD order is outside the current POS company.'))
            if not order.is_cod or order.cod_state not in ('pending', 'partial'):
                raise ValidationError(_('Only open COD orders can receive a payment arrangement.'))
            if order.currency_id.compare_amounts(order._cod_open_amount(), 0) <= 0:
                raise ValidationError(_('This COD order has no open balance.'))
            if not note:
                raise ValidationError(_('Enter the customer arrangement note.'))
            if len(note) > 4000:
                raise ValidationError(_('The customer arrangement note cannot exceed 4,000 characters.'))
            promised_at = fields.Datetime.to_datetime(payload.get('promised_at'))
            now = fields.Datetime.now()
            if not promised_at or promised_at <= now:
                raise ValidationError(_('Select a new promised payment date and time in the future.'))

            # Serialize updates so two terminals cannot create competing promises.
            self.env.cr.execute('SELECT id FROM pos_order WHERE id = %s FOR UPDATE', [order.id])
            order.invalidate_recordset(['cod_promised_payment_at'])
            current = order.cod_promised_payment_at
            expected_value = payload.get('expected_promised_at')
            expected = fields.Datetime.to_datetime(expected_value) if expected_value else False
            if current != expected:
                raise ValidationError(_('The promise changed on another terminal. Refresh and try again.'))
            if current and current > now:
                raise ValidationError(_('The current customer promise has not expired yet.'))

            active = order.cod_arrangement_ids.filtered(lambda item: item.outcome == 'active')
            active._finalize_expired(now)
            if current and not order.cod_arrangement_ids.filtered(
                    lambda item: item.promised_at == current):
                collected = sum(order.cod_collection_ids.filtered(
                    lambda item: item.kind == 'payment' and item.create_date <= current
                ).mapped('amount'))
                order._cod_create_arrangement({
                    'arrangement_type': 'dispatch',
                    'session_id': order.session_id.id,
                    'arranged_at': order.date_order,
                    'promised_at': current,
                    'arrangement_note': _('Imported promise; no customer arrangement note was recorded.'),
                    'promised_amount': order.amount_total,
                    'amount_paid_at_arrangement': 0,
                    'outcome': 'partially_kept' if collected else 'broken',
                    'amount_collected_by_due': collected,
                    'resolved_at': now,
                })

            arrangement_type = 'repromise' if current else 'legacy'
            arrangement = order._cod_create_arrangement({
                'arrangement_type': arrangement_type,
                'session_id': session.id,
                'previous_promised_at': current,
                'promised_at': promised_at,
                'arrangement_note': note,
            })
            order.write({'cod_promised_payment_at': promised_at})
            result = {
                'success': True,
                'arrangement_id': arrangement.id,
                'promised_at': fields.Datetime.to_string(promised_at),
                'arrangement_count': order.cod_arrangement_count,
            }
        except Exception:
            _logger.debug('[COD][ARRANGEMENT_SET][ERROR] order_id=%s user_id=%s', order_id, self.env.uid)
            raise
        _logger.debug(
            '[COD][ARRANGEMENT_SET][END] order_id=%s arrangement_id=%s', order_id, arrangement.id
        )
        return result


class PosCodCollection(models.Model):
    _inherit = 'pos.cod.collection'

    @api.model_create_multi
    def create(self, vals_list):
        collections = super().create(vals_list)
        collections.flush_recordset(['create_date'])
        orders = collections.mapped('order_id')
        orders.invalidate_recordset(['cod_collection_ids'])
        arrangements = orders.mapped('cod_arrangement_ids')
        if arrangements:
            _logger.debug(
                '[COD][ARRANGEMENT_OUTCOME][START] collection_ids=%s order_ids=%s',
                collections.ids, collections.mapped('order_id').ids,
            )
            try:
                arrangements._record_order_resolution(collections[-1].kind)
            except Exception:
                _logger.debug(
                    '[COD][ARRANGEMENT_OUTCOME][ERROR] collection_ids=%s', collections.ids
                )
                raise
            _logger.debug(
                '[COD][ARRANGEMENT_OUTCOME][END] collection_ids=%s', collections.ids
            )
        return collections
