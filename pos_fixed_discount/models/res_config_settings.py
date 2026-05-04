from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_discount_type = fields.Selection(
        related='pos_config_id.discount_type',
        readonly=False,
    )
