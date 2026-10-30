from odoo import api, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _get_source_link_records(self):
        sources = super()._get_source_link_records()
        moves = self._get_source_link_pickings().move_ids._filtered_access('read')
        lines = moves.purchase_line_id._filtered_access('read')
        role = self.env._('Purchase Order')
        sources.extend((role, order) for order in lines.order_id)
        return sources

    @api.depends('move_ids.purchase_line_id.order_id')
    def _compute_source_link_data(self):
        return super()._compute_source_link_data()
