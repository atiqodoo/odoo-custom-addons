# -*- coding: utf-8 -*-
from odoo import api, models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.constrains('quantity')
    def constrain_product_quantity(self):
        # Allow negative quants when dispatching a COD order (Option C).
        # The cod_dispatch context is set exclusively in pos_cod picking logic
        # so this bypass never fires for normal sales or adjustments.
        if self.env.context.get('cod_dispatch'):
            return
        return super().constrain_product_quantity()
