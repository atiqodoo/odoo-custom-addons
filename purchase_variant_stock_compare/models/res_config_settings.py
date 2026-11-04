from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    variant_compare_limit = fields.Integer(
        string='Stock comparison result limit', default=80,
        config_parameter='purchase_variant_stock_compare.result_limit')

    @api.constrains('variant_compare_limit')
    def _check_variant_compare_limit(self):
        if any(record.variant_compare_limit < 1 for record in self):
            raise ValidationError(_('Stock comparison result limit must be positive.'))
