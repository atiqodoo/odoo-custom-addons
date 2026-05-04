# -*- coding: utf-8 -*-
from odoo import models, fields

class SaleOrderLine(models.Model):
    """Extension to store tinting formula and cost snapshots"""
    _inherit = 'sale.order.line'
    
    # ============================================
    # TINTING FIELDS
    # ============================================
    is_tinted_product_line = fields.Boolean(
        string='Is Tinted Product Line',
        default=False
    )
    
    tinting_formula_json = fields.Text(
        string='Tinting Formula (JSON)',
        help='Colorant shots stored as JSON'
    )
    
    # ============================================
    # COST SNAPSHOTS
    # ============================================
    quoted_cost_at_creation = fields.Float(
        string='Quoted Cost (Snapshot)',
        digits='Product Price',
        readonly=True,
        copy=False
    )
    
    quoted_base_cost = fields.Float(
        string='Quoted Base Cost',
        digits='Product Price',
        readonly=True,
        copy=False
    )
    
    quoted_colorant_cost = fields.Float(
        string='Quoted Colorant Cost',
        digits='Product Price',
        readonly=True,
        copy=False
    )
    
    # ============================================
    # METADATA
    # ============================================
    colour_code_id = fields.Many2one('colour.code', string='Colour Code')
    fandeck_id = fields.Many2one('colour.fandeck', string='Fandeck')
    base_category_id = fields.Many2one('product.category', string='Base Category')