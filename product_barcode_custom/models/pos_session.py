from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def find_product_by_barcode(self, barcode, config_id):
        result = super().find_product_by_barcode(barcode, config_id)
        if result and result.get('product.product'):
            return result

        product_fields = self.env['product.product']._load_pos_data_fields(config_id)
        product_context = {**self.env.context, 'display_default_code': False}
        product = self.env['product.product'].search([
            '|',
            ('barcode', '=', barcode),
            ('nexx_barcode', '=', barcode),
            ('sale_ok', '=', True),
            ('available_in_pos', '=', True),
        ], limit=1)
        if product:
            result['product.product'] = product.with_context(product_context).read(
                product_fields, load=False
            )
        return result
