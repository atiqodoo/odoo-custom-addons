from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    discount_type = fields.Selection(
        [('percentage', 'Percentage'), ('fixed', 'Fixed Amount')],
        string='Discount Type',
        default='percentage',
        help='Determines whether the Global Discount button applies a percentage or a fixed amount.',
    )
