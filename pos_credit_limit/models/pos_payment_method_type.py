# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosPaymentMethodType(models.Model):
    # Responsibility: marks which POS payment method is the "Customer Account"
    # (credit) method, and exposes that flag to the POS frontend store.
    #
    # Design choice — why a boolean on pos.payment.method rather than
    # inspecting the journal type or using payment_method_type?
    #   pos.payment.method is a POS configuration model, not an accounting
    #   transactional model. Adding a boolean here avoids touching account.move,
    #   account.journal, or any accounting record. The admin simply checks
    #   "Is Credit Payment Method" on the relevant payment method in POS settings.
    #
    # ACCOUNTING SAFETY:
    #   pos.payment.method is NOT an accounting model. No journal entries,
    #   account.move records, or account.move.line records are touched here.
    _inherit = 'pos.payment.method'

    pcl_is_credit_method = fields.Boolean(
        string='Is Credit Payment Method',
        default=False,
        help=(
            'Check this box to mark this payment method as the Customer Account '
            '(credit / pay-later) method. When checked, the POS credit gates '
            '(payment terms check and credit limit check) will activate whenever '
            'a cashier selects this payment method.'
        ),
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Expose pcl_is_credit_method to the POS browser store.

        Without this override the JS layer cannot read the flag.
        The field value is loaded once at session start alongside
        other payment method configuration fields.

        Args:
            config_id (int): The pos.config primary key.

        Returns:
            list[str]: Extended list of payment method fields for POS.
        """
        fields = super()._load_pos_data_fields(config_id)
        fields += ['pcl_is_credit_method']
        return fields
