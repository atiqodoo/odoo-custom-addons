from odoo import api, fields, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    x_custom_pos_name = fields.Char(
        string='Custom POS Receipt Name',
        translate=True,
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields = super()._load_pos_data_fields(config_id)
        fields.append('x_custom_pos_name')
        return fields
