from odoo import api, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _get_source_link_records(self):
        sources = super()._get_source_link_records()
        pickings = self._get_source_link_pickings()
        moves = pickings.move_ids._filtered_access('read')
        lines = moves.sale_line_id._filtered_access('read')
        orders = pickings.sale_id | lines.order_id
        role = self.env._('Sales Order')
        sources.extend((role, order) for order in orders)
        return sources

    @api.depends('sale_id', 'move_ids.sale_line_id.order_id')
    def _compute_source_link_data(self):
        return super()._compute_source_link_data()
