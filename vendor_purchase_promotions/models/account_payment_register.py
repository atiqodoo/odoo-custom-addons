import logging

from odoo import models


_logger = logging.getLogger(__name__)


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _create_payments(self):
        moves = self.line_ids.move_id
        moves._check_promotion_payment_allowed()
        _logger.debug(
            '[VPP_PAYMENT] register_allowed wizard_ids=%s move_ids=%s user_id=%s',
            self.ids,
            moves.ids,
            self.env.user.id,
        )
        return super()._create_payments()

