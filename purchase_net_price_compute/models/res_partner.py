from odoo import fields, models

class Partner(models.Model):
    _inherit = 'res.partner'
    
    # These are now just defaults, actual logic is on product
    discount_percentage = fields.Float(
        string="Default Discount %", 
        default=0.0, 
        help="Default discount percentage for products without specific rules"
    )
    freight_percentage = fields.Float(
        string="Default Freight %", 
        default=0.0, 
        help="Default freight percentage for products without specific rules"
    )