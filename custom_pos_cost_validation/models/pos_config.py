from odoo import models, fields

class PosConfig(models.Model):
    _inherit = 'pos.config'
    
    block_below_cost = fields.Boolean(
        string='Block Sales Below Cost',
        default=True,
        help='Prevent cashiers from selling products below their AVCO cost price (VAT inclusive)'
    )


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    block_below_cost = fields.Boolean(
        related='pos_config_id.block_below_cost',
        readonly=False,
        string='Block Sales Below Cost Price'
    )
    
class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_product_product(self):
        params = super()._loader_params_product_product()
        # Add standard_price to the fields loaded for products
        params['search_params']['fields'].append('standard_price')
        return params