# -*- coding: utf-8 -*-
import logging

from odoo import fields, models


_logger = logging.getLogger(__name__)

VENDOR_INVOICE_PROFILE_STANDARD = 'standard'
VENDOR_INVOICE_PROFILE_CROWN = 'crown_paints'
VENDOR_INVOICE_PROFILE_SELECTION = [
    (VENDOR_INVOICE_PROFILE_STANDARD, 'Standard Vendor Invoice'),
    (VENDOR_INVOICE_PROFILE_CROWN, 'Crown Paints Invoice'),
]
VENDOR_INVOICE_ALLOCATION_NONE = 'none'
VENDOR_INVOICE_ALLOCATION_ABSORB_COST = 'absorb_into_cost'
VENDOR_INVOICE_ALLOCATION_SELECTION = [
    (VENDOR_INVOICE_ALLOCATION_NONE, 'No Invoice Total Allocation'),
    (VENDOR_INVOICE_ALLOCATION_ABSORB_COST, 'Absorb Variance Into Product Cost'),
]


class ResPartnerVendorInvoiceProfile(models.Model):
    """Explicit vendor-to-calculation mapping consumed by bill wizards."""

    _inherit = 'res.partner'

    vendor_invoice_profile = fields.Selection(
        selection=VENDOR_INVOICE_PROFILE_SELECTION,
        string='Vendor Invoice Calculation Profile',
        default=VENDOR_INVOICE_PROFILE_STANDARD,
        required=True,
        index=True,
        tracking=True,
        help=(
            'Select the invoice calculation formula used for this vendor. '
            'Child contacts inherit the commercial company profile at runtime.'
        ),
    )
    invoice_variance_currency_id = fields.Many2one(
        'res.currency',
        string='Invoice Variance Currency',
        compute='_compute_invoice_variance_currency_id',
    )
    allowed_invoice_variance_amount = fields.Monetary(
        string='Allowed Invoice Variance Amount',
        currency_field='invoice_variance_currency_id',
        default=0.0,
        tracking=True,
        help='Maximum absolute VAT-inclusive invoice variance allowed for this vendor before acknowledgement is required.',
    )
    variance_warning_dismiss_clicks_required = fields.Integer(
        string='Variance Warning Dismiss Clicks Required',
        default=1,
        tracking=True,
        help='Number of warning dismissals required before an above-limit invoice variance can create/update a bill.',
    )
    block_invoice_variance_above_allowed = fields.Boolean(
        string='Block Invoice Variance Above Allowed',
        default=True,
        tracking=True,
        help='Block bill creation/update when the invoice variance is above the allowed amount until the warning is dismissed enough times.',
    )
    require_vendor_invoice_final_total = fields.Boolean(
        string='Require Vendor Invoice Final Total',
        default=True,
        tracking=True,
        help='Require users to enter the vendor invoice final VAT-inclusive total before creating bills from the vendor bill wizard.',
    )
    invoice_variance_allocation_mode = fields.Selection(
        selection=VENDOR_INVOICE_ALLOCATION_SELECTION,
        string='Invoice Variance Allocation',
        default=VENDOR_INVOICE_ALLOCATION_ABSORB_COST,
        required=True,
        tracking=True,
        help='Controls how a vendor invoice final-total variance is applied to generated bill lines.',
    )

    def _compute_invoice_variance_currency_id(self):
        company_currency = self.env.company.currency_id
        for partner in self:
            partner.invoice_variance_currency_id = (
                partner.company_id.currency_id
                or company_currency
            )

    def get_vendor_invoice_profile(self):
        """Return the commercial vendor profile without relying on its name."""
        self.ensure_one()
        commercial_partner = self.commercial_partner_id or self
        profile = commercial_partner.vendor_invoice_profile or VENDOR_INVOICE_PROFILE_STANDARD
        _logger.debug(
            '[PNPC_PROFILE] resolved partner_id=%s commercial_partner_id=%s profile=%s',
            self.id,
            commercial_partner.id,
            profile,
        )
        return profile

    def get_invoice_variance_policy(self):
        self.ensure_one()
        commercial_partner = self.commercial_partner_id or self
        return {
            'allowed_amount': commercial_partner.allowed_invoice_variance_amount or 0.0,
            'dismiss_clicks_required': max(
                commercial_partner.variance_warning_dismiss_clicks_required or 0,
                0,
            ),
            'block_above_allowed': bool(commercial_partner.block_invoice_variance_above_allowed),
            'require_vendor_invoice_final_total': bool(commercial_partner.require_vendor_invoice_final_total),
            'allocation_mode': (
                commercial_partner.invoice_variance_allocation_mode
                or VENDOR_INVOICE_ALLOCATION_ABSORB_COST
            ),
        }

    def write(self, vals):
        old_profiles = {}
        tracked_fields = {
            'vendor_invoice_profile',
            'allowed_invoice_variance_amount',
            'variance_warning_dismiss_clicks_required',
            'block_invoice_variance_above_allowed',
            'require_vendor_invoice_final_total',
            'invoice_variance_allocation_mode',
        }
        if tracked_fields.intersection(vals):
            old_profiles = {
                partner.id: {
                    'vendor_invoice_profile': partner.vendor_invoice_profile,
                    'allowed_invoice_variance_amount': partner.allowed_invoice_variance_amount,
                    'variance_warning_dismiss_clicks_required': partner.variance_warning_dismiss_clicks_required,
                    'block_invoice_variance_above_allowed': partner.block_invoice_variance_above_allowed,
                    'require_vendor_invoice_final_total': partner.require_vendor_invoice_final_total,
                    'invoice_variance_allocation_mode': partner.invoice_variance_allocation_mode,
                }
                for partner in self
            }
        result = super().write(vals)
        if old_profiles:
            for partner in self:
                _logger.info(
                    '[PNPC_PROFILE] vendor_policy_changed partner_id=%s partner=%s old=%s new=%s user_id=%s',
                    partner.id,
                    partner.display_name,
                    old_profiles.get(partner.id),
                    {
                        'vendor_invoice_profile': partner.vendor_invoice_profile,
                        'allowed_invoice_variance_amount': partner.allowed_invoice_variance_amount,
                        'variance_warning_dismiss_clicks_required': partner.variance_warning_dismiss_clicks_required,
                        'block_invoice_variance_above_allowed': partner.block_invoice_variance_above_allowed,
                        'require_vendor_invoice_final_total': partner.require_vendor_invoice_final_total,
                        'invoice_variance_allocation_mode': partner.invoice_variance_allocation_mode,
                    },
                    self.env.user.id,
                )
        return result
