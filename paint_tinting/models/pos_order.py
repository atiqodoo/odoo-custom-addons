# -*- coding: utf-8 -*-
from odoo import api, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _process_order(self, order, existing_order):
        """
        Deduplicate POS order lines that share the same sale_order_line_id.

        When the POS frontend loads a quotation, a bug can cause the same
        sale order line to be added to the cart multiple times (same
        sale_order_line_id, same product, same qty). This guard collapses
        those duplicates into one line server-side before any further
        processing occurs. Lines without a sale_order_line_id are kept as-is.
        If one of the duplicates carries lot data (pack_lot_ids) while others
        don't, the one with lots is preferred.
        """
        lines = order.get('lines', [])
        seen_sol_ids = {}
        deduped = []

        for cmd in lines:
            if not (isinstance(cmd, (list, tuple)) and len(cmd) == 3 and cmd[0] == 0):
                deduped.append(cmd)
                continue

            vals = cmd[2]
            sol_id = vals.get('sale_order_line_id')
            if not sol_id:
                deduped.append(cmd)
                continue

            if sol_id not in seen_sol_ids:
                seen_sol_ids[sol_id] = len(deduped)
                deduped.append(cmd)
            else:
                # Prefer the entry that has lot information
                existing_idx = seen_sol_ids[sol_id]
                existing_vals = deduped[existing_idx][2]
                if vals.get('pack_lot_ids') and not existing_vals.get('pack_lot_ids'):
                    deduped[existing_idx] = cmd

        order['lines'] = deduped
        return super()._process_order(order, existing_order)
