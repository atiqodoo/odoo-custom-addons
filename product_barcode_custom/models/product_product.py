from odoo import api, models, fields
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    barcode = fields.Char(index=True)
    nexx_barcode = fields.Char(
        'Nexx Barcode (Nexx ERP)',
        index=True,
        store=True,
        copy=False,
        help="Secondary barcode from the Nexx ERP system. Scanned by POS alongside the primary barcode.",
    )

    _sql_constraints = [
        (
            'nexx_barcode_uniq',
            'unique(nexx_barcode)',
            'The Nexx barcode must be unique across all product variants.',
        ),
    ]

    def _get_category_validation_settings(self):
        ICP = self.env['ir.config_parameter'].sudo()
        require_category = ICP.get_param('product_barcode_custom.require_category') == 'True'
        require_non_default = ICP.get_param('product_barcode_custom.require_non_default_category') == 'True'
        return require_category, require_non_default

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields = super()._load_pos_data_fields(config_id)
        if 'nexx_barcode' not in fields:
            fields.append('nexx_barcode')
        return fields

    @api.model
    def create(self, vals):
        from ..services.barcode_service import generate_simple_barcode

        require_category, require_non_default = self._get_category_validation_settings()

        categ_id = vals.get('categ_id')
        if not categ_id and vals.get('product_tmpl_id'):
            template = self.env['product.template'].browse(vals['product_tmpl_id'])
            categ_id = template.categ_id.id if template.categ_id else False

        if require_category and not categ_id:
            raise ValidationError("A specific product category must be selected to create a product.")

        if require_non_default and categ_id:
            default_category = self.env.ref('product.product_category_all', raise_if_not_found=False)
            default_category_id = default_category.id if default_category else 1
            if categ_id == default_category_id:
                raise ValidationError(
                    "The default 'All' category is not allowed. Please select a specific product category."
                )

        if categ_id:
            category = self.env['product.category'].browse(categ_id)
            if not category.exists():
                raise ValidationError("The selected product category is invalid or does not exist.")

        res = super(ProductProduct, self).create(vals)

        barcode = generate_simple_barcode(str(res.categ_id.id), str(res.id))
        if self.env['product.product'].search([('barcode', '=', barcode), ('id', '!=', res.id)]):
            raise ValidationError("The generated barcode already exists. Please try again.")
        res.write({'barcode': barcode})
        return res

    @api.constrains('categ_id')
    def _check_categ_id(self):
        require_category, require_non_default = self._get_category_validation_settings()
        if not require_category and not require_non_default:
            return

        default_category = self.env.ref('product.product_category_all', raise_if_not_found=False)
        default_category_id = default_category.id if default_category else 1

        for product in self:
            if require_category and not product.categ_id:
                raise ValidationError("A specific product category must be selected to save the product.")
            if require_non_default and product.categ_id and product.categ_id.id == default_category_id:
                raise ValidationError(
                    "The default 'All' category is not allowed. Please select a specific product category."
                )
