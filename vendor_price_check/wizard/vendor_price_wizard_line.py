from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
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
    unit_price_vat_incl = fields.Monetary(
        string='Unit Price + Configured VAT',
        compute='_compute_vat_inclusive_amounts',
        currency_field='currency_id',
        readonly=True,
    )
    line_total_vat_incl = fields.Monetary(
        string='Line Total (VAT Incl.)',
        compute='_compute_vat_inclusive_amounts',
        currency_field='currency_id',
        readonly=True,
    )
    vendor_promised_cost_vat_incl = fields.Monetary(
        string='Vendor Promised Cost (VAT Incl.)',
        related='purchase_line_id.vendor_promised_cost_vat_incl',
        currency_field='currency_id',
        readonly=True,
    )
    promised_cost_difference_vat_incl = fields.Monetary(
        string='Promised vs Unit + VAT Diff.',
        compute='_compute_promised_cost_difference_vat_incl',
        currency_field='currency_id',
        readonly=True,
    )
    discrepancy_note = fields.Text(string='Discrepancy Note')
    purchase_line_id = fields.Many2one('purchase.order.line', string='Purchase Order Line', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    def _validate_for_bill(self):
        """Profile extension hook for line-level validation."""
        self.ensure_one()
        if not self.vendor_price:
            raise ValidationError(_(
                'Vendor Price is required and must be a non-zero value for %(product)s.'
            ) % {'product': self.product_id.display_name})

    def _get_effective_bill_unit_price(self):
        """Profile extension hook returning the tax-exclusive bill unit price."""
        self.ensure_one()
        return self.calculated_subtotal

    def _get_effective_bill_discount(self):
        self.ensure_one()
        return self.applied_discount

    def _get_promised_comparison_unit_vat_incl(self):
        self.ensure_one()
        return self.unit_price_vat_incl

    def _prepare_profile_bill_line_vals(self):
        """Profile extension hook for persistent audit values."""
        self.ensure_one()
        return {}

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

    @api.depends('calculated_subtotal', 'product_qty', 'purchase_line_id.taxes_id', 'currency_id')
    def _compute_vat_inclusive_amounts(self):
        for line in self:
            unit_price = line.calculated_subtotal or 0.0
            quantity = line.product_qty or 0.0
            taxes = line.purchase_line_id.taxes_id
            if taxes:
                tax_res = taxes.compute_all(
                    unit_price,
                    currency=line.currency_id,
                    quantity=quantity,
                    product=line.product_id,
                    partner=line.wizard_id.purchase_id.partner_id,
                )
                total_included = tax_res['total_included']
                line.line_total_vat_incl = total_included
                line.unit_price_vat_incl = total_included / quantity if quantity else 0.0
            else:
                line.unit_price_vat_incl = unit_price
                line.line_total_vat_incl = unit_price * quantity

    @api.depends('vendor_promised_cost_vat_incl', 'unit_price_vat_incl')
    def _compute_promised_cost_difference_vat_incl(self):
        for line in self:
            actual_unit_price = line._get_promised_comparison_unit_vat_incl()
            line.promised_cost_difference_vat_incl = (
                actual_unit_price - line.vendor_promised_cost_vat_incl
                if line.vendor_promised_cost_vat_incl
                else 0.0
            )
