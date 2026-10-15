import logging

from odoo import models


_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def _vendor_payment_audit_candidate_bills(self):
        bills = self.env['account.move']
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids') or []
        if active_model == 'account.move' and active_ids:
            bills |= self.env['account.move'].browse(active_ids)
        for payment in self:
            if 'reconciled_bill_ids' in payment._fields:
                bills |= payment.reconciled_bill_ids
            if payment.payment_type == 'outbound' and payment.partner_type == 'supplier':
                bills |= payment.move_id.line_ids.matched_debit_ids.debit_move_id.move_id.filtered(
                    lambda move: move.move_type == 'in_invoice'
                )
                bills |= payment.move_id.line_ids.matched_credit_ids.credit_move_id.move_id.filtered(
                    lambda move: move.move_type == 'in_invoice'
                )
        return bills

    def action_post(self):
        self._vendor_payment_audit_candidate_bills()._vendor_payment_audit_check_allowed(operation='payment_post')
        _logger.debug('[VPA_PAYMENT_GUARD] payment_post_allowed payment_ids=%s user_id=%s', self.ids, self.env.user.id)
        return super().action_post()

    def action_validate(self):
        self._vendor_payment_audit_candidate_bills()._vendor_payment_audit_check_allowed(operation='payment_validate')
        return super().action_validate()
