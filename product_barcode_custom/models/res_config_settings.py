from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    product_require_category = fields.Boolean(
        string='Require product category',
        config_parameter='product_barcode_custom.require_category',
        help='When enabled, saving a product without a category is blocked.',
    )
    product_require_non_default_category = fields.Boolean(
        string="Disallow default 'All' category",
        config_parameter='product_barcode_custom.require_non_default_category',
        help="When enabled, products must use a specific category — the default 'All' category is rejected.",
    )
