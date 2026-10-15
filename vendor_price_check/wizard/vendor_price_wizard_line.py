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
        store=True,
        currency_field='currency_id',
        readonly=True,
    )
    line_total_vat_incl = fields.Monetary(
        string='Line Total (VAT Incl.)',
        compute='_compute_vat_inclusive_amounts',
        store=True,
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
        store=True,
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
        return self.wizard_id._apply_invoice_allocation_to_unit_price(
            self.calculated_subtotal,
            line=self,
        )

    def _get_effective_bill_discount(self):
        self.ensure_one()
        return self.applied_discount

    def _get_promised_comparison_unit_vat_incl(self):
        self.ensure_one()
        return self.unit_price_vat_incl

    def _prepare_profile_bill_line_vals(self):
        """Profile extension hook for persistent audit values."""
        self.ensure_one()
        return self._prepare_common_bill_line_audit_vals()

    def _get_optional_field_value(self, field_name, default=False):
        self.ensure_one()
        return self[field_name] if field_name in self._fields else default

    def _prepare_common_bill_line_audit_vals(self):
        self.ensure_one()
        return {
            'wizard_vendor_list_unit_price': self.vendor_price,
            'wizard_vendor_line_total': self._get_optional_field_value('vendor_line_total', 0.0),
            'wizard_discount_percentage': self.applied_discount,
            'wizard_freight_percentage': self.applied_freight,
            'wizard_tint_type': self._get_optional_field_value('gamma_tint_type') or False,
            'wizard_tint_percentage': self._get_optional_field_value('gamma_tint_percentage', 0.0),
            'wizard_computed_unit_excl_vat': self.calculated_subtotal,
            'wizard_computed_unit_vat_incl': self.unit_price_vat_incl,
            'wizard_computed_line_total_vat_incl': self.line_total_vat_incl,
            'wizard_computed_gross_total': self._get_optional_field_value('gamma_gross_total', 0.0),
            'wizard_computed_discount_amount': (
                self._get_optional_field_value('gamma_discount_amount', 0.0)
                or self._get_optional_field_value('structured_discount_amount', 0.0)
            ),
            'wizard_computed_tint_charge': self._get_optional_field_value('gamma_tint_charge', 0.0),
            'wizard_computed_subtotal_excl_vat': (
                self._get_optional_field_value('gamma_subtotal_excl_vat', 0.0)
                or self.calculated_subtotal * (self.product_qty or 0.0)
            ),
            'wizard_computed_promised_cost_diff_vat_incl': self.promised_cost_difference_vat_incl,
        }

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

    @api.depends(
        'calculated_subtotal',
        'product_qty',
        'purchase_line_id.taxes_id',
        'currency_id',
        'wizard_id.vendor_invoice_final_total',
        'wizard_id.invoice_total_vat_incl',
        'wizard_id.vendor_invoice_profile',
    )
    def _compute_vat_inclusive_amounts(self):
        for line in self:
            unit_price = line.calculated_subtotal or 0.0
            quantity = line.product_qty or 0.0
            purchase_line = line.purchase_line_id
            if purchase_line:
                line.unit_price_vat_incl = purchase_line._get_price_with_configured_vat(
                    unit_price,
                    quantity=1.0,
                    currency=line.currency_id,
                    partner=line.wizard_id.purchase_id.partner_id,
                )
                line.line_total_vat_incl = purchase_line._get_price_with_configured_vat(
                    unit_price,
                    quantity=quantity,
                    currency=line.currency_id,
                    partner=line.wizard_id.purchase_id.partner_id,
                )
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
