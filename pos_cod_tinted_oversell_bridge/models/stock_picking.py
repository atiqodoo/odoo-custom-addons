# -*- coding: utf-8 -*-
"""Compatibility bridge between COD dispatch and POS tinted-lot overselling.

COD deliberately completes its dispatch picking through ``_action_done`` with
``cod_dispatch=True``.  The standard POS negative-stock path normally reaches
the existing lot-preassignment service through ``button_validate``.  This
module joins those two paths without replacing either implementation.
"""

import logging

from odoo import models
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)
_LOG = "[COD_TINT_OVERSELL_BRIDGE]"


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        """Prepare missing tinted lots immediately before a COD dispatch."""
        bridge_enabled = bool(self.env.context.get("cod_dispatch"))
        if bridge_enabled:
            _logger.warning(
                "%s action_done_enter | picking_ids=%s cod_dispatch=true "
                "cancel_backorder=%s",
                _LOG,
                self.ids,
                self.env.context.get("cancel_backorder"),
            )
            try:
                self._cod_prepare_missing_tinted_oversell_lots()
            except Exception:
                _logger.exception(
                    "%s preassignment_failed | picking_ids=%s context_keys=%s",
                    _LOG,
                    self.ids,
                    sorted(self.env.context.keys()),
                )
                raise
        else:
            _logger.debug(
                "%s skipped | picking_ids=%s reason=not_cod_dispatch",
                _LOG,
                self.ids,
            )

        result = super()._action_done()

        if bridge_enabled:
            _logger.warning(
                "%s action_done_exit | picking_ids=%s states=%s result_type=%s",
                _LOG,
                self.ids,
                {picking.id: picking.state for picking in self},
                type(result).__name__,
            )
        return result

    def _cod_prepare_missing_tinted_oversell_lots(self):
        """Run the existing POS lot allocator for eligible COD pickings only."""
        for picking in self:
            details = picking._cod_tinted_oversell_debug_details()

            if picking.picking_type_code != "outgoing":
                _logger.info(
                    "%s skipped | picking=%s id=%s reason=not_outgoing details=%s",
                    _LOG,
                    picking.name,
                    picking.id,
                    details,
                )
                continue

            if not picking._is_pos_picking():
                _logger.warning(
                    "%s skipped | picking=%s id=%s reason=not_pos_linked "
                    "origin=%s details=%s",
                    _LOG,
                    picking.name,
                    picking.id,
                    picking.origin,
                    details,
                )
                continue

            missing_moves = picking._cod_tinted_moves_missing_lot_quantity()
            if not missing_moves:
                _logger.info(
                    "%s skipped | picking=%s id=%s reason=no_tinted_lot_shortfall "
                    "details=%s",
                    _LOG,
                    picking.name,
                    picking.id,
                    details,
                )
                continue

            order = picking._get_linked_pos_order()
            _logger.warning(
                "%s preassignment_start | picking=%s id=%s order=%s order_id=%s "
                "missing_move_ids=%s details=%s",
                _LOG,
                picking.name,
                picking.id,
                order.name if order else "N/A",
                order.id if order else False,
                missing_moves.ids,
                details,
            )

            # Reuse the established normal-POS allocator.  Its existing lot
            # selection and temporary POS-lot policies intentionally remain
            # unchanged by this compatibility module.
            picking._preassign_missing_pos_tracked_lots()

            remaining = picking._cod_tinted_moves_missing_lot_quantity()
            result_details = picking._cod_tinted_oversell_debug_details()
            if remaining:
                _logger.error(
                    "%s preassignment_incomplete | picking=%s id=%s "
                    "remaining_move_ids=%s details=%s",
                    _LOG,
                    picking.name,
                    picking.id,
                    remaining.ids,
                    result_details,
                )
            else:
                _logger.warning(
                    "%s preassignment_complete | picking=%s id=%s details=%s",
                    _LOG,
                    picking.name,
                    picking.id,
                    result_details,
                )

    def _cod_tinted_moves_missing_lot_quantity(self):
        """Return active tinted tracked moves whose lot allocation is short."""
        self.ensure_one()
        return self.move_ids.filtered(
            lambda move: (
                move.state not in ("done", "cancel")
                and move.product_id.tracking in ("lot", "serial")
                and bool(getattr(move.product_id, "is_tinted_product", False))
                and self._cod_move_has_lot_shortfall(move)
            )
        )

    def _cod_move_has_lot_shortfall(self, move):
        """Compare demand with quantities carried by concrete ``lot_id`` rows."""
        product = move.product_id
        rounding = product.uom_id.rounding
        demand = move.product_uom._compute_quantity(
            move.product_uom_qty,
            product.uom_id,
            rounding_method="HALF-UP",
        )
        allocated = sum(
            line.product_uom_id._compute_quantity(
                line.quantity,
                product.uom_id,
                rounding_method="HALF-UP",
            )
            for line in move.move_line_ids.filtered(lambda line: line.lot_id)
        )
        return float_compare(allocated, demand, precision_rounding=rounding) < 0

    def _cod_tinted_oversell_debug_details(self):
        """Build a compact, non-sensitive snapshot for operational diagnosis."""
        self.ensure_one()
        move_details = []
        for move in self.move_ids.filtered(lambda rec: rec.state not in ("done", "cancel")):
            lot_lines = move.move_line_ids.filtered(lambda line: line.lot_id)
            move_details.append(
                {
                    "move_id": move.id,
                    "product_id": move.product_id.id,
                    "product": move.product_id.display_name,
                    "tracking": move.product_id.tracking,
                    "is_tinted": bool(
                        getattr(move.product_id, "is_tinted_product", False)
                    ),
                    "demand": move.product_uom_qty,
                    "move_line_count": len(move.move_line_ids),
                    "lot_line_count": len(lot_lines),
                    "lots": lot_lines.mapped("lot_id.name"),
                }
            )
        return {
            "state": self.state,
            "operation": self.picking_type_code,
            "origin": self.origin,
            "moves": move_details,
        }
