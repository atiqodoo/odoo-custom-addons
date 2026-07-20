# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from odoo.addons.purchase_net_price_compute.models.vendor_invoice_profile import (
    VENDOR_INVOICE_PROFILE_CROWN,
)
from ..services.crown_invoice_calculator import calculate_line


_logger = logging.getLogger(__name__)


class CrownVendorPriceWizardLine(models.TransientModel):
    _inherit = 'vendor.price.wizard.line'

    vendor_line_total = fields.Monetary(
        string='Vendor Line Total',
        currency_field='currency_id',
        help='Line total printed on the vendor invoice, excluding VAT.',
    )
    purchase_tax_ids = fields.Many2many(
        related='purchase_line_id.taxes_id',
        string='VAT / Purchase Taxes',
        readonly=True,
    )
    vat_description = fields.Char(
        string='VAT',
        compute='_compute_vat_description',
        readonly=True,
    )
    structured_discount_amount = fields.Monetary(
        string='Structured Discount',
        compute='_compute_crown_line_metrics',
        currency_field='currency_id',
        readonly=True,
    )
    structured_discount_percentage = fields.Float(
        string='Structured Discount %',
        compute='_compute_crown_line_metrics',
        readonly=True,
    )
    discount_per_quantity = fields.Monetary(
        string='Discount / Qty',
        compute='_compute_crown_line_metrics',
        currency_field='currency_id',
        readonly=True,
    )
    freight_amount = fields.Monetary(
        string='Freight Amount',
        compute='_compute_crown_line_metrics',
        currency_field='currency_id',
        readonly=True,
    )
    preliminary_unit_price_excl_vat = fields.Monetary(
        string='Preliminary Unit Excl. VAT',
        compute='_compute_crown_line_metrics',
        currency_field='currency_id',
        readonly=True,
    )
    final_unit_price_excl_vat = fields.Monetary(
        string='Final Unit Excl. VAT',
        compute='_compute_crown_final_amounts',
        currency_field='currency_id',
        readonly=True,
    )
    final_unit_price_incl_vat = fields.Monetary(
        string='Final Unit Incl. VAT',
        compute='_compute_crown_final_amounts',
        currency_field='currency_id',
        readonly=True,
    )
    final_line_total_vat_incl = fields.Monetary(
        string='Final Line Total Incl. VAT',
        compute='_compute_crown_final_amounts',
        currency_field='currency_id',
        readonly=True,
    )
    allocated_variance_amount = fields.Monetary(
        string='Allocated Invoice Variance',
        compute='_compute_crown_final_amounts',
        currency_field='currency_id',
        readonly=True,
    )

    def _is_crown_profile(self):
        self.ensure_one()
        return self.wizard_id.vendor_invoice_profile == VENDOR_INVOICE_PROFILE_CROWN

    @api.depends('purchase_tax_ids', 'purchase_tax_ids.name', 'purchase_tax_ids.amount')
    def _compute_vat_description(self):
        for line in self:
            line.vat_description = ', '.join(line.purchase_tax_ids.mapped('display_name')) or _('No VAT')

    @api.depends(
        'vendor_price',
        'vendor_line_total',
        'product_qty',
        'applied_freight',
        'wizard_id.vendor_invoice_profile',
    )
    def _compute_crown_line_metrics(self):
        for line in self:
            if not line._is_crown_profile():
                line.structured_discount_amount = 0.0
                line.structured_discount_percentage = 0.0
                line.discount_per_quantity = 0.0
                line.freight_amount = 0.0
                line.preliminary_unit_price_excl_vat = line.calculated_subtotal
                continue
            result = calculate_line(
                line.product_qty,
                line.vendor_price,
                line.vendor_line_total,
                line.applied_freight,
            )
            line.structured_discount_amount = result['structured_discount_amount']
            line.structured_discount_percentage = result['structured_discount_percentage']
            line.discount_per_quantity = result['discount_per_quantity']
            line.freight_amount = result['freight_amount']
            line.preliminary_unit_price_excl_vat = result['preliminary_unit_excl_vat']

    @api.depends(
        'vendor_price',
        'vendor_line_total',
        'product_qty',
        'applied_discount',
        'applied_freight',
        'wizard_id.vendor_invoice_profile',
    )
    def _compute_calculated_subtotal(self):
        super()._compute_calculated_subtotal()
        for line in self.filtered(lambda item: item._is_crown_profile()):
            result = calculate_line(
                line.product_qty,
                line.vendor_price,
                line.vendor_line_total,
                line.applied_freight,
            )
            line.calculated_subtotal = result['preliminary_unit_excl_vat']

    @api.depends(
        'calculated_subtotal',
        'product_qty',
        'purchase_tax_ids',
        'wizard_id.invoice_allocation_ratio',
        'wizard_id.vendor_invoice_profile',
        'line_total_vat_incl',
    )
    def _compute_crown_final_amounts(self):
        for line in self:
            ratio = line.wizard_id.invoice_allocation_ratio or 1.0
            if not line._is_crown_profile():
                ratio = 1.0
            final_unit_excl = (line.calculated_subtotal or 0.0) * ratio
            quantity = line.product_qty or 0.0
            taxes = line.purchase_tax_ids
            if taxes:
                unit_tax_result = taxes.compute_all(
                    final_unit_excl,
                    currency=line.currency_id,
                    quantity=1.0,
                    product=line.product_id,
                    partner=line.wizard_id.purchase_id.partner_id,
                )
                line_tax_result = taxes.compute_all(
                    final_unit_excl,
                    currency=line.currency_id,
                    quantity=quantity,
                    product=line.product_id,
                    partner=line.wizard_id.purchase_id.partner_id,
                )
                final_unit_incl = unit_tax_result['total_included']
                final_line_incl = line_tax_result['total_included']
            else:
                final_unit_incl = final_unit_excl
                final_line_incl = final_unit_excl * quantity

            line.final_unit_price_excl_vat = final_unit_excl
            line.final_unit_price_incl_vat = final_unit_incl
            line.final_line_total_vat_incl = final_line_incl
            line.allocated_variance_amount = (
                (line.line_total_vat_incl or 0.0) - final_line_incl
                if line._is_crown_profile()
                else 0.0
            )

    @api.depends(
        'vendor_promised_cost_vat_incl',
        'unit_price_vat_incl',
        'final_unit_price_incl_vat',
        'wizard_id.vendor_invoice_profile',
    )
    def _compute_promised_cost_difference_vat_incl(self):
        super()._compute_promised_cost_difference_vat_incl()

    @api.onchange('vendor_price', 'vendor_line_total', 'product_qty')
    def _onchange_crown_structured_discount(self):
        for line in self.filtered(lambda item: item._is_crown_profile()):
            result = calculate_line(
                line.product_qty,
                line.vendor_price,
                line.vendor_line_total,
                line.applied_freight,
            )
            line.applied_discount = result['structured_discount_percentage']

    def _validate_for_bill(self):
        super()._validate_for_bill()
        if not self._is_crown_profile():
            return
        if self.product_qty <= 0:
            raise ValidationError(_('Received quantity must be greater than zero for %s.') % self.product_id.display_name)
        if self.vendor_line_total <= 0:
            raise ValidationError(_('Vendor Line Total must be greater than zero for %s.') % self.product_id.display_name)
        if self.applied_freight < 0:
            raise ValidationError(_('Freight percentage cannot be negative for %s.') % self.product_id.display_name)
        if not self.purchase_tax_ids:
            raise ValidationError(_(
                'No purchase VAT/tax is configured for %(product)s. Configure the product purchase tax before billing.'
            ) % {'product': self.product_id.display_name})
        if self.vendor_line_total > self.product_qty * self.vendor_price:
            _logger.warning(
                '[VPC_CROWN] negative_structured_discount wizard_line_id=%s product_id=%s '
                'expected_total=%s vendor_line_total=%s',
                self.id,
                self.product_id.id,
                self.product_qty * self.vendor_price,
                self.vendor_line_total,
            )

    def _get_effective_bill_unit_price(self):
        self.ensure_one()
        if self._is_crown_profile():
            # Monetary display fields are currency-rounded. Bill price_unit must
            # retain full precision so quantity multiplication reconciles to the
            # vendor's final invoice total without cumulative unit-rounding drift.
            return (
                (self.calculated_subtotal or 0.0)
                * (self.wizard_id.invoice_allocation_ratio or 1.0)
            )
        return super()._get_effective_bill_unit_price()

    def _get_effective_bill_discount(self):
        self.ensure_one()
        if self._is_crown_profile():
            return self.structured_discount_percentage
        return super()._get_effective_bill_discount()

    def _get_promised_comparison_unit_vat_incl(self):
        self.ensure_one()
        if self._is_crown_profile():
            return self.final_unit_price_incl_vat
        return super()._get_promised_comparison_unit_vat_incl()

    def _prepare_profile_bill_line_vals(self):
        values = super()._prepare_profile_bill_line_vals()
        if self._is_crown_profile():
            values.update({
                'vendor_invoice_unit_price': self.vendor_price,
                'vendor_invoice_line_total': self.vendor_line_total,
                'vendor_structured_discount_amount': self.structured_discount_amount,
                'vendor_structured_discount_percentage': self.structured_discount_percentage,
                'vendor_discount_per_quantity': self.discount_per_quantity,
                'vendor_invoice_variance_allocated': self.allocated_variance_amount,
                'vendor_final_unit_price_vat_incl': self.final_unit_price_incl_vat,
            })
        return values
