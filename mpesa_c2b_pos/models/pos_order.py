"""Stores and maps M-Pesa references used by POS orders."""
import logging

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

_log = logging.getLogger(__name__)


class MpesaTransaction(models.Model):
    _inherit = 'mpesa.transaction'

    pos_reserved_amount = fields.Monetary(
        'Confirmed POS Amount Awaiting Order Sync',
        currency_field='currency_id',
        default=0.0,
        readonly=True,
        help='M-Pesa amount confirmed in POS but not yet linked to a synced POS order.',
    )


class PosOrder(models.Model):
    _inherit = 'pos.order'

    mpesa_ref        = fields.Char('M-Pesa Reference', readonly=True)
    mpesa_transaction_id = fields.Many2one(
        'mpesa.transaction', 'M-Pesa Transaction', readonly=True, ondelete='set null',
    )
    mpesa_usage_ids = fields.One2many(
        'mpesa.transaction.usage', 'pos_order_id', 'M-Pesa Usage', readonly=True,
    )
    mpesa_transaction_ids = fields.Many2many(
        'mpesa.transaction', string='M-Pesa Transactions',
        compute='_compute_mpesa_transaction_ids', store=False,
    )

    def _compute_mpesa_transaction_ids(self):
        for order in self:
            txns = order.mpesa_usage_ids.mapped('transaction_id')
            if order.mpesa_transaction_id:
                txns |= order.mpesa_transaction_id
            order.mpesa_transaction_ids = txns

    def _process_order(self, order, existing_order):
        self._mpesa_validate_order_payload(order)
        order_id = super()._process_order(order, existing_order)
        self.browse(order_id)._link_mpesa_usages_from_payments()
        return order_id

    def _mpesa_validate_order_payload(self, order):
        """Reject duplicate or unconfirmed M-Pesa references before POS creates payments."""
        payload = order.get('data') if isinstance(order, dict) else {}
        if not payload:
            payload = order if isinstance(order, dict) else {}

        payment_commands = payload.get('payment_ids') or payload.get('statement_ids') or []
        mpesa_by_ref = {}
        PaymentMethod = self.env['pos.payment.method'].sudo()
        for command in payment_commands:
            values = command[2] if isinstance(command, (list, tuple)) and len(command) >= 3 else {}
            if not isinstance(values, dict):
                continue
            mpesa_ref = values.get('mpesa_ref')
            if not mpesa_ref:
                continue
            method_id = values.get('payment_method_id') or values.get('journal_id')
            method = PaymentMethod.browse(method_id) if method_id else PaymentMethod.browse()
            if method and not method.is_mpesa:
                continue
            amount = float(values.get('amount') or 0.0)
            mpesa_by_ref.setdefault(mpesa_ref, 0.0)
            mpesa_by_ref[mpesa_ref] += amount

        if not mpesa_by_ref:
            return

        Txn = self.env['mpesa.transaction'].sudo()
        for mpesa_ref, total_amount in mpesa_by_ref.items():
            if float_is_zero(total_amount, precision_digits=2):
                continue
            txn = Txn.search([('mpesa_ref', '=', mpesa_ref)], limit=1)
            if not txn:
                raise UserError(
                    "M-Pesa transaction %s was not found. Search and confirm the SMS again."
                    % mpesa_ref
                )
            if float_compare(
                total_amount,
                txn.pos_reserved_amount or 0.0,
                precision_rounding=txn.currency_id.rounding or 0.01,
            ) > 0:
                _log.warning(
                    "Rejected POS order with unreserved M-Pesa ref=%s amount=%.2f "
                    "reserved=%.2f state=%s",
                    mpesa_ref, total_amount, txn.pos_reserved_amount, txn.state,
                )
                raise UserError(
                    "M-Pesa transaction %s is not available for this payment. "
                    "Each SMS must be searched and confirmed once."
                    % mpesa_ref
                )

    def _link_mpesa_usages_from_payments(self):
        Usage = self.env['mpesa.transaction.usage'].sudo()
        Txn = self.env['mpesa.transaction'].sudo()
        for order in self.sudo():
            mpesa_payments = order.payment_ids.filtered(
                lambda p: p.amount > 0 and p.mpesa_ref and p.payment_method_id.is_mpesa
            )
            for payment in mpesa_payments:
                txn = Txn.search([('mpesa_ref', '=', payment.mpesa_ref)], limit=1)
                if not txn:
                    _log.warning(
                        "POS order %s has M-Pesa ref %s but no mpesa.transaction row",
                        order.name, payment.mpesa_ref,
                    )
                    continue

                if not Usage.search([
                    ('transaction_id', '=', txn.id),
                    ('pos_payment_id', '=', payment.id),
                ], limit=1):
                    Usage.create({
                        'transaction_id': txn.id,
                        'pos_order_id': order.id,
                        'pos_payment_id': payment.id,
                        'amount': payment.amount,
                        'currency_id': payment.currency_id.id or txn.currency_id.id,
                        'cashier_id': order.user_id.id,
                        'session_id': order.session_id.id,
                    })
                    reserved_after = max(
                        (txn.pos_reserved_amount or 0.0) - (payment.amount or 0.0),
                        0.0,
                    )
                    txn.write({'pos_reserved_amount': reserved_after})

                values = {'mpesa_transaction_id': txn.id}
                if not payment.mpesa_transaction_id:
                    payment.write(values)

                order_values = {}
                if not order.mpesa_ref:
                    order_values['mpesa_ref'] = txn.mpesa_ref
                if not order.mpesa_transaction_id:
                    order_values['mpesa_transaction_id'] = txn.id
                if order_values:
                    order.write(order_values)

                txn_values = {}
                if txn.state == 'pending_pos':
                    remaining_before = max((txn.amount or 0.0) - (txn.amount_used or 0.0), 0.0)
                    applied = min(payment.amount or remaining_before, remaining_before)
                    amount_used = (txn.amount_used or 0.0) + applied
                    remaining_after = max((txn.amount or 0.0) - amount_used, 0.0)
                    txn_values.update({
                        'state': 'partial_pos' if remaining_after > 0.01 else 'reconciled_pos',
                        'amount_used': amount_used,
                        'pos_session_id': False,
                        'pos_lock_expires': False,
                        'lock_token': False,
                        'pos_reserved_amount': 0.0,
                    })

                if not txn.pos_order_id:
                    txn_values['pos_order_id'] = order.id
                if txn.pos_reserved_amount <= 0.0:
                    txn_values.update({
                        'pos_session_id': False,
                        'pos_lock_expires': False,
                        'lock_token': False,
                    })
                if txn_values:
                    txn.write(txn_values)
