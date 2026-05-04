import logging

_logger = logging.getLogger(__name__)

def generate_simple_barcode(category_id, product_id):
    """Generate a barcode by concatenating category ID and product ID without padding."""
    if not category_id or not product_id:
        _logger.warning("Missing category_id (%s) or product_id (%s) for barcode generation", category_id, product_id)
        return '0'
    try:
        int(category_id)
        int(product_id)
        return f'{category_id}{product_id}'
    except ValueError:
        _logger.error("Non-numeric category_id (%s) or product_id (%s)", category_id, product_id)
        return '0'

def generate_and_assign_barcode(product):
    """Generate and assign a unique barcode to a product."""
    from odoo.exceptions import ValidationError
    barcode = generate_simple_barcode(str(product.categ_id.id), str(product.id))
    if product.env['product.product'].search([('barcode', '=', barcode), ('id', '!=', product.id)]):
        _logger.warning("Barcode %s already exists for another product", barcode)
        raise ValidationError("The generated barcode already exists for another product.")
    product.write({'barcode': barcode})