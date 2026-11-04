import logging

from odoo import models
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)


class PurchaseOverdueSupply(models.AbstractModel):
    _name = 'purchase.overdue.supply'
    _description = 'Outstanding supplier receipts and replacement shortage'

    def _candidate_domain(self, orderpoints):
        return [
            ('company_id', 'in', orderpoints.company_id.ids),
            ('product_id', 'in', orderpoints.product_id.ids),
            ('purchase_line_id', '!=', False),
            ('purchase_line_id.order_id.state', 'in', ['purchase', 'done']),
            ('location_id.usage', '=', 'supplier'),
            ('state', 'not in', ['draft', 'cancel', 'done']),
            ('product_uom_qty', '>', 0),
        ]

    def _moves_by_rule(self, orderpoints, now):
        """One candidate query, with prefetch and shared location ancestry checks.

        Only supplier legs are included, so chained internal moves do not double-count
        the same shipment. Final locations handle two/three-step receipts.
        """
        moves = self.env['stock.move'].search(self._candidate_domain(orderpoints) + [('date', '<', now)])
        policy = self.env['purchase.receiving.calendar']
        destination_ids = (moves.location_final_id | moves.location_dest_id).ids
        descendants = {
            location.id: set(self.env['stock.location'].search([
                ('id', 'in', destination_ids), ('id', 'child_of', location.id),
            ]).ids) for location in orderpoints.location_id
        }
        by_key = {}
        overdue_cache = {}
        for move in moves:
            key = (move.company_id.id, move.product_id.id)
            by_key.setdefault(key, self.env['stock.move'])
            date_key = (move.company_id.id, move.date)
            if date_key not in overdue_cache:
                overdue_cache[date_key] = policy._is_overdue(move.company_id, move.date, now)
            if overdue_cache[date_key]:
                by_key[key] |= move
        return {
            op.id: by_key.get((op.company_id.id, op.product_id.id), self.env['stock.move']).filtered(
                lambda move: (move.location_final_id or move.location_dest_id).id in descendants[op.location_id.id])
            for op in orderpoints
        }

    def _replacement_snapshot(self, orderpoint, overdue_moves):
        return self._replacement_snapshots(orderpoint, {orderpoint.id: overdue_moves})[orderpoint.id]

    def _replacement_snapshots(self, orderpoints, moves_by_rule):
        """Conservative shortage: retain every other outstanding receipt and RFQ.

        The full location forecast deliberately includes later supply as well. Only
        the overdue supplier quantities under review are removed for this decision;
        standard Odoo forecasting is never changed.
        """
        grouped = {}
        for op in orderpoints:
            grouped.setdefault((op.company_id, op.location_id), self.env['stock.warehouse.orderpoint'])
            grouped[(op.company_id, op.location_id)] |= op
        snapshots = {}
        for (company, location), rules in grouped.items():
            rules = rules.with_company(company).with_context(allowed_company_ids=[company.id])
            products = rules.product_id.with_context(
                location=location.id, warehouse=False, warehouse_id=False, from_date=False, to_date=False,
                lot_id=False, owner_id=False, package_id=False)
            products.invalidate_recordset(['virtual_available'])
            forecasts = {item['id']: item['virtual_available'] for item in products.read(['virtual_available'])}
            # Purchase-specific contract: the orderpoint hook also inspects draft
            # manufacturing orders, requiring unrelated manufacturing permissions.
            # Confirmed manufacturing receipts already appear in the stock forecast.
            drafts, unused_by_warehouse = products._get_quantity_in_progress(location_ids=location.ids)
            for op in rules:
                overdue_qty = sum(moves_by_rule[op.id].mapped('product_qty'))
                forecast = forecasts[op.product_id.id] + drafts.get((op.product_id.id, location.id), 0)
                reliable_forecast = forecast - overdue_qty
                qty = 0.0
                if float_compare(reliable_forecast, op.product_min_qty,
                                 precision_rounding=op.product_uom.rounding) < 0:
                    qty = max(0, op.product_max_qty - reliable_forecast)
                snapshots[op.id] = {'overdue_qty': overdue_qty, 'forecast_qty': forecast,
                    'reliable_forecast_qty': reliable_forecast, 'suggested_qty': qty}
        return snapshots
