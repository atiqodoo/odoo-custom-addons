import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare, float_is_zero

_log = logging.getLogger(__name__)


class MpesaTransactionRefundCase(models.Model):
    _name = 'mpesa.transaction.refund.case'
    _description = 'M-Pesa Refund / Safaricom Dispute Case'
    _order = 'create_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(default='New', copy=False, readonly=True)
    transaction_id = fields.Many2one(
        'mpesa.transaction', 'Original M-Pesa Transaction',
        required=True, index=True, ondelete='cascade',
    )
    mpesa_ref = fields.Char(related='transaction_id.mpesa_ref', store=True, index=True)
    case_type = fields.Selection(
        [
            ('internal_refund', 'Internal Refund'),
            ('safaricom_reversal', 'Safaricom Reversal Complaint'),
        ],
        required=True, default='internal_refund', index=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('requested', 'Refund Requested'),
            ('approved', 'Refund Approved'),
            ('paid', 'Refund Paid'),
            ('under_review', 'Safaricom Review'),
            ('accepted', 'Reversal Accepted'),
            ('objected', 'Reversal Objected'),
            ('reversed', 'Reversed by Safaricom'),
            ('won', 'Dispute Won'),
            ('lost', 'Dispute Lost'),
            ('rejected', 'Rejected'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft', required=True, index=True,
    )
    amount = fields.Monetary(required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.ref('base.KES', raise_if_not_found=False),
        required=True,
    )
    partner_id = fields.Many2one('res.partner', 'Customer', ondelete='set null')
    reason = fields.Text(required=True)
    evidence = fields.Text('Evidence / Notes')

    safaricom_case_ref = fields.Char('Safaricom Case Reference', copy=False)
    safaricom_verdict = fields.Text('Safaricom Verdict')
    refund_payment_ref = fields.Char(
        'Refund/Reversal Reference',
        copy=False,
        help='M-Pesa send-money reference, Safaricom reversal reference, or settlement deduction reference.',
    )

    refund_journal_id = fields.Many2one(
        'account.journal', 'Refund/Reversal Journal',
        domain="[('type', 'in', ('bank', 'cash'))]",
        help='Journal that actually paid or absorbed the refund/reversal. This can differ from the Till receipt journal.',
    )
    counterpart_account_id = fields.Many2one(
        'account.account', 'Customer Deposit / Suspense Account',
        help='Liability/clearing account credited when the unused money was received.',
    )
    loss_account_id = fields.Many2one(
        'account.account', 'Dispute Loss Account',
        help='Used only when Safaricom reverses money after the business already consumed the payment.',
    )
    move_id = fields.Many2one('account.move', 'Accounting Entry', readonly=True, copy=False)

    requested_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    requested_at = fields.Datetime(readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    paid_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    paid_at = fields.Datetime(readonly=True, copy=False)

    _sql_constraints = [
        (
            'refund_payment_ref_uniq',
            'UNIQUE(refund_payment_ref)',
            'This refund/reversal reference is already used on another case.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = seq.next_by_code('mpesa.refund.case') or 'New'
        return super().create(vals_list)

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Amount must be greater than zero.'))
            rec._check_amount_available()

    def _check_amount_available(self):
        for rec in self:
            txn = rec.transaction_id
            precision = rec.currency_id.rounding or 0.01
            if rec.case_type == 'safaricom_reversal':
                own_reversed = rec.amount if rec.state == 'reversed' else 0.0
                own_frozen = rec.amount if rec.state in ('under_review', 'accepted', 'objected') else 0.0
                available = (
                    (txn.amount or 0.0)
                    - (txn.amount_reversed or 0.0)
                    - (txn.amount_frozen or 0.0)
                    + own_reversed
                    + own_frozen
                )
            else:
                own_paid = rec.amount if rec.state == 'paid' else 0.0
                available = (txn.amount_remaining or 0.0) + own_paid
            if float_compare(rec.amount, available, precision_rounding=precision) > 0:
                raise ValidationError(_(
                    'Case amount %(amount).2f is higher than available transaction balance %(available).2f.',
                    amount=rec.amount,
                    available=available,
                ))

    def action_submit(self):
        for rec in self:
            rec._check_amount_available()
            values = {
                'requested_by_id': self.env.user.id,
                'requested_at': fields.Datetime.now(),
            }
            if rec.case_type == 'internal_refund':
                values['state'] = 'requested'
                txn_state = 'refund_requested'
            else:
                values['state'] = 'under_review'
                txn_state = 'safaricom_dispute'
            rec.write(values)
            rec.transaction_id.write({'state': txn_state})
            _log.info("M-Pesa case %s submitted by %s", rec.name, self.env.user.login)

    def action_open_transaction(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'M-Pesa Transaction',
            'res_model': 'mpesa.transaction',
            'res_id': self.transaction_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_approve(self):
        for rec in self:
            if rec.case_type != 'internal_refund':
                raise ValidationError(_('Only internal refunds use approval. Safaricom cases must be accepted or objected.'))
            if rec.state != 'requested':
                raise ValidationError(_('Only requested refunds can be approved.'))
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_at': fields.Datetime.now(),
            })
            rec.transaction_id.write({'state': 'refund_approved'})

    def action_mark_refund_paid(self):
        for rec in self:
            if rec.case_type != 'internal_refund' or rec.state != 'approved':
                raise ValidationError(_('Only approved internal refunds can be marked paid.'))
            rec._create_refund_move(debit_account=rec.counterpart_account_id)
            rec.write({
                'state': 'paid',
                'paid_by_id': self.env.user.id,
                'paid_at': fields.Datetime.now(),
            })
            rec.transaction_id.write({'state': rec.transaction_id._available_state()})

    def action_accept_reversal(self):
        for rec in self:
            if rec.case_type != 'safaricom_reversal' or rec.state != 'under_review':
                raise ValidationError(_('Only Safaricom cases under review can be accepted.'))
            rec.write({
                'state': 'accepted',
                'approved_by_id': self.env.user.id,
                'approved_at': fields.Datetime.now(),
            })
            rec.transaction_id.write({'state': 'reversal_accepted'})

    def action_object_reversal(self):
        for rec in self:
            if rec.case_type != 'safaricom_reversal' or rec.state != 'under_review':
                raise ValidationError(_('Only Safaricom cases under review can be objected.'))
            rec.write({
                'state': 'objected',
                'approved_by_id': self.env.user.id,
                'approved_at': fields.Datetime.now(),
            })
            rec.transaction_id.write({'state': 'reversal_objected'})

    def action_mark_reversed(self):
        for rec in self:
            if rec.case_type != 'safaricom_reversal' or rec.state not in ('accepted', 'objected'):
                raise ValidationError(_('Only accepted/objected Safaricom cases can be marked reversed.'))
            account = rec.loss_account_id if rec.state == 'objected' and rec.transaction_id.amount_used else rec.counterpart_account_id
            rec._create_refund_move(debit_account=account)
            rec.write({
                'state': 'reversed',
                'paid_by_id': self.env.user.id,
                'paid_at': fields.Datetime.now(),
            })
            rec.transaction_id.write({'state': rec.transaction_id._available_state()})

    def action_mark_won(self):
        for rec in self:
            if rec.case_type != 'safaricom_reversal' or rec.state != 'objected':
                raise ValidationError(_('Only objected Safaricom cases can be marked won.'))
            rec.write({'state': 'won', 'safaricom_verdict': rec.safaricom_verdict or 'Dispute won.'})
            rec.transaction_id.write({'state': 'dispute_won'})

    def action_mark_lost(self):
        for rec in self:
            if rec.case_type != 'safaricom_reversal' or rec.state != 'objected':
                raise ValidationError(_('Only objected Safaricom cases can be marked lost.'))
            account = rec.loss_account_id if rec.transaction_id.amount_used else rec.counterpart_account_id
            rec._create_refund_move(debit_account=account)
            rec.write({
                'state': 'lost',
                'safaricom_verdict': rec.safaricom_verdict or 'Dispute lost.',
                'paid_by_id': self.env.user.id,
                'paid_at': fields.Datetime.now(),
            })
            rec.transaction_id.write({
                'state': 'dispute_lost' if not rec.transaction_id.amount_remaining else rec.transaction_id._available_state()
            })

    def action_reject(self):
        for rec in self:
            if rec.state not in ('draft', 'requested', 'under_review'):
                raise ValidationError(_('Only draft/requested/review cases can be rejected.'))
            rec.write({'state': 'rejected'})
            rec._restore_transaction_state()

    def action_cancel(self):
        for rec in self:
            if rec.move_id:
                raise ValidationError(_('You cannot cancel a case that already has an accounting entry.'))
            rec.write({'state': 'cancelled'})
            rec._restore_transaction_state()

    def _restore_transaction_state(self):
        for rec in self:
            txn = rec.transaction_id
            txn.write({'state': txn._available_state()})

    def _create_refund_move(self, debit_account):
        self.ensure_one()
        if self.move_id:
            return self.move_id
        if not self.refund_journal_id:
            raise ValidationError(_('Select the journal that paid or absorbed this refund/reversal.'))
        if not debit_account:
            raise ValidationError(_('Select the customer deposit/suspense account or dispute loss account.'))
        credit_account = self.refund_journal_id.default_account_id
        if not credit_account:
            raise ValidationError(_('The selected journal has no default liquidity account.'))
        if not self.refund_payment_ref:
            raise ValidationError(_('Enter the refund/reversal payment reference before posting accounting.'))
        if float_is_zero(self.amount, precision_rounding=self.currency_id.rounding or 0.01):
            raise ValidationError(_('Cannot create accounting for a zero amount.'))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.refund_journal_id.id,
            'date': fields.Date.context_today(self),
            'ref': '%s - %s' % (self.name, self.refund_payment_ref),
            'line_ids': [
                (0, 0, {
                    'name': '%s %s' % (self.name, self.mpesa_ref),
                    'partner_id': self.partner_id.id,
                    'account_id': debit_account.id,
                    'debit': self.amount,
                    'credit': 0.0,
                    'currency_id': self.currency_id.id,
                }),
                (0, 0, {
                    'name': '%s %s' % (self.name, self.refund_payment_ref),
                    'partner_id': self.partner_id.id,
                    'account_id': credit_account.id,
                    'debit': 0.0,
                    'credit': self.amount,
                    'currency_id': self.currency_id.id,
                }),
            ],
        })
        move.action_post()
        self.move_id = move.id
        return move
