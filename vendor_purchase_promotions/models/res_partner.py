from odoo import fields, models


VENDOR_PROFILE_GAMMA = 'gamma_paints'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    vendor_invoice_profile = fields.Selection(
        selection_add=[(VENDOR_PROFILE_GAMMA, 'Gamma Paints Invoice')],
        ondelete={VENDOR_PROFILE_GAMMA: 'set default'},
    )

