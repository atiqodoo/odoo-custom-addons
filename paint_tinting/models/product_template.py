# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ProductTemplate(models.Model):
    """Extension of product.template to add tinting-specific fields"""
    _inherit = 'product.template'

    # Link to colour master module
    fandeck_id = fields.Many2one(
        'colour.fandeck',
        string='Fandeck',
        help='Colour fandeck reference from paint_colour_master module'
    )
    
    colour_code_id = fields.Many2one(
        'colour.code',
        string='Colour Code',
        help='Colour code from paint_colour_master module'
    )
    
    colour_name = fields.Char(
        string='Colour Name',
        related='colour_code_id.name',
        store=True,
        readonly=True,
        help='Colour name from selected colour code'
    )
    
    # Tinting flags
    is_tinted_product = fields.Boolean(
        string='Is Tinted Product',
        default=False,
        help='Indicates if this product was created through the tinting wizard'
    )
    
    is_colorant = fields.Boolean(
        string='Is Colorant',
        default=False,
        help='Indicates if this product is a colorant for tinting'
    )
    
    colorant_code = fields.Char(
        string='Colorant Code',
        help='Short code for colorant (e.g., C1, C2, etc.)'
    )
    
    # Removed is_base_paint - any product can be base paint now
    
    # Paint type categorization
    paint_type = fields.Selection([
        ('supergloss', 'Supergloss'),
        ('vinylsilk', 'Vinylsilk'),
        ('emulsion', 'Emulsion'),
        ('undercoat', 'Undercoat'),
        ('other', 'Other'),
    ], string='Paint Type', help='Type of paint product')
    
    # Costing fields (VAT-inclusive tracking)
    cost_price_excl_vat = fields.Float(
        string='Cost (Excl. VAT)',
        digits='Product Price',
        help='Cost price excluding VAT'
    )
    
    cost_price_incl_vat = fields.Float(
        string='Cost (Incl. VAT)',
        compute='_compute_cost_incl_vat',
        store=True,
        digits='Product Price',
        help='Cost price including 16% VAT'
    )
    
    @api.depends('cost_price_excl_vat')
    def _compute_cost_incl_vat(self):
        """Compute VAT-inclusive cost (16% VAT rate for Kenya)"""
        for product in self:
            product.cost_price_incl_vat = product.cost_price_excl_vat * 1.16
    
    @api.onchange('colour_code_id')
    def _onchange_colour_code(self):
        """Auto-fill colour name when colour code changes"""
        if self.colour_code_id:
            self.colour_name = self.colour_code_id.name