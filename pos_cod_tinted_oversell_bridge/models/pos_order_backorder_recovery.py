# -*- coding: utf-8 -*-
"""Recover COD tinted oversell backorders after COD sync completes.

COD validates its dispatch picking through ``_action_done`` while the order can
still be in the draft creation window. If Odoo splits a tinted tracked product
into a child backorder during that window, the child can miss POS metadata and
therefore miss the existing POS lot-preassignment force-delivery path.

This file is deliberately additive: it does not change COD dispatch,
accounting, stock valuation, or the existing POS lot allocator. It only links
eligible COD child backorders and hands them to the established force-delivery
method already provided by ``pos_neg_stock_anglosaxon``.
"""

import logging

from odoo import api, models, tools


_logger = logging.getLogger(__name__)
_LOG = "[COD_TINT_BACKORDER_RECOVERY]"


class PosOrder(models.Model):
    _inherit = "pos.order"

    @api.model
    def sync_from_ui(self, orders):
        cod_inputs = self._cod_tinted_recovery_input_summary(orders)
        result = super().sync_from_ui(orders)

        if not cod_inputs:
            return result

        order_ids = self._cod_tinted_recovery_result_order_ids(result)
        orders_to_recover = self.browse(order_ids).exists().filtered("is_cod")
        _logger.warning(
            "%s sync_after_super | input_cod=%s result_order_ids=%s "
            "cod_result_orders=%s result_keys=%s",
            _LOG,
            cod_inputs,
            order_ids,
            orders_to_recover.mapped(lambda order: (order.id, order.name, order.state)),
            sorted(result.keys()) if isinstance(result, dict) else type(result).__name__,
        )

        for order in orders_to_recover:
            try:
                with self.env.cr.savepoint():
                    order._cod_tinted_recover_backorders_after_sync()
            except Exception as exc:
                _logger.error(
                    "%s recovery_failed_non_blocking | order=%s id=%s "
                    "state=%s cod_state=%s error=%s",
                    _LOG,
                    order.name,
                    order.id,
                    order.state,
                    order.cod_state,
                    tools.exception_to_unicode(exc),
                    exc_info=True,
                )

        return result

    @api.model
    def _cod_tinted_recovery_input_summary(self, orders):
        """Return compact details for COD orders present in the UI payload."""
        summary = []
        for index, order_data in enumerate(orders or []):
            if not order_data.get("is_cod"):
                continue
            summary.append(
                {
                    "index": index,
                    "name": order_data.get("name"),
                    "uuid": order_data.get("uuid"),
                    "partner_id": order_data.get("partner_id"),
                    "lines": len(order_data.get("lines") or []),
                    "state": order_data.get("state"),
                }
            )
        return summary

    @api.model
    def _cod_tinted_recovery_result_order_ids(self, result):
        """Extract ``pos.order`` ids from the normal POS sync result shape."""
        order_ids = []
        if not isinstance(result, dict):
            _logger.warning(
                "%s result_unexpected_type | result_type=%s",
                _LOG,
                type(result).__name__,
            )
            return order_ids

        for record in result.get("pos.order", []) or []:
            if isinstance(record, dict):
                record_id = record.get("id")
            else:
                record_id = record
            if record_id:
                order_ids.append(int(record_id))
        return order_ids

    def _cod_tinted_recover_backorders_after_sync(self):
        """Link eligible COD child backorders and reuse POS force delivery."""
        self.ensure_one()
        if not self.is_cod:
            _logger.debug(
                "%s skipped_not_cod | order=%s id=%s",
                _LOG,
                self.name,
                self.id,
            )
            return

        descendants = self._cod_tinted_backorder_descendants()
        recoverable = self.env["stock.picking"]
        skipped = []

        for picking in descendants:
            reason = self._cod_tinted_backorder_skip_reason(picking)
            if reason:
                skipped.append((picking.name, picking.id, reason))
                continue
            recoverable |= picking

        _logger.warning(
            "%s scan | order=%s id=%s state=%s cod_state=%s "
            "direct_pickings=%s descendants=%s recoverable=%s skipped=%s",
            _LOG,
            self.name,
            self.id,
            self.state,
            self.cod_state,
            self.picking_ids.mapped(lambda p: (p.name, p.id, p.state)),
            descendants.mapped(lambda p: (p.name, p.id, p.state, p.backorder_id.name)),
            recoverable.mapped(lambda p: (p.name, p.id, p.state)),
            skipped,
        )

        for picking in recoverable:
            self._cod_tinted_link_backorder(picking)
            self._cod_tinted_force_recovered_backorder(picking)

    def _cod_tinted_backorder_descendants(self):
        """Return all child backorders below this COD order's direct pickings."""
        self.ensure_one()
        Picking = self.env["stock.picking"]
        frontier = self.picking_ids
        descendants = Picking
        visited_ids = set(frontier.ids)

        while frontier:
            children = Picking.search(
                [("backorder_id", "in", frontier.ids)],
                order="id asc",
            ).filtered(lambda picking: picking.id not in visited_ids)
            if not children:
                break
            descendants |= children
            visited_ids.update(children.ids)
            frontier = children

        return descendants

    def _cod_tinted_backorder_skip_reason(self, picking):
        """Keep recovery narrow to COD child backorders with tinted lot debt."""
        self.ensure_one()
        picking.ensure_one()

        if picking.picking_type_code != "outgoing":
            return "not_outgoing"
        if picking.state in ("done", "cancel"):
            return "already_done_or_cancelled"
        if picking.company_id != self.company_id:
            return "company_mismatch"
        if picking.pos_order_id and picking.pos_order_id != self:
            return "foreign_pos_order"
        if picking.pos_session_id and picking.pos_session_id != self.session_id:
            return "foreign_pos_session"
        if not picking.backorder_id:
            return "not_child_backorder"
        if not self._cod_tinted_has_tracked_shortfall(picking):
            return "no_tinted_tracked_lot_shortfall"
        return False

    def _cod_tinted_has_tracked_shortfall(self, picking):
        """Use the bridge shortfall detector when available."""
        picking.ensure_one()
        if hasattr(picking, "_cod_tinted_moves_missing_lot_quantity"):
            return bool(picking._cod_tinted_moves_missing_lot_quantity())
        return bool(
            picking.move_ids.filtered(
                lambda move: (
                    move.state not in ("done", "cancel")
                    and move.product_id.tracking in ("lot", "serial")
                    and bool(getattr(move.product_id, "is_tinted_product", False))
                )
            )
        )

    def _cod_tinted_link_backorder(self, picking):
        """Write only missing POS identity fields on a recovered COD child."""
        self.ensure_one()
        picking.ensure_one()
        values = {}

        if not picking.pos_order_id:
            values["pos_order_id"] = self.id
        if not picking.pos_session_id:
            values["pos_session_id"] = self.session_id.id
        if not picking.origin:
            values["origin"] = self.name

        if not values:
            _logger.info(
                "%s link_not_needed | order=%s id=%s picking=%s id=%s",
                _LOG,
                self.name,
                self.id,
                picking.name,
                picking.id,
            )
            return

        picking.write(values)
        _logger.warning(
            "%s linked | order=%s id=%s picking=%s id=%s parent=%s "
            "fields=%s state=%s",
            _LOG,
            self.name,
            self.id,
            picking.name,
            picking.id,
            picking.backorder_id.name,
            sorted(values),
            picking.state,
        )

    def _cod_tinted_force_recovered_backorder(self, picking):
        """Hand the linked child to the existing POS force-delivery service."""
        self.ensure_one()
        picking.ensure_one()
        before = {
            "state": picking.state,
            "moves": picking.move_ids.mapped(
                lambda move: (
                    move.id,
                    move.product_id.display_name,
                    move.state,
                    move.product_uom_qty,
                    move.quantity,
                    move.product_id.tracking,
                )
            ),
            "lots": picking.move_line_ids.mapped(
                lambda line: (
                    line.id,
                    line.product_id.display_name,
                    line.lot_id.name,
                    line.quantity,
                    line.picked,
                )
            ),
        }
        _logger.warning(
            "%s force_start | order=%s id=%s picking=%s id=%s snapshot=%s",
            _LOG,
            self.name,
            self.id,
            picking.name,
            picking.id,
            before,
        )

        self._force_one_pos_delivery_picking(picking)
        picking.invalidate_recordset(["state"])

        after = {
            "state": picking.state,
            "lots": picking.move_line_ids.mapped(
                lambda line: (
                    line.id,
                    line.product_id.display_name,
                    line.lot_id.name,
                    line.quantity,
                    line.picked,
                )
            ),
        }
        _logger.warning(
            "%s force_done | order=%s id=%s picking=%s id=%s snapshot=%s",
            _LOG,
            self.name,
            self.id,
            picking.name,
            picking.id,
            after,
        )
