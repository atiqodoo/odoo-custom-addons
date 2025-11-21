from odoo import models

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def copy(self, default=None):
        self.ensure_one()
        res = super().copy(default=default)
        if self.attribute_line_ids:
            res.attribute_line_ids.unlink()
            res._create_variant_ids()
        return res