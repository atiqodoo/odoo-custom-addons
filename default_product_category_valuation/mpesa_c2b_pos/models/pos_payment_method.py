"""
Extends pos.payment.method to add an M-Pesa type.
When is_mpesa=True the POS frontend opens MpesaPaymentScreen
instead of the standard cash input.
"""
from odoo import fields, models


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    is_mpesa = fields.Boolean(
        'M-Pesa C2B',
        help='Enable to use M-Pesa BuyGoods C2B validation for this payment method.',
    )
    mpesa_lock_minutes = fields.Integer(
        'Lock Timeout (minutes)', default=5,
        help='How long a transaction is reserved for a POS session before auto-release.',
    )
    mpesa_amount_tolerance = fields.Float(
        'Amount Tolerance (Ksh)', default=1.0,
        help='Accepted rounding difference between M-Pesa amount and order total.',
    )
    mpesa_allow_overpayment = fields.Boolean(
        'Allow Overpayment', default=True,
        help='Accept M-Pesa payments larger than the order total (give change).',
    )
    mpesa_allow_partial = fields.Boolean(
        'Allow Partial Payment', default=True,
        help='Allow M-Pesa to cover part of the order (split with cash/card).',
    )

    def _load_pos_data_fields(self, config_id):
        fields = super()._load_pos_data_fields(config_id)
        return fields + [
            'is_mpesa',
            'mpesa_lock_minutes',
            'mpesa_amount_tolerance',
            'mpesa_allow_overpayment',
            'mpesa_allow_partial',
        ]
