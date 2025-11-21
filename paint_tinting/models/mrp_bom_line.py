# -*- coding: utf-8 -*-

from odoo import models, fields, api


class MrpBomLine(models.Model):
    """Extension of mrp.bom.line to add VAT-inclusive costing"""
    _inherit = 'mrp.bom.line'

    # Colorant-specific fields
    is_colorant_line = fields.Boolean(
        string='Is Colorant',
        default=False,
        help='Indicates if this line is a colorant component'
    )
    
    colorant_shots = fields.Float(
        string='Shots',
        digits=(10, 2),
        help='Number of shots from LargoTint machine (1 shot = 0.616 ml)'
    )
    
    colorant_ml = fields.Float(
        string='Volume (ml)',
        compute='_compute_colorant_ml',
        store=True,
        digits=(10, 3),
        help='Volume in milliliters (shots × 0.616)'
    )
    
    # Cost tracking (both VAT-exclusive and VAT-inclusive)
    unit_cost_excl_vat = fields.Float(
        string='Unit Cost (Excl. VAT)',
        digits='Product Price',
        help='Unit cost of component excluding VAT'
    )
    
    unit_cost_incl_vat = fields.Float(
        string='Unit Cost (Incl. VAT)',
        compute='_compute_unit_cost_incl_vat',
        store=True,
        digits='Product Price',
        help='Unit cost of component including 16% VAT'
    )
    
    cost_excl_vat = fields.Float(
        string='Line Cost (Excl. VAT)',
        compute='_compute_line_costs',
        store=True,
        digits='Product Price',
        help='Total line cost excluding VAT (unit cost × quantity)'
    )
    
    cost_incl_vat = fields.Float(
        string='Line Cost (Incl. VAT)',
        compute='_compute_line_costs',
        store=True,
        digits='Product Price',
        help='Total line cost including VAT'
    )
    
    # Stock availability warning
    available_stock = fields.Float(
        string='Available Stock',
        compute='_compute_available_stock',
        digits='Product Unit of Measure',
        help='Current available stock for this component'
    )
    
    stock_warning = fields.Boolean(
        string='Stock Warning',
        compute='_compute_stock_warning',
        help='True if requested quantity exceeds available stock'
    )
    
    @api.depends('colorant_shots')
    def _compute_colorant_ml(self):
        """Convert shots to milliliters (1 shot = 0.616 ml)"""
        for line in self:
            if line.is_colorant_line and line.colorant_shots:
                line.colorant_ml = line.colorant_shots * 0.616
            else:
                line.colorant_ml = 0.0
    
    @api.depends('unit_cost_excl_vat')
    def _compute_unit_cost_incl_vat(self):
        """Compute VAT-inclusive unit cost (16% VAT)"""
        for line in self:
            line.unit_cost_incl_vat = line.unit_cost_excl_vat * 1.16
    
    @api.depends('unit_cost_excl_vat', 'unit_cost_incl_vat', 'product_qty')
    def _compute_line_costs(self):
        """Calculate total line costs"""
        for line in self:
            line.cost_excl_vat = line.unit_cost_excl_vat * line.product_qty
            line.cost_incl_vat = line.unit_cost_incl_vat * line.product_qty
    
    def _compute_available_stock(self):
        """Get available stock for the component"""
        for line in self:
            if line.product_id:
                # Get available quantity in the product's UoM
                available = line.product_id.with_context(
                    warehouse=self.env.user.company_id.warehouse_id.id
                ).qty_available
                
                # Convert to BOM line UoM if different
                if line.product_uom_id != line.product_id.uom_id:
                    available = line.product_id.uom_id._compute_quantity(
                        available,
                        line.product_uom_id
                    )
                
                line.available_stock = available
            else:
                line.available_stock = 0.0
    
    @api.depends('product_qty', 'available_stock')
    def _compute_stock_warning(self):
        """Check if stock is insufficient"""
        for line in self:
            line.stock_warning = line.product_qty > line.available_stock
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Auto-fill unit cost when product changes"""
        res = super()._onchange_product_id()
        if self.product_id:
            # Get standard price from product
            self.unit_cost_excl_vat = self.product_id.standard_price
        return res
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to ensure unit costs are set"""
        for vals in vals_list:
            if 'product_id' in vals:
                product = self.env['product.product'].browse(vals['product_id'])
                vals['unit_cost_excl_vat'] = product.standard_price
        return super().create(vals_list)