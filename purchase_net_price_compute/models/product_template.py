from odoo import api, fields, models

class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    use_custom_vendor_pricing = fields.Boolean(
        string="Use Custom Vendor Pricing",
        default=False,
        help="Enable custom discount/freight calculations for this product. "
             "If disabled, standard Odoo vendor pricelist will be used."
    )
    
    vendor_pricing_ids = fields.One2many(
        'product.vendor.pricing', 
        'product_tmpl_id', 
        string='Vendor Pricing Rules'
    )
    
    # Quick stats
    vendor_pricing_count = fields.Integer(
        string='Pricing Rules',
        compute='_compute_vendor_pricing_count'
    )
    
    @api.depends('vendor_pricing_ids')
    def _compute_vendor_pricing_count(self):
        for product in self:
            product.vendor_pricing_count = len(product.vendor_pricing_ids)


class ProductProduct(models.Model):
    _inherit = 'product.product'
    
    use_custom_vendor_pricing = fields.Boolean(
        related='product_tmpl_id.use_custom_vendor_pricing',
        readonly=True
    )