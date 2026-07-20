"""
Core M-Pesa transaction model.
State machine: new → pending_pos → reconciled_pos | reconciled_invoice | unmatched
mpesa_ref is the idempotency key — unique per Safaricom transaction.
"""
import logging

from odoo import api, fields, models

_log = logging.getLogger(__name__)


class MpesaTransaction(models.Model):
    _name        = 'mpesa.transaction'
    _description = 'M-Pesa C2B Transaction'
    _order       = 'transaction_date desc'
    _rec_name    = 'mpesa_ref'

    # ------------------------------------------------------------------
    # Safaricom transaction data
    # ------------------------------------------------------------------
    mpesa_ref        = fields.Char('M-Pesa Reference', required=True, index=True)
    amount           = fields.Monetary('Amount (Ksh)', currency_field='currency_id')
    amount_used      = fields.Monetary(
        'Amount Used', currency_field='currency_id', default=0.0,
        help='Amount already consumed by POS/invoice reconciliation.',
    )
    amount_refunded = fields.Monetary(
        'Amount Refunded', currency_field='currency_id',
        compute='_compute_case_amounts', store=True,
        help='Amount paid back through an internal refund case.',
    )
    amount_reversed = fields.Monetary(
        'Amount Reversed by Safaricom', currency_field='currency_id',
        compute='_compute_case_amounts', store=True,
        help='Amount reversed or deducted by Safaricom after a reversal complaint.',
    )
    amount_frozen = fields.Monetary(
        'Amount Frozen', currency_field='currency_id',
        compute='_compute_case_amounts', store=True,
        help='Amount blocked while a Safaricom dispute is under review.',
    )
    amount_remaining = fields.Monetary(
        'Amount Remaining', currency_field='currency_id',
        compute='_compute_amount_remaining', store=True,
    )
    currency_id      = fields.Many2one(
        'res.currency', default=lambda s: s.env.ref('base.KES', raise_if_not_found=False),
    )
    sender_name      = fields.Char('Sender Name')
    sender_phone     = fields.Char('Sender Phone', index=True)
    transaction_date = fields.Datetime('Transaction Date', index=True)
    utility_balance  = fields.Monetary('Till Balance After', currency_field='currency_id')
    transaction_cost = fields.Monetary('Transaction Cost', currency_field='currency_id')

    # ------------------------------------------------------------------
    # Odoo linkages
    # ------------------------------------------------------------------
    partner_id   = fields.Many2one('res.partner', 'Customer', ondelete='set null', index=True)
    raw_log_id   = fields.Many2one('mpesa.sms.raw.log', 'Source SMS', ondelete='set null')
    invoice_id   = fields.Many2one('account.move', 'Invoice', ondelete='set null')
    pos_usage_ids = fields.One2many(
        'mpesa.transaction.usage', 'transaction_id', 'POS Usage',
    )
    pos_order_ids = fields.Many2many(
        'pos.order', string='POS Orders',
        compute='_compute_pos_order_ids', store=False,
    )
    refund_case_ids = fields.One2many(
        'mpesa.transaction.refund.case', 'transaction_id', 'Refund/Dispute Cases',
    )
    refund_case_count = fields.Integer(
        'Refund/Dispute Case Count', compute='_compute_refund_case_count',
    )

    # ------------------------------------------------------------------
    # POS locking (used by mpesa_c2b_pos)
    # ------------------------------------------------------------------
    pos_session_id    = fields.Many2one('pos.session', 'Locked by Session', ondelete='set null')
    pos_order_id      = fields.Many2one('pos.order', 'POS Order', ondelete='set null')
    pos_lock_expires  = fields.Datetime('Lock Expires At')
    locked_by_cashier = fields.Many2one('res.users', 'Locked by Cashier', ondelete='set null')
    lock_token        = fields.Char('Lock Token')

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    state = fields.Selection(
        [
            ('new',               'New'),
            ('unmatched',         'Unmatched Partner'),
            ('pending_pos',       'Held by POS'),
            ('partial_pos',       'Partially Used (POS)'),
            ('reconciled_pos',    'Reconciled (POS)'),
            ('reconciled_invoice','Reconciled (Invoice)'),
            ('refund_requested',  'Refund Requested'),
            ('refund_approved',   'Refund Approved'),
            ('partially_refunded','Partially Refunded'),
            ('refunded',          'Refunded'),
            ('safaricom_dispute', 'Safaricom Dispute'),
            ('reversal_accepted', 'Reversal Accepted'),
            ('reversal_objected', 'Reversal Objected'),
            ('reversed_safaricom','Reversed by Safaricom'),
            ('dispute_won',       'Dispute Won'),
            ('dispute_lost',      'Dispute Lost'),
            ('cancelled',         'Cancelled'),
        ],
        default='new', required=True, index=True,
    )

    _sql_constraints = [
        ('mpesa_ref_uniq', 'UNIQUE(mpesa_ref)',
         'M-Pesa reference already exists — duplicate transaction rejected.'),
    ]

    # ------------------------------------------------------------------
    # Computed display
    # ------------------------------------------------------------------

    @api.depends('amount', 'amount_used', 'amount_refunded', 'amount_reversed', 'amount_frozen')
    def _compute_amount_remaining(self):
        for rec in self:
            rec.amount_remaining = max(
                (rec.amount or 0.0)
                - (rec.amount_used or 0.0)
                - (rec.amount_refunded or 0.0)
                - (rec.amount_reversed or 0.0)
                - (rec.amount_frozen or 0.0),
                0.0,
            )

    @api.depends('refund_case_ids.amount', 'refund_case_ids.state', 'refund_case_ids.case_type')
    def _compute_case_amounts(self):
        for rec in self:
            paid_refunds = rec.refund_case_ids.filtered(
                lambda c: c.case_type == 'internal_refund' and c.state == 'paid'
            )
            reversed_cases = rec.refund_case_ids.filtered(
                lambda c: c.case_type == 'safaricom_reversal' and c.state == 'reversed'
            )
            frozen_cases = rec.refund_case_ids.filtered(
                lambda c: (
                    c.case_type == 'safaricom_reversal'
                    and c.state in ('under_review', 'accepted', 'objected')
                )
            )
            rec.amount_refunded = sum(paid_refunds.mapped('amount'))
            rec.amount_reversed = sum(reversed_cases.mapped('amount'))
            rec.amount_frozen = sum(frozen_cases.mapped('amount'))

    def _compute_refund_case_count(self):
        for rec in self:
            rec.refund_case_count = len(rec.refund_case_ids)

    @api.depends('pos_usage_ids.pos_order_id')
    def _compute_pos_order_ids(self):
        for rec in self:
            orders = rec.pos_usage_ids.mapped('pos_order_id')
            if rec.pos_order_id:
                orders |= rec.pos_order_id
            rec.pos_order_ids = orders

    @api.depends('sender_phone')
    def _compute_display_phone(self):
        for rec in self:
            p = rec.sender_phone or ''
            rec.display_phone = (
                '0' + p[3:4] + p[4:7] + ' ' + p[7:] if p.startswith('254') and len(p) == 12
                else p
            )
    display_phone = fields.Char(compute='_compute_display_phone', store=False)

    # ------------------------------------------------------------------
    # Business methods
    # ------------------------------------------------------------------

    def action_cancel(self):
        for rec in self.filtered(lambda r: r.state in ('new', 'unmatched')):
            rec.state = 'cancelled'
            _log.info("Transaction %s cancelled by %s", rec.mpesa_ref, self.env.user.name)

    def action_open_refund_cases(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Refund/Dispute Cases',
            'res_model': 'mpesa.transaction.refund.case',
            'view_mode': 'list,form',
            'domain': [('transaction_id', '=', self.id)],
            'context': {
                'default_transaction_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_currency_id': self.currency_id.id,
                'default_amount': self.amount_remaining,
            },
        }

    def action_request_internal_refund(self):
        self.ensure_one()
        case = self.env['mpesa.transaction.refund.case'].create({
            'transaction_id': self.id,
            'case_type': 'internal_refund',
            'reason': 'Internal refund requested.',
            'amount': self.amount_remaining,
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
        })
        case.action_submit()
        return self.action_open_refund_cases()

    def action_open_safaricom_dispute(self):
        self.ensure_one()
        case = self.env['mpesa.transaction.refund.case'].create({
            'transaction_id': self.id,
            'case_type': 'safaricom_reversal',
            'reason': 'Safaricom reversal complaint received.',
            'amount': self.amount_remaining or self.amount,
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
        })
        case.action_submit()
        return self.action_open_refund_cases()

    def action_reset_to_new(self):
        """Manager-only: reset stuck transactions."""
        self.ensure_one()
        self.write({'state': 'new', 'pos_session_id': False, 'lock_token': False})
        _log.warning("Transaction %s reset to new by %s", self.mpesa_ref, self.env.user.name)

    def action_recompute_availability_state(self):
        for rec in self:
            rec.write({'state': rec._available_state()})
            _log.info("Transaction %s availability state recomputed by %s", rec.mpesa_ref, self.env.user.name)

    def _available_state(self):
        self.ensure_one()
        if self.amount_used:
            return 'partial_pos' if self.amount_remaining else 'reconciled_pos'
        if self.amount_refunded and self.amount_remaining:
            return 'partially_refunded'
        if self.amount_reversed and self.amount_remaining:
            return 'new' if self.partner_id else 'unmatched'
        if self.amount_remaining:
            return 'new' if self.partner_id else 'unmatched'
        if self.amount_refunded:
            return 'refunded'
        if self.amount_reversed:
            return 'reversed_safaricom'
        return 'new' if self.partner_id else 'unmatched'

    @api.model
    def _cron_release_expired_pos_locks(self):
        expired = self.search([
            ('state', '=', 'pending_pos'),
            ('pos_lock_expires', '<', fields.Datetime.now()),
        ])
        expired.write({'state': 'new', 'pos_session_id': False, 'lock_token': False})
        _log.info("Released %d expired M-Pesa POS lock(s)", len(expired))
