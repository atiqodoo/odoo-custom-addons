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

    def write(self, vals):
        old_profiles = {}
        if 'vendor_invoice_profile' in vals:
            old_profiles = {partner.id: partner.vendor_invoice_profile for partner in self}
        result = super().write(vals)
        if old_profiles:
            for partner in self:
                _logger.info(
                    '[PNPC_PROFILE] mapping_changed partner_id=%s partner=%s old=%s new=%s user_id=%s',
                    partner.id,
                    partner.display_name,
                    old_profiles.get(partner.id),
                    partner.vendor_invoice_profile,
                    self.env.user.id,
                )
        return result
