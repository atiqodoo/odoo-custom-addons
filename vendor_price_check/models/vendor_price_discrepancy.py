# vendor_price_check/models/vendor_price_discrepancy.py
from odoo import fields, models

class VendorPriceDiscrepancy(models.Model):
    _name = 'vendor.price.discrepancy'
    _description = 'Vendor Price Discrepancy'

    bill_id = fields.Many2one('account.move', string='Bill', required=True)
    product_id = fields.Many2one('product.product', string='Product', required=True)
    vendor_id = fields.Many2one('res.partner', string='Vendor', required=True)
    vendor_price = fields.Float(string='Vendor Price', required=True)
    lowest_price = fields.Float(string='Lowest Historical Price')
    average_price = fields.Float(string='Average Historical Price')
    price_difference_lowest = fields.Float(string='Difference from Lowest')
    percentage_diff_lowest = fields.Float(string='Percentage Difference from Lowest')
    price_difference_average = fields.Float(string='Difference from Average')
    percentage_diff_average = fields.Float(string='Percentage Difference from Average')
    bill_count = fields.Integer(string='Bill Count', default=1)
    discrepancy_date = fields.Date(string='Date', default=fields.Date.context_today)