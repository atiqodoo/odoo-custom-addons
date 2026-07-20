# -*- coding: utf-8 -*-
"""Route POS force-delivery through the lot-aware validation path.

The original post-accounting force delivery called stock.picking._action_done()
directly. That is fine for untracked products, but it skips the POS tracked-lot
preassignment added for tinted products. This bridge keeps the existing POS order
flow and makes the final validation use stock.picking.button_validate(), where
temporary/preassigned POS lots are created before negative quants are posted.
"""

import logging

from odoo import models


_logger = logging.getLogger(__name__)
_LOG = "[NegStock][POS_FORCE_LOT_BRIDGE]"


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _force_one_pos_delivery_picking(self, picking):
        self.ensure_one()
        picking.ensure_one()

        tracked_moves = picking.move_ids.filtered(
            lambda move: (
                move.state not in ("done", "cancel")
                and move.product_id.tracking in ("lot", "serial")
            )
        )

        if not tracked_moves:
            return super()._force_one_pos_delivery_picking(picking)

        _logger.info(
            "%s validating via lot-aware path | order=%s picking=%s tracked_moves=%s",
            _LOG,
            self.name,
            picking.name,
            tracked_moves.ids,
        )

        picking.with_context(
            cancel_backorder=True,
            skip_immediate=True,
            skip_backorder=True,
            skip_activity_done=True,
            pos_allow_negative_stock=True,
        ).button_validate()

        self.env.flush_all()
        picking.invalidate_recordset(["state"])

        _logger.info(
            "%s done | order=%s picking=%s final_state=%s",
            _LOG,
            self.name,
            picking.name,
            picking.state,
        )

        self._tag_force_delivery_negative_svls(picking)
        self._post_force_delivery_success_note(picking)
