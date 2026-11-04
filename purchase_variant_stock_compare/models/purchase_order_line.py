from odoo import _, models
from odoo.exceptions import UserError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def action_compare_similar_stock(self):
        self.ensure_one()
        self.check_access('read')
        if not self.product_id or self.display_type or self.order_id.state not in ('draft', 'sent'):
            raise UserError(_('Select a product line on a draft or sent RFQ.'))
        return self.env['purchase.variant.stock.compare']._open_for_line(self)
