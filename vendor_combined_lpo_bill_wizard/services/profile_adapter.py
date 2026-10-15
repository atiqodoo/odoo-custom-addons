# -*- coding: utf-8 -*-
import logging

from odoo import _
from odoo.exceptions import ValidationError

from odoo.addons.purchase_net_price_compute.models.vendor_invoice_profile import (
    VENDOR_INVOICE_PROFILE_CROWN,
    VENDOR_INVOICE_PROFILE_STANDARD,
)
from odoo.addons.vendor_price_check.services.crown_invoice_calculator import (
    calculate_line,
    calculate_variance,
)
from odoo.addons.vendor_purchase_promotions.models.res_partner import VENDOR_PROFILE_GAMMA
from odoo.addons.vendor_purchase_promotions.services.promotion_registry import get_calculator


_logger = logging.getLogger(__name__)


PROFILE_SELECTION = [
    (VENDOR_INVOICE_PROFILE_STANDARD, 'Standard Vendor Invoice'),
    (VENDOR_INVOICE_PROFILE_CROWN, 'Crown Paints Invoice'),
    (VENDOR_PROFILE_GAMMA, 'Gamma Paints Invoice'),
]


class CombinedLpoProfileAdapter:
    def __init__(self, wizard):
        self.wizard = wizard

    def compute_crown_variance(self):
        result = calculate_variance(
            self.wizard.invoice_total_vat_incl,
            self.wizard.vendor_invoice_final_total,
        )
        _logger.info(
            '[CLPO_CROWN] variance wizard_id=%s calculated_total=%s vendor_total=%s result=%s',
            self.wizard.id,
            self.wizard.invoice_total_vat_incl,
            self.wizard.vendor_invoice_final_total,
            result,
        )
        return result

    def prepare_line_amounts(self, line):
        profile = line.wizard_id.vendor_invoice_profile
        if profile == VENDOR_PROFILE_GAMMA:
            return self._prepare_gamma_amounts(line)
        if profile == VENDOR_INVOICE_PROFILE_CROWN:
            return self._prepare_crown_amounts(line)
        return self._prepare_standard_amounts(line)

    def _prepare_standard_amounts(self, line):
        unit = (
            (line.vendor_price or 0.0)
            * (1 - (line.applied_discount or 0.0) / 100.0)
            * (1 + (line.applied_freight or 0.0) / 100.0)
        )
        return {
            'bill_unit_price_excl_vat': unit,
            'gross_total': (line.vendor_price or 0.0) * (line.product_qty or 0.0),
            'discount_amount': 0.0,
            'tint_charge': 0.0,
            'subtotal_excl_vat': unit * (line.product_qty or 0.0),
        }

    def _prepare_gamma_amounts(self, line):
        result = get_calculator(VENDOR_PROFILE_GAMMA).calculate_unit(
            quantity=line.product_qty,
            list_unit_price=line.vendor_price,
            discount_percentage=line.applied_discount,
            tint_percentage=line.gamma_tint_percentage,
        )
        _logger.debug(
            '[CLPO_GAMMA] line_amounts wizard_id=%s purchase_line_id=%s result=%s',
            line.wizard_id.id,
            line.purchase_line_id.id,
            result,
        )
        return {
            'bill_unit_price_excl_vat': result['unit_cost_excl_vat'],
            'gross_total': result['gross_total'],
            'discount_amount': result['discount_amount'],
            'tint_charge': result['tint_charge'],
            'subtotal_excl_vat': result['subtotal_excl_vat'],
        }

    def _prepare_crown_amounts(self, line):
        result = calculate_line(
            line.product_qty,
            line.vendor_price,
            line.vendor_line_total,
            line.applied_freight,
        )
        _logger.debug(
            '[CLPO_CROWN] line_amounts wizard_id=%s purchase_line_id=%s result=%s',
            line.wizard_id.id,
            line.purchase_line_id.id,
            result,
        )
        return {
            'bill_unit_price_excl_vat': result['preliminary_unit_excl_vat'],
            'gross_total': result['expected_total'],
            'discount_amount': result['structured_discount_amount'],
            'discount_percentage': result['structured_discount_percentage'],
            'discount_per_quantity': result['discount_per_quantity'],
            'freight_amount': result['freight_amount'],
            'subtotal_excl_vat': result['preliminary_total_excl_vat'],
        }

    def validate_wizard(self):
        wizard = self.wizard
        if not wizard.line_ids:
            raise ValidationError(_('There are no eligible received LPO lines to bill.'))
        wizard._validate_required_vendor_invoice_final_total()

        if wizard.vendor_invoice_profile == VENDOR_PROFILE_GAMMA and wizard.vendor_invoice_final_total:
            rounding = wizard.currency_id.rounding or 0.01
            if abs(wizard.invoice_total_vat_incl - wizard.vendor_invoice_final_total) > rounding:
                _logger.warning(
                    '[VPC_VARIANCE] combined_gamma_total_variance wizard_id=%s '
                    'calculated=%s vendor_total=%s variance=%s',
                    wizard.id,
                    wizard.invoice_total_vat_incl,
                    wizard.vendor_invoice_final_total,
                    wizard.invoice_total_vat_incl - wizard.vendor_invoice_final_total,
                )

        _logger.info('[CLPO_VALIDATE] wizard_valid payload=%s', wizard._debug_payload())

    def prepare_bill_vals(self):
        wizard = self.wizard
        values = {
            'vendor_invoice_profile': wizard.vendor_invoice_profile,
            'vendor_calculated_total_vat_incl': wizard.invoice_total_vat_incl,
            'vendor_invoice_final_total': wizard.vendor_invoice_final_total,
            'vendor_invoice_variance_amount': wizard.invoice_variance_amount,
            'vendor_invoice_variance_percentage': wizard.invoice_variance_percentage,
        }
        if wizard.vendor_invoice_profile == VENDOR_INVOICE_PROFILE_CROWN:
            values.update({
                'vendor_calculated_total_vat_incl': wizard.invoice_total_vat_incl,
                'vendor_invoice_final_total': wizard.vendor_invoice_final_total,
                'vendor_invoice_variance_amount': wizard.invoice_variance_amount,
                'vendor_invoice_variance_percentage': wizard.invoice_variance_percentage,
            })
        elif wizard.vendor_invoice_profile == VENDOR_PROFILE_GAMMA:
            applications = wizard.gamma_promotion_application_ids
            all_foc_received = bool(applications) and not any(
                application.outstanding_foc_qty > 0 for application in applications
            )
            values.update({
                'vendor_invoice_profile': wizard.vendor_invoice_profile,
                'gamma_vendor_calculated_total_vat_incl': wizard.invoice_total_vat_incl,
                'gamma_vendor_invoice_final_total': wizard.vendor_invoice_final_total,
                'promotion_application_ids': [(6, 0, applications.ids)],
                'promotion_release_state': (
                    'released' if all_foc_received
                    else 'hold' if applications
                    else 'not_required'
                ),
                'promotion_release_reason': (
                    _('Automatically released: every promised FOC unit was received.')
                    if all_foc_received else False
                ),
            })
            _logger.info(
                '[CLPO_PROMOTION] prepare_bill wizard_id=%s application_ids=%s '
                'promised=%s received=%s outstanding=%s',
                wizard.id,
                applications.ids,
                wizard.gamma_promised_foc_qty,
                wizard.gamma_received_foc_qty,
                wizard.gamma_outstanding_foc_qty,
            )
        return values

    def prepare_bill_line_vals(self, line):
        values = {}
        if self.wizard.vendor_invoice_profile == VENDOR_INVOICE_PROFILE_CROWN:
            values.update({
                'vendor_invoice_unit_price': line.vendor_price,
                'vendor_invoice_line_total': line.vendor_line_total,
                'vendor_structured_discount_amount': line.structured_discount_amount,
                'vendor_structured_discount_percentage': line.structured_discount_percentage,
                'vendor_discount_per_quantity': line.discount_per_quantity,
                'vendor_invoice_variance_allocated': line.allocated_variance_amount,
                'vendor_final_unit_price_vat_incl': line.final_unit_price_incl_vat,
            })
        elif self.wizard.vendor_invoice_profile == VENDOR_PROFILE_GAMMA:
            values.update({
                'gamma_invoice_list_unit_price': line.vendor_price,
                'gamma_invoice_discount_percentage': line.applied_discount,
                'gamma_invoice_tint_type': line.gamma_tint_type,
                'gamma_invoice_tint_percentage': line.gamma_tint_percentage,
                'gamma_invoice_gross_total': line.gamma_gross_total,
                'gamma_invoice_discount_amount': line.gamma_discount_amount,
                'gamma_invoice_tint_charge': line.gamma_tint_charge,
                'gamma_invoice_subtotal_excl_vat': line.gamma_subtotal_excl_vat,
            })
        return values
