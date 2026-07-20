# -*- coding: utf-8 -*-
"""Allocate recovery lots only to POS debt and normal lots to surplus."""

import logging
import re

from odoo import models
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)
_LOG = "[PT][MO_POS_LOT_RECOVERY]"


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def _pt_assign_pending_pos_lots_before_done(self):
        """Use one shared negative-debt pool per product/location for a batch."""
        assigned = self.env["mrp.production"]
        used_lot_ids = set()
        debt_by_key = {}

        for mo in self.sorted("id"):
            if (
                mo.state in ("done", "cancel")
                or mo.product_tracking not in ("lot", "serial")
                or mo.lot_producing_id
                or not mo.is_tinting_mo
            ):
                continue

            key = (mo.company_id.id, mo.product_id.id, mo.location_dest_id.id)
            if key not in debt_by_key:
                quants = self.env["stock.quant"].sudo().search(
                    [
                        ("product_id", "=", mo.product_id.id),
                        ("location_id", "child_of", mo.location_dest_id.id),
                    ]
                )
                debt_by_key[key] = max(-sum(quants.mapped("quantity")), 0.0)

            quantity = mo.product_uom_id._compute_quantity(
                mo.qty_producing or mo.product_qty,
                mo.product_id.uom_id,
                rounding_method="HALF-UP",
            )
            rounding = mo.product_id.uom_id.rounding
            debt_remaining = debt_by_key[key]
            covers_negative_debt = (
                float_compare(
                    debt_remaining,
                    quantity,
                    precision_rounding=rounding,
                )
                >= 0
            )

            if covers_negative_debt:
                lot = mo._pt_find_pending_pos_lot_for_production(used_lot_ids)
                if not lot:
                    lot = mo._pt_get_or_create_pos_recovery_lot(used_lot_ids)
                debt_by_key[key] = max(debt_remaining - quantity, 0.0)
                lot_kind = "pos_debt"
            else:
                mo.action_generate_serial()
                lot = mo.lot_producing_id
                lot_kind = "normal_surplus"

            if not lot:
                continue
            mo.lot_producing_id = lot.id
            used_lot_ids.add(lot.id)
            assigned |= mo
            _logger.info(
                "%s allocated | mo=%s product=%s lot=%s kind=%s "
                "opening_debt=%.4f qty=%.4f remaining_debt=%.4f",
                _LOG,
                mo.name,
                mo.product_id.display_name,
                lot.name,
                lot_kind,
                debt_remaining,
                quantity,
                debt_by_key[key],
            )

        return assigned

    def _pt_get_or_create_pos_recovery_lot(self, exclude_lot_ids):
        self.ensure_one()
        clean_mo_name = re.sub(r"[^A-Za-z0-9]+", "-", self.name or str(self.id)).strip("-")
        lot_name = "POS-RECOVERY-%s" % clean_mo_name.upper()
        Lot = self.env["stock.lot"].sudo()
        lot = Lot.search(
            [
                ("name", "=", lot_name),
                ("product_id", "=", self.product_id.id),
                ("company_id", "=", self.company_id.id),
            ],
            limit=1,
        )
        if lot and lot.id in exclude_lot_ids:
            return self.env["stock.lot"]
        if not lot:
            lot = Lot.create(
                {
                    "name": lot_name,
                    "product_id": self.product_id.id,
                    "company_id": self.company_id.id,
                }
            )
        _logger.warning(
            "%s selected | mo=%s product=%s lot=%s reason=negative_pos_debt_without_pending_lot",
            _LOG,
            self.name,
            self.product_id.display_name,
            lot.name,
        )
        return lot

