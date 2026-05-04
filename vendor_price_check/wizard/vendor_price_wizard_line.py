from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)

class VendorPriceWizardLine(models.TransientModel):
    _name = 'vendor.price.wizard.line'
    _description = 'Vendor Price Wizard Line'

    wizard_id = fields.Many2one('vendor.price.wizard', string='Wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    product_qty = fields.Float(string='Quantity', readonly=True)
    price_unit = fields.Float(string='PO Unit Price', readonly=True)
    vendor_price = fields.Float(string='Vendor Price', required=True)  # UI enforces blank until user input
    use_custom_pricing = fields.Boolean(string='Use Custom Pricing', default=True)
    applied_discount = fields.Float(string='Discount %')
    applied_freight = fields.Float(string='Freight %')
    calculated_subtotal = fields.Float(string='Calculated Subtotal', compute='_compute_calculated_subtotal', store=True)
    discrepancy_note = fields.Text(string='Discrepancy Note')
    purchase_line_id = fields.Many2one('purchase.order.line', string='Purchase Order Line', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    @api.depends('vendor_price', 'applied_discount', 'applied_freight')
    def _compute_calculated_subtotal(self):
        for line in self:
            _logger.debug(f"Computing subtotal for line {line.id}: vendor_price={line.vendor_price}, applied_discount={line.applied_discount}%, applied_freight={line.applied_freight}%")
            # Always apply custom pricing formula since use_custom_pricing is True
            subtotal = line.vendor_price * (1 - (line.applied_discount or 0.0) / 100) * (1 + (line.applied_freight or 0.0) / 100)
            line.calculated_subtotal = round(subtotal, 2)

    @api.onchange('vendor_price', 'applied_discount', 'applied_freight')
    def _onchange_pricing_fields(self):
        _logger.debug(f"Onchange triggered for line {self.id}: vendor_price={self.vendor_price}, applied_discount={self.applied_discount}%, applied_freight={self.applied_freight}%")
        # Always apply custom pricing formula since use_custom_pricing is True
        subtotal = self.vendor_price * (1 - (self.applied_discount or 0.0) / 100) * (1 + (self.applied_freight or 0.0) / 100)
        self.calculated_subtotal = round(subtotal, 2)