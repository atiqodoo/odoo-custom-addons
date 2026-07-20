# -*- coding: utf-8 -*-
from odoo import api, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _process_order(self, order, existing_order):
        """
        Remove shadow SO-import lines without discarding legitimate lot splits.

        When the POS frontend loads a quotation, a bug can cause the same
        sale order line to appear once without lot data and again with the
        selected lot data.  In that shape, the no-lot line is only a shadow and
        must be removed.

        A tracked quantity can also legitimately be represented by multiple POS
        lines linked to the same sale.order.line (for example, one line for lot
        0000538 and another for lot 0000539).  Those lot-bearing lines are
        separate physical units and must all be preserved.

        Rules per sale_order_line_id:
        - if any line carries lot data, keep every lot-bearing line and remove
          only the no-lot shadow line(s);
        - if no line carries lot data, retain the original duplicate guard and
          keep the first line only;
        - lines without a sale_order_line_id are never changed.
        """
        order['lines'] = self._deduplicate_sale_order_import_lines(
            order.get('lines', [])
        )
        return super()._process_order(order, existing_order)

    @api.model
    def _deduplicate_sale_order_import_lines(self, lines):
        """Return SO-import commands after removing only proven shadow lines."""
        indexes_by_sol_id = {}

        for index, cmd in enumerate(lines):
            if not (isinstance(cmd, (list, tuple)) and len(cmd) == 3 and cmd[0] == 0):
                continue

            vals = cmd[2]
            sol_id = vals.get('sale_order_line_id')
            if not sol_id:
                continue

            indexes_by_sol_id.setdefault(sol_id, []).append(index)

        indexes_to_remove = set()
        for indexes in indexes_by_sol_id.values():
            if len(indexes) <= 1:
                continue

            lot_indexes = [
                index for index in indexes
                if lines[index][2].get('pack_lot_ids')
            ]
            if lot_indexes:
                indexes_to_remove.update(set(indexes) - set(lot_indexes))
            else:
                indexes_to_remove.update(indexes[1:])

        return [
            cmd for index, cmd in enumerate(lines)
            if index not in indexes_to_remove
        ]
