from odoo import api, models, fields
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class ProductProduct(models.Model):
    """Inherit product_product model to enforce non-default category selection and generate a barcode."""
    _inherit = 'product.product'
    barcode = fields.Char(index=True)

    @api.model
    def create(self, vals):
        """Generate a barcode during product creation and enforce non-default category selection."""
        from ..services.barcode_service import generate_simple_barcode

        # If categ_id is not in vals, retrieve it from the associated product.template
        categ_id = vals.get('categ_id')
        if not categ_id and vals.get('product_tmpl_id'):
            template = self.env['product.template'].browse(vals['product_tmpl_id'])
            categ_id = template.categ_id.id if template.categ_id else False

        # Validate category
        if not categ_id:
            _logger.warning("No product category provided for product creation: %s", vals)
            raise ValidationError("A specific product category must be selected to create a product.")

        # Check if the selected category is the default 'All' category
        default_category = self.env.ref('product.product_category_all', raise_if_not_found=False)
        default_category_id = default_category.id if default_category else 1
        if categ_id == default_category_id:
            _logger.warning("Default 'All' category (ID %s) selected for product creation", categ_id)
            raise ValidationError("The default 'All' category is not allowed. Please select a specific product category.")

        # Verify that the category exists
        category = self.env['product.category'].browse(categ_id)
        if not category.exists():
            _logger.error("Invalid category ID %s provided for product creation", categ_id)
            raise ValidationError("The selected product category is invalid or does not exist.")

        # Create the product
        res = super(ProductProduct, self).create(vals)

        # Generate and assign barcode
        barcode = generate_simple_barcode(str(res.categ_id.id), str(res.id))
        if self.env['product.product'].search([('barcode', '=', barcode), ('id', '!=', res.id)]):
            _logger.warning("Barcode %s already exists for another product", barcode)
            raise ValidationError("The generated barcode already exists. Please try again.")
        res.write({'barcode': barcode})
        return res

    @api.constrains('categ_id')
    def _check_categ_id(self):
        """Ensure a non-default product category is assigned for all products."""
        default_category = self.env.ref('product.product_category_all', raise_if_not_found=False)
        default_category_id = default_category.id if default_category else 1
        for product in self:
            if not product.categ_id:
                _logger.warning("No category assigned to product ID %s", product.id)
                raise ValidationError("A specific product category must be selected to save the product.")
            if product.categ_id.id == default_category_id:
                _logger.warning("Default 'All' category (ID %s) assigned to product ID %s", default_category_id, product.id)
                raise ValidationError("The default 'All' category is not allowed. Please select a specific product category.")
            if not product.categ_id.exists():
                _logger.error("Invalid category ID %s for product ID %s", product.categ_id.id, product.id)
                raise ValidationError("The selected product category is invalid or does not exist.")