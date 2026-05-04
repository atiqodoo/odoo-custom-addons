from odoo import api, fields, models
from odoo.exceptions import UserError

class BarcodeWizard(models.TransientModel):
    _name = 'product.barcode.wizard'
    _description = 'Generate Barcodes Wizard'

    product_ids = fields.Many2many('product.product', string='Products', help='Select products to generate barcodes for. Leave empty to process all products without barcodes.')
    mode = fields.Selection([
        ('selected', 'Selected Products'),
        ('all', 'All Products without Barcodes')
    ], string='Mode', default='selected', required=True)

    def action_generate_barcodes(self):
        """Generate barcodes for selected products or all products without barcodes."""
        from ..services.barcode_service import generate_and_assign_barcode
        products = self.product_ids if self.mode == 'selected' else self.env['product.product'].search([('barcode', '=', False)])
        
        if not products:
            raise UserError("No products to process. Please select products or ensure there are products without barcodes.")

        for product in products:
            generate_and_assign_barcode(product)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Barcodes generated for {len(products)} product(s).',
                'type': 'success',
                'sticky': False,
            }
        }