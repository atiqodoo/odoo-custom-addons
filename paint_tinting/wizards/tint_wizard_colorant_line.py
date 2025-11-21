# -*- coding: utf-8 -*-

from odoo import models, fields, api


class TintWizardColorantLine(models.TransientModel):
    """Colorant line in tinting wizard - handles shot-to-ml-to-litre conversion"""
    _name = 'tint.wizard.colorant.line'
    _description = 'Tinting Wizard Colorant Line'
    _order = 'colorant_code'

    # Parent wizard
    wizard_id = fields.Many2one(
        'tint.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade'
    )
    
    # Colorant product
    colorant_id = fields.Many2one(
        'product.product',
        string='Colorant',
        required=False,
        domain="[('is_colorant', '=', True)]",
        help='Colorant product'
    )
    
    colorant_name = fields.Char(
        string='Colorant Name',
        compute='_compute_colorant_name',
        store=True,
        readonly=True
    )
    
    colorant_code = fields.Char(
        string='Code',
        related='colorant_id.colorant_code',
        readonly=True,
        store=True
    )
    
    # User input: shots from LargoTint machine
    shots = fields.Float(
        string='Shots',
        digits=(10, 2),
        default=0.0,
        help='Number of shots from LargoTint machine (1 shot = 0.616 ml)'
    )
    
    # Auto-computed: ml volume
    ml_volume = fields.Float(
        string='ml',
        compute='_compute_ml_volume',
        store=True,
        digits=(10, 3),
        help='Volume in milliliters (shots × 0.616)'
    )
    
    # Auto-computed: litres for BOM
    qty_litres = fields.Float(
        string='Quantity (L)',
        compute='_compute_qty_litres',
        store=True,
        digits=(10, 6),
        help='Quantity in litres for BOM (ml ÷ 1000)'
    )
    
    # Stock information
    available_stock = fields.Float(
        string='Available Stock (L)',
        compute='_compute_available_stock',
        digits=(10, 4),
        help='Current available stock in litres'
    )
    
    stock_warning = fields.Boolean(
        string='Stock Warning',
        compute='_compute_stock_warning',
        help='True if requested quantity exceeds available stock'
    )
    
    # Cost information
    unit_cost_excl_vat = fields.Float(
        string='Unit Cost (Excl. VAT)',
        related='colorant_id.standard_price',
        readonly=True,
        digits='Product Price',
        help='Cost per litre excluding VAT'
    )
    
    unit_cost_incl_vat = fields.Float(
        string='Unit Cost (Incl. VAT)',
        compute='_compute_unit_cost_incl_vat',
        digits='Product Price',
        help='Cost per litre including 16% VAT'
    )
    
    line_cost_excl_vat = fields.Float(
        string='Line Cost (Excl. VAT)',
        compute='_compute_line_costs',
        digits='Product Price',
        help='Total line cost excluding VAT'
    )
    
    line_cost_incl_vat = fields.Float(
        string='Line Cost (Incl. VAT)',
        compute='_compute_line_costs',
        digits='Product Price',
        help='Total line cost including VAT'
    )
    
    @api.depends('shots')
    def _compute_ml_volume(self):
        """Convert shots to milliliters (1 shot = 0.616 ml)"""
        for line in self:
            line.ml_volume = line.shots * 0.616
    
    @api.depends('ml_volume')
    def _compute_qty_litres(self):
        """Convert milliliters to litres (ml ÷ 1000)"""
        for line in self:
            line.qty_litres = line.ml_volume / 1000.0
    
    def _compute_available_stock(self):
        """Get available stock for colorant in litres"""
        for line in self:
            if line.colorant_id:
                line.available_stock = line.colorant_id.qty_available
            else:
                line.available_stock = 0.0
    
    @api.depends('qty_litres', 'available_stock')
    def _compute_stock_warning(self):
        """Check if stock is insufficient (only for lines with shots > 0)"""
        for line in self:
            if line.shots > 0:
                line.stock_warning = line.qty_litres > line.available_stock
            else:
                line.stock_warning = False
    
    @api.depends('unit_cost_excl_vat')
    def _compute_unit_cost_incl_vat(self):
        """Calculate VAT-inclusive unit cost (16% VAT)"""
        for line in self:
            line.unit_cost_incl_vat = line.unit_cost_excl_vat * 1.16
    
    @api.depends('unit_cost_excl_vat', 'unit_cost_incl_vat', 'qty_litres')
    def _compute_line_costs(self):
        """Calculate total line costs"""
        for line in self:
            line.line_cost_excl_vat = line.unit_cost_excl_vat * line.qty_litres
            line.line_cost_incl_vat = line.unit_cost_incl_vat * line.qty_litres

    @api.depends('colorant_id.name')
    def _compute_colorant_name(self):
        """Compute colorant name without related+store=True to avoid translation bug"""
        for line in self:
            line.colorant_name = line.colorant_id.name if line.colorant_id else ''