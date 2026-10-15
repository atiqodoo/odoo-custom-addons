import logging

from odoo import models


_logger = logging.getLogger(__name__)


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _create_payments(self):
        moves = self.line_ids.move_id
        moves._vendor_payment_audit_check_allowed(operation='payment_register_create')
        _logger.debug(
            '[VPA_PAYMENT_GUARD] register_allowed wizard_ids=%s move_ids=%s user_id=%s',
            self.ids,
            moves.ids,
            self.env.user.id,
        )
        return super()._create_payments()
