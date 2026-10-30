from odoo import api, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _get_source_link_records(self):
        sources = super()._get_source_link_records()
        orders = self._get_source_link_pickings().pos_order_id
        role = self.env._('POS Order')
        sources.extend((role, order) for order in orders)
        return sources

    @api.depends('pos_order_id')
    def _compute_source_link_data(self):
        return super()._compute_source_link_data()
