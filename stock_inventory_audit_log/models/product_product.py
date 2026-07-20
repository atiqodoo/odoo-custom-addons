from odoo import models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _get_stock_audit_barcode_values(self):
        self.ensure_one()
        return {
            'barcode': self.barcode or False,
            'nexx_barcode': self.nexx_barcode if 'nexx_barcode' in self._fields else False,
        }
