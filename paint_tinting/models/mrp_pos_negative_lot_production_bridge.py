# -*- coding: utf-8 -*-
"""Use pending POS delivery lots when tinting MOs are produced manually.

The duplicate wizard already reuses negative/preassigned POS lots. Operators can
also open a duplicated MO and click Produce All manually, so the same bridge must
exist at mrp.production level before button_mark_done runs.

Two POS oversell shapes are supported:
- temporary/preassigned lots named POS-...
- normal existing lots that POS delivered beyond available stock, leaving the
  same lot negative in WH/Stock
"""

import logging

from odoo import models
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)
_LOG = "[PT][MO_POS_LOT_BRIDGE]"


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def button_mark_done(self):
        bridged = self._pt_assign_pending_pos_lots_before_done()
        if bridged:
            return super(
                MrpProduction,
                self.with_context(pt_allow_negative_manufacturing=True),
            ).button_mark_done()
        return super().button_mark_done()

    def _pt_assign_pending_pos_lots_before_done(self):
        assigned = self.env["mrp.production"]
        used_lot_ids = set()
        for mo in self:
            if (
                mo.state in ("done", "cancel")
                or mo.product_tracking not in ("lot", "serial")
                or mo.lot_producing_id
                or not mo.is_tinting_mo
            ):
                continue

            lot = mo._pt_find_pending_pos_lot_for_production(used_lot_ids)
            if not lot:
                continue

            mo.lot_producing_id = lot.id
            used_lot_ids.add(lot.id)
            assigned |= mo
            _logger.info(
                "%s assigned | mo=%s product=%s lot=%s",
                _LOG,
                mo.name,
                mo.product_id.display_name,
                lot.name,
            )
        return assigned

    def _pt_find_pending_pos_lot_for_production(self, exclude_lot_ids=False):
        self.ensure_one()
        exclude_lot_ids = exclude_lot_ids or set()

        lot = self._pt_find_negative_pos_quant_lot(exclude_lot_ids)
        if lot:
            return lot

        return self._pt_find_unfulfilled_pos_delivery_lot(exclude_lot_ids)

    def _pt_find_negative_pos_quant_lot(self, exclude_lot_ids):
        domain = [
            ("product_id", "=", self.product_id.id),
            ("location_id", "child_of", self.location_dest_id.id),
            ("lot_id", "!=", False),
            ("quantity", "<", 0),
        ]
        if exclude_lot_ids:
            domain.append(("lot_id", "not in", list(exclude_lot_ids)))

        quants = self.env["stock.quant"].sudo().search(domain, order="in_date asc, id asc")
        for quant in quants:
            lot = quant.lot_id
            if float_compare(
                abs(quant.quantity),
                0.0,
                precision_rounding=self.product_uom_id.rounding,
            ) <= 0:
                continue
            if not self._pt_lot_has_pos_delivery(lot):
                continue
            if lot.id in exclude_lot_ids:
                continue
            return lot
        return self.env["stock.lot"]

    def _pt_lot_has_pos_delivery(self, lot):
        if not lot:
            return False
        lines = self.env["stock.move.line"].sudo().search(
            [
                ("product_id", "=", self.product_id.id),
                ("lot_id", "=", lot.id),
                ("move_id.picking_id.state", "=", "done"),
                ("move_id.picking_id.picking_type_code", "=", "outgoing"),
            ],
            order="date asc, id asc",
        )
        for line in lines:
            if line.move_id.picking_id._is_pos_picking():
                return True
        return False

    def _pt_lot_has_negative_stock(self, lot):
        if not lot:
            return False
        quants = self.env["stock.quant"].sudo().search(
            [
                ("product_id", "=", self.product_id.id),
                ("location_id", "child_of", self.location_dest_id.id),
                ("lot_id", "=", lot.id),
                ("quantity", "<", 0),
            ],
            limit=1,
        )
        return bool(quants)

    def _pt_find_unfulfilled_pos_delivery_lot(self, exclude_lot_ids):
        domain = [
            ("product_id", "=", self.product_id.id),
            ("lot_id", "!=", False),
            ("move_id.picking_id.state", "=", "done"),
            ("move_id.picking_id.picking_type_code", "=", "outgoing"),
        ]
        if exclude_lot_ids:
            domain.append(("lot_id", "not in", list(exclude_lot_ids)))

        lines = self.env["stock.move.line"].sudo().search(domain, order="date asc, id asc")
        for line in lines:
            lot = line.lot_id
            if not line.move_id.picking_id._is_pos_picking():
                continue
            if self._pt_is_pos_preassigned_lot(lot):
                if not self._pt_lot_already_produced(lot):
                    return lot
                continue
            if self._pt_lot_has_negative_stock(lot):
                return lot
        return self.env["stock.lot"]

    def _pt_lot_already_produced(self, lot):
        return bool(
            self.env["mrp.production"].sudo().search_count(
                [
                    ("product_id", "=", self.product_id.id),
                    ("lot_producing_id", "=", lot.id),
                    ("state", "=", "done"),
                ]
            )
        )

    def _pt_is_pos_preassigned_lot(self, lot):
        return bool(lot and lot.name and lot.name.startswith("POS-"))
