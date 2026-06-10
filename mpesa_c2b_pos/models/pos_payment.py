from odoo import fields, models


class PosPayment(models.Model):
    _inherit = 'pos.payment'

    mpesa_ref = fields.Char('M-Pesa Reference', readonly=True, index=True)
    mpesa_transaction_id = fields.Many2one(
        'mpesa.transaction', 'M-Pesa Transaction', readonly=True, ondelete='set null',
    )
