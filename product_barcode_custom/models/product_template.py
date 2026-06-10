from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    nexx_barcode = fields.Char(
        related='product_variant_ids.nexx_barcode',
        string='Nexx Barcode (Nexx ERP)',
        readonly=False,
        store=False,
    )
