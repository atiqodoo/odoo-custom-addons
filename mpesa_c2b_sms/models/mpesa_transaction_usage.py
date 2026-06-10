from odoo import fields, models


class MpesaTransactionUsage(models.Model):
    _name = 'mpesa.transaction.usage'
    _description = 'M-Pesa Transaction POS Usage'
    _order = 'create_date desc, id desc'

    transaction_id = fields.Many2one(
        'mpesa.transaction', 'M-Pesa Transaction',
        required=True, index=True, ondelete='cascade',
    )
    mpesa_ref = fields.Char(related='transaction_id.mpesa_ref', store=True, index=True)
    pos_order_id = fields.Many2one(
        'pos.order', 'POS Order',
        required=True, index=True, ondelete='cascade',
    )
    pos_payment_id = fields.Many2one(
        'pos.payment', 'POS Payment',
        index=True, ondelete='set null',
    )
    amount = fields.Monetary('Amount Used', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', default=lambda s: s.env.ref('base.KES', raise_if_not_found=False),
    )
    cashier_id = fields.Many2one('res.users', 'Cashier', ondelete='set null')
    session_id = fields.Many2one('pos.session', 'POS Session', ondelete='set null')

    _sql_constraints = [
        (
            'mpesa_usage_payment_uniq',
            'UNIQUE(transaction_id, pos_payment_id)',
            'This POS payment is already linked to this M-Pesa transaction.',
        ),
    ]
