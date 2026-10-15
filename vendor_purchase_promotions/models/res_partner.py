from odoo import fields, models


VENDOR_PROFILE_GAMMA = 'gamma_paints'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    vendor_promotion_profile_id = fields.Many2one(
        'vendor.promotion.profile',
        string='Vendor Promotion Profile',
        help='Configures promotion grouping, tiering, substitutions, and alerts for this vendor.',
    )
    vendor_invoice_profile = fields.Selection(
        selection_add=[(VENDOR_PROFILE_GAMMA, 'Gamma Paints Invoice')],
        ondelete={VENDOR_PROFILE_GAMMA: 'set default'},
    )
