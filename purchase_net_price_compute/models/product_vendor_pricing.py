from odoo import api, fields, models

class ProductVendorPricing(models.Model):
    _name = 'product.vendor.pricing'
    _description = 'Product Vendor Pricing Rules'
    _order = 'partner_id, product_tmpl_id, min_qty'

    partner_id = fields.Many2one(
        'res.partner', 
        string='Vendor', 
        required=True, 
        domain=[('supplier_rank', '>', 0)],
        ondelete='cascade'
    )
    product_id = fields.Many2one(
        'product.product', 
        string='Product Variant',
        ondelete='cascade'
    )
    product_tmpl_id = fields.Many2one(
        'product.template', 
        string='Product', 
        required=True,
        ondelete='cascade'
    )
    
    # Slab-based pricing
    min_qty = fields.Float(
        string='Min Quantity', 
        default=1.0, 
        required=True
    )
    max_qty = fields.Float(
        string='Max Quantity', 
        default=0.0, 
        help="0 means no maximum limit"
    )
    
    # Product-specific overrides
    discount_percentage = fields.Float(
        string='Discount %',
        help="Discount percentage for this product from this vendor"
    )
    freight_percentage = fields.Float(
        string='Freight %',
        help="Freight percentage for this product from this vendor"
    )
    price_unit = fields.Float(
        string='Unit Price',
        help="Optional: Specific price for this quantity range"
    )
    
    active = fields.Boolean(default=True)
    
    _sql_constraints = [
        ('check_qty_range', 
         'CHECK(min_qty >= 0 AND max_qty >= 0)', 
         'Quantities must be positive!'),
        ('unique_vendor_product_qty', 
         'UNIQUE(partner_id, product_tmpl_id, product_id, min_qty)', 
         'Only one pricing rule per vendor/product/quantity combination!'),
    ]
    
    @api.constrains('min_qty', 'max_qty')
    def _check_qty_range(self):
        for record in self:
            if record.max_qty > 0 and record.min_qty > record.max_qty:
                raise models.ValidationError(
                    'Minimum quantity cannot be greater than maximum quantity!'
                )
    
    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        """Clear product variant when template changes"""
        if self.product_tmpl_id:
            self.product_id = False