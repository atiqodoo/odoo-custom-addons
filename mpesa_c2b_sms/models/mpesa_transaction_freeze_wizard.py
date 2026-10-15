import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare

_log = logging.getLogger(__name__)


class MpesaTransactionFreezeWizard(models.TransientModel):
    _name = 'mpesa.transaction.freeze.wizard'
    _description = 'Authorize M-Pesa Transaction Freeze'

    transaction_id = fields.Many2one('mpesa.transaction', required=True, readonly=True)
    operation = fields.Selection(
        [('freeze', 'Freeze'), ('unfreeze', 'Unfreeze')],
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='transaction_id.currency_id',
        readonly=True,
    )
    max_amount = fields.Monetary(
        'Maximum Amount',
        currency_field='currency_id',
        compute='_compute_max_amount',
    )
    amount = fields.Monetary(
        'Amount',
        currency_field='currency_id',
        required=True,
    )
    pin = fields.Char('Employee PIN', required=True)
    reason = fields.Text()

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        transaction = self.env['mpesa.transaction'].sudo().browse(
            values.get('transaction_id') or self.env.context.get('default_transaction_id') or 0
        ).exists()
        operation = values.get('operation') or self.env.context.get('default_operation')
        if transaction and 'amount' in fields_list:
            values['amount'] = (
                transaction.amount_remaining
                if operation == 'freeze'
                else transaction.amount_manually_frozen
            )
        return values

    @api.depends('transaction_id', 'operation')
    def _compute_max_amount(self):
        for rec in self:
            if rec.operation == 'freeze':
                rec.max_amount = rec.transaction_id.amount_remaining
            elif rec.operation == 'unfreeze':
                rec.max_amount = rec.transaction_id.amount_manually_frozen
            else:
                rec.max_amount = 0.0

    def action_confirm(self):
        self.ensure_one()
        txn = self.transaction_id.sudo().exists()
        if not txn:
            raise UserError(_('M-Pesa transaction was not found.'))
        precision = txn.currency_id.rounding or 0.01
        max_amount = (
            txn.amount_remaining
            if self.operation == 'freeze'
            else txn.amount_manually_frozen
        )
        if float_compare(self.amount or 0.0, 0.0, precision_rounding=precision) <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        if float_compare(self.amount or 0.0, max_amount or 0.0, precision_rounding=precision) > 0:
            raise UserError(_(
                'Amount %(amount).2f is higher than the allowed maximum %(maximum).2f.'
            ) % {
                'amount': self.amount,
                'maximum': max_amount,
            })

        _log.debug(
            "M-Pesa %s wizard submitted: txn_id=%s ref=%s amount=%.2f max_amount=%.2f user=%s",
            self.operation,
            txn.id,
            txn.mpesa_ref,
            self.amount,
            max_amount,
            self.env.uid,
        )
        authorization = txn._mpesa_authorize_freeze_pin(self.pin, self.operation)
        if not authorization.get('approved'):
            _log.warning(
                "M-Pesa %s denied: txn_id=%s ref=%s user=%s message=%s",
                self.operation,
                txn.id,
                txn.mpesa_ref,
                self.env.uid,
                authorization.get('message'),
            )
            raise UserError(authorization.get('message') or _('Employee PIN is not authorized.'))

        employee = self.env['hr.employee'].sudo().browse(
            authorization.get('employee_id') or 0
        ).exists()
        if self.operation == 'freeze':
            freeze = txn._mpesa_freeze_remaining(
                employee=employee,
                reason=self.reason,
                amount=self.amount,
            )
            message = _('Frozen %(amount).2f from M-Pesa transaction %(ref)s.') % {
                'amount': freeze.amount,
                'ref': txn.mpesa_ref,
            }
        else:
            txn._mpesa_unfreeze_active(employee=employee, amount=self.amount)
            message = _('Released %(amount).2f manual freeze on M-Pesa transaction %(ref)s.') % {
                'amount': self.amount,
                'ref': txn.mpesa_ref,
            }

        txn._mpesa_log_freeze_authorization(
            self.operation,
            True,
            employee=employee,
            message=message,
        )
        _log.info(
            "M-Pesa %s completed: txn_id=%s ref=%s employee=%s user=%s message=%s",
            self.operation,
            txn.id,
            txn.mpesa_ref,
            employee.id if employee else False,
            self.env.uid,
            message,
        )
        return {'type': 'ir.actions.act_window_close'}
