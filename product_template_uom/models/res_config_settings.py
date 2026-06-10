from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    product_require_uom = fields.Boolean(
        string='Require Unit of Measure on products',
        config_parameter='product_template_uom.require_uom',
        help=(
            'When enabled, saving a product without an explicitly selected Unit of Measure is blocked. '
            'When disabled, products may be saved with the system default UoM.'
        ),
    )
