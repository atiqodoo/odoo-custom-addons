from odoo import fields, models, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    price_check_bill_count = fields.Integer(
        string='Number of Bills to Check',
        config_parameter='vendor_price_check.price_check_bill_count',
        default=3,
        help='Number of previous vendor bills to check for product price comparison.'
    )
    price_check_approver_id = fields.Many2one(
        'res.users',
        string='Price Discrepancy Approver',
        help='User who must approve bills with price discrepancies.'
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        params = self.env['ir.config_parameter'].sudo()
        approver_id = params.get_param('vendor_price_check.price_check_approver_id', default=False)
        res.update(
            price_check_approver_id=int(approver_id) if approver_id else False,
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('vendor_price_check.price_check_approver_id', 
                        self.price_check_approver_id.id if self.price_check_approver_id else False)