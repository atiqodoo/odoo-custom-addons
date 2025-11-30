# -*- coding: utf-8 -*-

from odoo import fields, models


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    taken_qty = fields.Float(
        string='Quantity Taken',
        help='Quantity taken by customer (defaults to full quantity)',
        copy=False,
    )
    
    deferred_qty = fields.Float(
        string='Quantity Deferred',
        compute='_compute_deferred_qty',
        store=True,
        help='Quantity left in store for later collection',
    )
    
    def _compute_deferred_qty(self):
        """Calculate deferred quantity"""
        for line in self:
            if line.taken_qty:
                line.deferred_qty = line.qty - line.taken_qty
            else:
                line.deferred_qty = 0.0
