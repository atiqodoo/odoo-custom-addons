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

    @api.depends('amount', 'amount_used')
    def _compute_amount_remaining(self):
        for rec in self:
            rec.amount_remaining = max((rec.amount or 0.0) - (rec.amount_used or 0.0), 0.0)

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

    def action_reset_to_new(self):
        """Manager-only: reset stuck transactions."""
        self.ensure_one()
        self.write({'state': 'new', 'pos_session_id': False, 'lock_token': False})
        _log.warning("Transaction %s reset to new by %s", self.mpesa_ref, self.env.user.name)

    @api.model
    def _cron_release_expired_pos_locks(self):
        expired = self.search([
            ('state', '=', 'pending_pos'),
            ('pos_lock_expires', '<', fields.Datetime.now()),
        ])
        expired.write({'state': 'new', 'pos_session_id': False, 'lock_token': False})
        _log.info("Released %d expired M-Pesa POS lock(s)", len(expired))
