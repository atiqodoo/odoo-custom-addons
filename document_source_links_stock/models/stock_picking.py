from odoo import api, models


class StockPicking(models.Model):
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'document.source.link.mixin']

    def _get_source_link_pickings(self):
        """Walk upstream transfers without loops, privilege elevation or name matching."""
        self.ensure_one()
        visited = self.env['stock.picking']
        pending = self
        while pending:
            current = pending - visited
            current = current._filtered_access('read').filtered(self._source_link_same_company)
            if not current:
                break
            visited |= current
            moves = current.move_ids._filtered_access('read')
            upstream_moves = moves.move_orig_ids._filtered_access('read')
            pending = (current.return_id | current.backorder_id |
                       upstream_moves.picking_id) - visited
        return visited

    def _get_source_link_records(self):
        sources = super()._get_source_link_records()
        role = self.env._('Source Transfer')
        sources.extend((role, picking)
                       for picking in self._get_source_link_pickings() - self)
        return sources

    @api.depends('origin', 'return_id', 'backorder_id', 'move_ids',
                 'move_ids.move_orig_ids.picking_id')
    def _compute_source_link_data(self):
        return super()._compute_source_link_data()
