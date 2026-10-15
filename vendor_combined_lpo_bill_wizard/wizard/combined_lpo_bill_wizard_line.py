# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare

from odoo.addons.purchase_net_price_compute.models.vendor_invoice_profile import (
    VENDOR_INVOICE_PROFILE_CROWN,
)
from odoo.addons.vendor_purchase_promotions.models.res_partner import VENDOR_PROFILE_GAMMA
from odoo.addons.vendor_purchase_promotions.services.promotion_registry import get_calculator

from ..services.debug_payload import line_payload


_logger = logging.getLogger(__name__)


class CombinedLpoBillWizardLine(models.TransientModel):
    _name = 'combined.lpo.bill.wizard.line'
    _description = 'Combined LPO Vendor Bill Wizard Line'

    wizard_id = fields.Many2one(
        'combined.lpo.bill.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    include_line = fields.Boolean(string='Include', default=True)
    purchase_id = fields.Many2one('purchase.order', string='LPO', readonly=True)
    purchase_line_id = fields.Many2one('purchase.order.line', string='LPO Line', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='UoM', readonly=True)
    product_qty = fields.Float(string='Quantity')
    max_billable_qty = fields.Float(string='Max Billable Qty', readonly=True)
    po_unit_price = fields.Monetary(string='PO Unit Price', currency_field='currency_id', readonly=True)
    vendor_price = fields.Monetary(string='Vendor Unit/List Price', currency_field='currency_id')
    vendor_line_total = fields.Monetary(string='Vendor Line Total', currency_field='currency_id')
    applied_discount = fields.Float(string='Discount %')
    applied_freight = fields.Float(string='Freight %')
    gamma_tint_type = fields.Selection(
        [
            ('not_tinted', 'Not Tinted'),
            ('factory', 'Factory'),
            ('showroom_branch', 'Showroom/Branch'),
            ('custom', 'Custom'),
        ],
        string='Gamma Tinting',
        default='not_tinted',
    )
    gamma_tint_percentage = fields.Float(string='Gamma Tint %')
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    purchase_tax_ids = fields.Many2many(
        related='purchase_line_id.taxes_id',
        string='Purchase Taxes',
        readonly=True,
    )
    vendor_promised_cost_vat_incl = fields.Monetary(
        related='purchase_line_id.vendor_promised_cost_vat_incl',
        string='Vendor Promised Cost',
        currency_field='currency_id',
        readonly=True,
    )

    bill_unit_price_excl_vat = fields.Monetary(
        string='Bill Unit Excl. VAT',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    line_total_vat_incl = fields.Monetary(
        string='Line Total VAT Incl.',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    final_unit_price_excl_vat = fields.Monetary(
        string='Final Unit Excl. VAT',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    final_unit_price_incl_vat = fields.Monetary(
        string='Final Unit Incl. VAT',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    unit_price_vat_incl = fields.Monetary(
        string='Unit Price + Configured VAT',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
        help='VAT-inclusive cost price per unit using the purchase line configured taxes.',
    )
    final_line_total_vat_incl = fields.Monetary(
        string='Final Line Total VAT Incl.',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    promised_cost_difference_vat_incl = fields.Monetary(
        string='Promised Cost Diff.',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    gamma_gross_total = fields.Monetary(
        string='Gamma Gross',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    gamma_discount_amount = fields.Monetary(
        string='Gamma Discount',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    gamma_tint_charge = fields.Monetary(
        string='Gamma Tint Charge',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    gamma_subtotal_excl_vat = fields.Monetary(
        string='Gamma Subtotal Excl. VAT',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    structured_discount_amount = fields.Monetary(
        string='Structured Discount',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    structured_discount_percentage = fields.Float(
        string='Structured Discount %',
        compute='_compute_amounts',
        store=True,
    )
    discount_per_quantity = fields.Monetary(
        string='Discount / Qty',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    freight_amount = fields.Monetary(
        string='Freight Amount',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    allocated_variance_amount = fields.Monetary(
        string='Allocated Variance',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )

    @api.onchange('gamma_tint_type')
    def _onchange_gamma_tint_type(self):
        rates = get_calculator(VENDOR_PROFILE_GAMMA).TINT_RATES
        for line in self:
            if line.gamma_tint_type in rates:
                line.gamma_tint_percentage = rates[line.gamma_tint_type]

    @api.depends(
        'include_line',
        'product_qty',
        'vendor_price',
        'vendor_line_total',
        'applied_discount',
        'applied_freight',
        'gamma_tint_percentage',
        'purchase_tax_ids',
        'wizard_id.vendor_invoice_profile',
        'wizard_id.invoice_allocation_ratio',
        'vendor_promised_cost_vat_incl',
    )
    def _compute_amounts(self):
        for line in self:
            line._compute_single_line_amounts()

    def _compute_single_line_amounts(self):
        self.ensure_one()
        zero_values = {
            'bill_unit_price_excl_vat': 0.0,
            'line_total_vat_incl': 0.0,
            'final_unit_price_excl_vat': 0.0,
            'final_unit_price_incl_vat': 0.0,
            'unit_price_vat_incl': 0.0,
            'final_line_total_vat_incl': 0.0,
            'promised_cost_difference_vat_incl': 0.0,
            'gamma_gross_total': 0.0,
            'gamma_discount_amount': 0.0,
            'gamma_tint_charge': 0.0,
            'gamma_subtotal_excl_vat': 0.0,
            'structured_discount_amount': 0.0,
            'structured_discount_percentage': 0.0,
            'discount_per_quantity': 0.0,
            'freight_amount': 0.0,
            'allocated_variance_amount': 0.0,
        }
        if not self.include_line:
            for field_name, value in zero_values.items():
                self[field_name] = value
            return

        try:
            amounts = self.wizard_id._profile_adapter().prepare_line_amounts(self)
        except Exception as error:
            _logger.warning(
                '[CLPO_LINE] compute_failed wizard_line_id=%s purchase_line_id=%s error=%s',
                self.id,
                self.purchase_line_id.id,
                error,
            )
            amounts = {'bill_unit_price_excl_vat': 0.0, 'subtotal_excl_vat': 0.0}

        unit_excl = amounts.get('bill_unit_price_excl_vat', 0.0)
        qty = self.product_qty or 0.0
        tax_partner = self.wizard_id.partner_id
        if self.purchase_line_id:
            unit_incl = self.purchase_line_id._get_price_with_configured_vat(
                unit_excl,
                currency=self.currency_id,
                quantity=1.0,
                partner=tax_partner,
            )
            line_incl = self.purchase_line_id._get_price_with_configured_vat(
                unit_excl,
                currency=self.currency_id,
                quantity=qty,
                partner=tax_partner,
            )
        else:
            unit_incl = unit_excl
            line_incl = unit_excl * qty

        allocation_values = self.wizard_id._get_variance_policy_values()
        ratio = allocation_values['allocation_ratio'] if allocation_values['allocation_enabled'] else 1.0
        final_unit_excl = unit_excl * ratio
        if self.purchase_line_id:
            final_unit_incl = self.purchase_line_id._get_price_with_configured_vat(
                final_unit_excl,
                currency=self.currency_id,
                quantity=1.0,
                partner=tax_partner,
            )
            final_line_incl = self.purchase_line_id._get_price_with_configured_vat(
                final_unit_excl,
                currency=self.currency_id,
                quantity=qty,
                partner=tax_partner,
            )
        else:
            final_unit_incl = final_unit_excl
            final_line_incl = final_unit_excl * qty

        self.bill_unit_price_excl_vat = unit_excl
        self.line_total_vat_incl = line_incl
        self.final_unit_price_excl_vat = final_unit_excl
        self.final_unit_price_incl_vat = final_unit_incl
        self.unit_price_vat_incl = final_unit_incl
        self.final_line_total_vat_incl = final_line_incl
        self.promised_cost_difference_vat_incl = (
            final_unit_incl - self.vendor_promised_cost_vat_incl
            if self.vendor_promised_cost_vat_incl
            else 0.0
        )
        self.gamma_gross_total = amounts.get('gross_total', 0.0)
        self.gamma_discount_amount = amounts.get('discount_amount', 0.0)
        self.gamma_tint_charge = amounts.get('tint_charge', 0.0)
        self.gamma_subtotal_excl_vat = amounts.get('subtotal_excl_vat', 0.0)
        self.structured_discount_amount = amounts.get('discount_amount', 0.0)
        self.structured_discount_percentage = amounts.get('discount_percentage', 0.0)
        self.discount_per_quantity = amounts.get('discount_per_quantity', 0.0)
        self.freight_amount = amounts.get('freight_amount', 0.0)
        self.allocated_variance_amount = line_incl - final_line_incl

        _logger.debug('[CLPO_LINE] computed payload=%s', line_payload(self))

    @api.onchange('vendor_price', 'vendor_line_total', 'product_qty', 'applied_freight')
    def _onchange_crown_structured_discount(self):
        for line in self.filtered(
            lambda item: item.wizard_id.vendor_invoice_profile == VENDOR_INVOICE_PROFILE_CROWN
        ):
            if line.product_qty and line.vendor_price and line.vendor_line_total:
                expected_total = line.product_qty * line.vendor_price
                if expected_total:
                    line.applied_discount = (
                        (expected_total - line.vendor_line_total) / expected_total * 100.0
                    )

    def _validate_for_bill(self):
        self.ensure_one()
        if not self.include_line:
            return
        if self.product_qty <= 0:
            raise ValidationError(_('Quantity must be greater than zero for %s.') % self.product_id.display_name)
        if float_compare(
            self.product_qty,
            self.max_billable_qty,
            precision_rounding=self.product_uom_id.rounding or 0.01,
        ) > 0:
            raise ValidationError(_(
                'Quantity for %(product)s exceeds received uninvoiced quantity.'
            ) % {'product': self.product_id.display_name})
        if self.vendor_price <= 0:
            raise ValidationError(_('Vendor price is required for %s.') % self.product_id.display_name)
        if not self.purchase_tax_ids:
            raise ValidationError(_('Configure purchase VAT/taxes for %s before billing.') % self.product_id.display_name)
        if self.wizard_id.vendor_invoice_profile == VENDOR_INVOICE_PROFILE_CROWN:
            if self.vendor_line_total <= 0:
                raise ValidationError(_('Vendor line total is required for %s.') % self.product_id.display_name)
            if self.applied_freight < 0:
                raise ValidationError(_('Freight percentage cannot be negative for %s.') % self.product_id.display_name)
        if self.wizard_id.vendor_invoice_profile == VENDOR_PROFILE_GAMMA:
            if not 0.0 <= self.applied_discount <= 100.0:
                raise ValidationError(_('Gamma discount must be between 0 and 100 percent.'))
            if self.gamma_tint_percentage < 0:
                raise ValidationError(_('Gamma tint percentage cannot be negative.'))

    def _get_effective_bill_unit_price(self):
        self.ensure_one()
        amounts = self.wizard_id._profile_adapter().prepare_line_amounts(self)
        return self.wizard_id._apply_invoice_allocation_to_unit_price(
            amounts.get('bill_unit_price_excl_vat', 0.0),
            line=self,
        )

    def _get_effective_bill_discount(self):
        self.ensure_one()
        if self.wizard_id.vendor_invoice_profile == VENDOR_INVOICE_PROFILE_CROWN:
            return self.structured_discount_percentage
        return self.applied_discount

    def _prepare_common_bill_line_audit_vals(self):
        self.ensure_one()
        amounts = self.wizard_id._profile_adapter().prepare_line_amounts(self)
        unit_excl = amounts.get('bill_unit_price_excl_vat', 0.0)
        subtotal_excl = amounts.get('subtotal_excl_vat', unit_excl * (self.product_qty or 0.0))
        return {
            'wizard_vendor_list_unit_price': self.vendor_price,
            'wizard_vendor_line_total': self.vendor_line_total,
            'wizard_discount_percentage': self.applied_discount,
            'wizard_freight_percentage': self.applied_freight,
            'wizard_tint_type': self.gamma_tint_type or False,
            'wizard_tint_percentage': self.gamma_tint_percentage,
            'wizard_computed_unit_excl_vat': unit_excl,
            'wizard_computed_unit_vat_incl': self.unit_price_vat_incl,
            'wizard_computed_line_total_vat_incl': self.line_total_vat_incl,
            'wizard_computed_gross_total': self.gamma_gross_total,
            'wizard_computed_discount_amount': (
                self.gamma_discount_amount or self.structured_discount_amount
            ),
            'wizard_computed_tint_charge': self.gamma_tint_charge,
            'wizard_computed_subtotal_excl_vat': (
                self.gamma_subtotal_excl_vat or subtotal_excl
            ),
            'wizard_computed_promised_cost_diff_vat_incl': self.promised_cost_difference_vat_incl,
        }
