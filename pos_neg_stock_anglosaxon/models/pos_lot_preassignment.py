# -*- coding: utf-8 -*-
"""Preassign lots for POS force-delivered tracked products.

POS negative-stock validation can force quantities, but Odoo still requires a
lot/serial on every done move line for tracked products. This extension assigns
existing available lots first and creates preassigned POS lots for any shortfall.
Those preassigned lots are later reused by paint tinting production.
"""

import logging
import re

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero


_logger = logging.getLogger(__name__)
_LOG = "[NegStock][POS_LOT_PREASSIGN]"


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _force_pos_quantities(self):
        result = super()._force_pos_quantities()
        for picking in self:
            if picking.picking_type_code == "outgoing" and picking._is_pos_picking():
                picking._preassign_missing_pos_tracked_lots()
        return result

    def _preassign_missing_pos_tracked_lots(self):
        self.ensure_one()
        pos_order = self._get_linked_pos_order()
        moves = self.move_ids.filtered(
            lambda move: (
                move.state not in ("done", "cancel")
                and move.product_id.tracking in ("lot", "serial")
                and move.product_uom_qty
            )
        )
        if not moves:
            return

        _logger.info(
            "%s start | picking=%s id=%s order=%s tracked_moves=%s",
            _LOG,
            self.name,
            self.id,
            pos_order.name if pos_order else "N/A",
            moves.ids,
        )
        for move in moves:
            self._preassign_missing_lots_for_move(move, pos_order)

    def _preassign_missing_lots_for_move(self, move, pos_order=False):
        self.ensure_one()
        product = move.product_id
        rounding = product.uom_id.rounding
        demand_product_uom = move.product_uom._compute_quantity(
            move.product_uom_qty,
            product.uom_id,
            rounding_method="HALF-UP",
        )
        if float_is_zero(demand_product_uom, precision_rounding=rounding):
            return

        allocations = []
        remaining_qty = demand_product_uom
        for lot, qty_product_uom in self._get_existing_move_lot_allocations(move):
            if float_compare(remaining_qty, 0.0, precision_rounding=rounding) <= 0:
                break
            take_qty = min(remaining_qty, qty_product_uom)
            if float_compare(take_qty, 0.0, precision_rounding=rounding) <= 0:
                continue
            allocations.append((lot, take_qty))
            remaining_qty -= take_qty

        if float_compare(remaining_qty, 0.0, precision_rounding=rounding) > 0:
            allocations += self._get_pos_lot_allocations(move, remaining_qty, pos_order)

        move.move_line_ids.unlink()

        for lot, qty_product_uom in allocations:
            qty_move_uom = product.uom_id._compute_quantity(
                qty_product_uom,
                move.product_uom,
                rounding_method="HALF-UP",
            )
            vals = {
                "move_id": move.id,
                "picking_id": self.id,
                "company_id": move.company_id.id,
                "product_id": product.id,
                "product_uom_id": move.product_uom.id,
                "location_id": move.location_id.id,
                "location_dest_id": move.location_dest_id.id,
                "lot_id": lot.id,
                "quantity": qty_move_uom,
                "picked": True,
            }
            self.env["stock.move.line"].create(vals)

            _logger.info(
                "%s assigned | picking=%s move=%s product=%s lot=%s qty=%.4f",
                _LOG,
                self.name,
                move.id,
                product.display_name,
                lot.name,
                qty_product_uom,
            )

    def _get_existing_move_lot_allocations(self, move):
        product = move.product_id
        for line in move.move_line_ids.filtered(lambda rec: rec.lot_id):
            qty_product_uom = line.product_uom_id._compute_quantity(
                line.quantity,
                product.uom_id,
                rounding_method="HALF-UP",
            )
            if float_compare(qty_product_uom, 0.0, precision_rounding=product.uom_id.rounding) > 0:
                yield line.lot_id, qty_product_uom

    def _get_pos_lot_allocations(self, move, missing_qty, pos_order=False):
        self.ensure_one()
        product = move.product_id
        rounding = product.uom_id.rounding
        remaining = missing_qty
        allocations = []

        for lot, available_qty in self._iter_available_lots_for_move(move):
            if float_compare(remaining, 0.0, precision_rounding=rounding) <= 0:
                break
            take_qty = min(remaining, available_qty)
            if float_compare(take_qty, 0.0, precision_rounding=rounding) <= 0:
                continue
            allocations.append((lot, take_qty))
            remaining -= take_qty

        while float_compare(remaining, 0.0, precision_rounding=rounding) > 0:
            lot_qty = self._get_next_preassigned_lot_qty(product, remaining)
            lot = self._create_pos_preassigned_lot(move, pos_order)
            allocations.append((lot, lot_qty))
            remaining -= lot_qty

        return allocations

    def _iter_available_lots_for_move(self, move):
        product = move.product_id
        Quant = self.env["stock.quant"]
        domain = [
            ("product_id", "=", product.id),
            ("location_id", "child_of", move.location_id.id),
            ("lot_id", "!=", False),
            ("quantity", ">", 0),
        ]
        for quant in Quant.search(domain, order="in_date asc, id asc"):
            available_qty = quant.quantity - quant.reserved_quantity
            if float_compare(available_qty, 0.0, precision_rounding=product.uom_id.rounding) > 0:
                yield quant.lot_id, available_qty

    def _get_next_preassigned_lot_qty(self, product, remaining):
        if product.tracking == "serial":
            return min(1.0, remaining)
        nearest_unit = round(remaining)
        if abs(remaining - nearest_unit) <= product.uom_id.rounding and nearest_unit >= 1:
            return 1.0
        return remaining

    def _create_pos_preassigned_lot(self, move, pos_order=False):
        product = move.product_id
        order_name = pos_order.name if pos_order else self.name
        prefix = self._sanitize_pos_lot_prefix(order_name)
        Lot = self.env["stock.lot"]
        for sequence in range(1, 10000):
            lot_name = "%s-%03d" % (prefix, sequence)
            existing = Lot.search(
                [("name", "=", lot_name), ("product_id", "=", product.id)],
                limit=1,
            )
            if existing:
                continue
            lot = Lot.create(
                {
                    "name": lot_name,
                    "product_id": product.id,
                    "company_id": move.company_id.id,
                }
            )
            _logger.info(
                "%s created | picking=%s move=%s product=%s lot=%s",
                _LOG,
                self.name,
                move.id,
                product.display_name,
                lot.name,
            )
            return lot
        raise UserError(_("Could not generate a unique POS lot for %s.") % product.display_name)

    def _sanitize_pos_lot_prefix(self, name):
        clean = re.sub(r"[^A-Za-z0-9]+", "-", name or "POS").strip("-").upper()
        return "POS-%s" % (clean or "ORDER")
