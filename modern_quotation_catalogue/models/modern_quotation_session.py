# -*- coding: utf-8 -*-
from odoo import fields, models


class ModernQuotationSession(models.TransientModel):
    _name = 'modern.quotation.session'
    _description = 'Modern Quotation Workspace Session'

    name = fields.Char(default='Modern Quotation Workspace')
    sale_order_id = fields.Many2one('sale.order', string='Quotation')
    partner_id = fields.Many2one('res.partner', string='Customer')
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist')
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
