# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare

from odoo.addons.purchase_net_price_compute.models.vendor_invoice_profile import (
    VENDOR_INVOICE_PROFILE_CROWN,
    VENDOR_INVOICE_PROFILE_SELECTION,
    VENDOR_INVOICE_PROFILE_STANDARD,
)
from ..services.crown_invoice_calculator import calculate_variance


_logger = logging.getLogger(__name__)


class CrownVendorPriceWizard(models.TransientModel):
    _inherit = 'vendor.price.wizard'

    vendor_invoice_profile = fields.Selection(
        selection=VENDOR_INVOICE_PROFILE_SELECTION,
        string='Invoice Calculation Profile',
        compute='_compute_vendor_invoice_profile',
        readonly=True,
    )
    is_crown_profile = fields.Boolean(
        string='Uses Crown Invoice Calculation',
        compute='_compute_vendor_invoice_profile',
    )
    vendor_invoice_final_total = fields.Monetary(
        string='Vendor Invoice Final Total (VAT Incl.)',
        currency_field='currency_id',
        help='Enter the total amount printed on the vendor invoice, including VAT.',
    )
    invoice_variance_amount = fields.Monetary(
        string='Invoice Variance',
        compute='_compute_crown_invoice_variance',
        currency_field='currency_id',
        readonly=True,
    )
    invoice_variance_percentage = fields.Float(
        string='Invoice Variance %',
        compute='_compute_crown_invoice_variance',
        readonly=True,
    )
    invoice_allocation_ratio = fields.Float(
        string='Invoice Allocation Ratio',
        compute='_compute_crown_invoice_variance',
        digits=(16, 10),
        readonly=True,
    )
    invoice_variance_status = fields.Char(
        string='Variance Status',
        compute='_compute_crown_invoice_variance',
        readonly=True,
    )

    @api.depends(
        'purchase_id',
        'purchase_id.partner_id',
        'purchase_id.partner_id.vendor_invoice_profile',
        'purchase_id.partner_id.parent_id.vendor_invoice_profile',
    )
    def _compute_vendor_invoice_profile(self):
        for wizard in self:
            partner = wizard.purchase_id.partner_id
            profile = (
                partner.get_vendor_invoice_profile()
                if partner
                else VENDOR_INVOICE_PROFILE_STANDARD
            )
            wizard.vendor_invoice_profile = profile
            wizard.is_crown_profile = profile == VENDOR_INVOICE_PROFILE_CROWN

    @api.depends(
        'vendor_invoice_profile',
        'invoice_total_vat_incl',
        'vendor_invoice_final_total',
    )
    def _compute_crown_invoice_variance(self):
        for wizard in self:
            if not wizard.is_crown_profile:
                wizard.invoice_variance_amount = 0.0
                wizard.invoice_variance_percentage = 0.0
                wizard.invoice_allocation_ratio = 1.0
                wizard.invoice_variance_status = _('Standard vendor calculation')
                continue

            if not wizard.vendor_invoice_final_total:
                wizard.invoice_variance_amount = 0.0
                wizard.invoice_variance_percentage = 0.0
                wizard.invoice_allocation_ratio = 1.0
                wizard.invoice_variance_status = _('Enter the vendor invoice final total')
                continue

            result = calculate_variance(
                wizard.invoice_total_vat_incl,
                wizard.vendor_invoice_final_total,
            )
            wizard.invoice_variance_amount = result['variance_amount']
            wizard.invoice_variance_percentage = result['variance_percentage']
            wizard.invoice_allocation_ratio = result['allocation_ratio']

            rounding = wizard.currency_id.rounding or 0.01
            comparison = float_compare(
                result['variance_amount'],
                0.0,
                precision_rounding=rounding,
            )
            if comparison > 0:
                wizard.invoice_variance_status = _('Extra invoice discount')
            elif comparison < 0:
                wizard.invoice_variance_status = _('Vendor charged above calculated total')
            else:
                wizard.invoice_variance_status = _('No invoice variance')

    def _validate_invoice_profile_inputs(self):
        super()._validate_invoice_profile_inputs()
        if not self.is_crown_profile:
            return
        if self.vendor_invoice_final_total <= 0:
            raise ValidationError(_('Vendor Invoice Final Total must be greater than zero.'))
        if self.invoice_total_vat_incl <= 0:
            raise ValidationError(_('Calculated invoice total must be greater than zero.'))

        _logger.info(
            '[VPC_CROWN] validation_complete wizard_id=%s po_id=%s calculated_total=%s '
            'vendor_final_total=%s variance=%s variance_pct=%s ratio=%s',
            self.id,
            self.purchase_id.id,
            self.invoice_total_vat_incl,
            self.vendor_invoice_final_total,
            self.invoice_variance_amount,
            self.invoice_variance_percentage,
            self.invoice_allocation_ratio,
        )

    def _prepare_profile_bill_vals(self):
        values = super()._prepare_profile_bill_vals()
        if self.is_crown_profile:
            values.update({
                'vendor_invoice_profile': self.vendor_invoice_profile,
                'vendor_calculated_total_vat_incl': self.invoice_total_vat_incl,
                'vendor_invoice_final_total': self.vendor_invoice_final_total,
                'vendor_invoice_variance_amount': self.invoice_variance_amount,
                'vendor_invoice_variance_percentage': self.invoice_variance_percentage,
            })
        return values

    def _validate_profile_bill_result(self, bill):
        super()._validate_profile_bill_result(bill)
        if not self.is_crown_profile:
            return
        rounding = self.currency_id.rounding or 0.01
        comparison = float_compare(
            bill.amount_total,
            self.vendor_invoice_final_total,
            precision_rounding=rounding,
        )
        _logger.info(
            '[VPC_CROWN] bill_total_check wizard_id=%s bill_id=%s generated_total=%s '
            'vendor_final_total=%s comparison=%s',
            self.id,
            bill.id,
            bill.amount_total,
            self.vendor_invoice_final_total,
            comparison,
        )
        if comparison:
            raise ValidationError(_(
                'The generated bill total (%(generated).2f) does not match the vendor invoice '
                'final total (%(vendor).2f). Review line values, taxes, and rounding.'
            ) % {
                'generated': bill.amount_total,
                'vendor': self.vendor_invoice_final_total,
            })
