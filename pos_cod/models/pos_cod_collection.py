# -*- coding: utf-8 -*-
from odoo import fields, models


class PosCodCollection(models.Model):
    _name = 'pos.cod.collection'
    _description = 'POS COD Collection / Return'
    _order = 'create_date desc, id desc'

    order_id = fields.Many2one('pos.order', required=True, index=True, ondelete='cascade')
    session_id = fields.Many2one('pos.session', required=True, index=True, ondelete='restrict')
    payment_method_id = fields.Many2one('pos.payment.method', index=True, ondelete='restrict')
    move_id = fields.Many2one('account.move', readonly=True, ondelete='set null')
    kind = fields.Selection(
        [('payment', 'Payment'), ('return', 'Return')],
        required=True,
        default='payment',
        index=True,
    )
    amount = fields.Monetary(required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='order_id.currency_id', store=True)
    return_line_qtys = fields.Json(copy=False)
    note = fields.Char()
