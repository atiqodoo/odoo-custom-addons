# -*- coding: utf-8 -*-
"""Carry the tinting negative-stock context across the complete MO.

Raw-material moves already receive the bypass from deferred valuation logic.
Finished-product moves are a separate ``stock.move._action_done`` call and may
increase an aggregate-negative product without bringing it back to zero.  This
bridge scopes the same manufacturing context to both sides of a tinting MO.
"""

import logging

from odoo import models


_logger = logging.getLogger(__name__)
_LOG = "[PT][NEGATIVE_MFG_CONTEXT]"


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, cancel_backorder=False):
        if self.env.context.get("pt_allow_negative_manufacturing"):
            return super()._action_done(cancel_backorder=cancel_backorder)

        tinting_moves = self.filtered(
            lambda move: move._pt_is_tinting_manufacturing_move()
        )
        regular_moves = self - tinting_moves

        result = self.env["stock.move"]
        if regular_moves:
            result |= super(StockMove, regular_moves)._action_done(
                cancel_backorder=cancel_backorder,
            )
        if tinting_moves:
            _logger.info(
                "%s enabled | move_ids=%s raw_mo_ids=%s finished_mo_ids=%s",
                _LOG,
                tinting_moves.ids,
                tinting_moves.raw_material_production_id.ids,
                tinting_moves.production_id.ids,
            )
            result |= super(
                StockMove,
                tinting_moves.with_context(pt_allow_negative_manufacturing=True),
            )._action_done(cancel_backorder=cancel_backorder)
        return result

    def _pt_is_tinting_manufacturing_move(self):
        """Identify only raw or finished moves belonging to a tinting MO."""
        self.ensure_one()
        production = self.raw_material_production_id or self.production_id
        if not production or not production.is_tinting_mo:
            return False

        is_raw = (
            bool(self.raw_material_production_id)
            and self.location_id.usage == "internal"
            and self.location_dest_id.usage == "production"
        )
        is_finished = (
            bool(self.production_id)
            and self.location_id.usage == "production"
            and self.location_dest_id.usage == "internal"
        )
        return is_raw or is_finished
