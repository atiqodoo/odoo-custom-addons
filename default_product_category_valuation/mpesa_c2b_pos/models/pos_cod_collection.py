from odoo import fields, models


class PosCodCollection(models.Model):
    _inherit = 'pos.cod.collection'

    mpesa_transaction_id = fields.Many2one(
        'mpesa.transaction', 'M-Pesa Transaction', readonly=True, ondelete='set null', copy=False,
    )
