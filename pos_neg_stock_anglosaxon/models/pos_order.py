# -*- coding: utf-8 -*-
"""pos_order.py

Extends pos.order._create_order_picking to tag freshly created negative SVLs
with pos_negative_origin=True immediately after the POS fields (pos_order_id,
pos_session_id, origin) are written to the picking.

Why this is necessary
---------------------
Odoo's POS module creates the picking and calls _action_done() BEFORE writing
pos_order_id / pos_session_id to the picking record.  At that moment our
stock_picking._action_done() hook cannot detect the picking as POS-linked
(all three strategies in _is_pos_picking() fail) so the negative SVLs are left
untagged.

By hooking _create_order_picking() AFTER super() we are guaranteed that
pos_order_id has already been written, so self.picking_ids includes the new
pickings and we can match their move SVLs.
"""

import logging
from odoo import models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_order_picking(self):
        """Hook: tag negative SVLs after POS fields are written to the picking.

        Odoo calls _create_picking_from_pos_order_lines which internally calls
        _action_done() **before** pos_order_id is written.  After super() here
        the write has happened and self.picking_ids reflects the new records.
        """
        super()._create_order_picking()
        self._tag_neg_svls_on_order_pickings()

    def _tag_neg_svls_on_order_pickings(self):
        """Find untagged negative SVLs on this order's outgoing pickings and mark them.

        Called immediately after _create_order_picking() so that the FIFO
        reconciliation logic can later locate these layers via
        stock.valuation.layer._get_open_negative_layers().
        """
        self.ensure_one()
        outgoing = self.picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing'
        )
        if not outgoing:
            return

        move_ids = outgoing.move_ids.ids
        if not move_ids:
            return

        neg_svls = self.env['stock.valuation.layer'].search([
            ('stock_move_id', 'in', move_ids),
            ('quantity', '<', 0),
            ('pos_negative_origin', '=', False),
        ])
        if not neg_svls:
            _logger.debug(
                '[NegStock] _tag_neg_svls_on_order_pickings: no untagged negative SVLs '
                'for POS order %s', self.name,
            )
            return

        for svl in neg_svls:
            svl.write({
                'pos_negative_origin': True,
                'pos_order_id': self.id,
            })
            _logger.info(
                '[NegStock] Tagged SVL id=%d | product="%s" | qty=%.4f | '
                'unit_cost=%.6f | pos_order=%s',
                svl.id,
                svl.product_id.display_name,
                svl.quantity,
                svl.unit_cost,
                self.name,
            )
            self.message_post(
                body=(
                    '<b>[Negative Stock Created]</b><br/>'
                    f'Product: {svl.product_id.display_name}<br/>'
                    f'Qty oversold: {abs(svl.quantity):.2f}<br/>'
                    f'AVCO at sale: {svl.unit_cost:.4f}<br/>'
                    f'Exposure value: {abs(svl.value):.4f}<br/>'
                    f'SVL reference: #{svl.id}'
                )
            )
