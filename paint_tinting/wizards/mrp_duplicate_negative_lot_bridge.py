# -*- coding: utf-8 -*-
"""Reuse POS preassigned negative lots when duplicating tinting MOs."""

import logging

from odoo import models
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)
_LOG = "[PT][NEG_LOT_BRIDGE]"


class MrpProductionDuplicateWizard(models.TransientModel):
    _inherit = "mrp.production.duplicate.wizard"

    def _produce_tinting_duplicate_now(self, production):
        used_lot_ids = set()
        for mo in production:
            if mo.product_tracking in ("lot", "serial") and not mo.lot_producing_id:
                lot = self._get_next_negative_pos_lot_for_mo(mo, used_lot_ids)
                if lot:
                    mo.lot_producing_id = lot.id
                    used_lot_ids.add(lot.id)
                    _logger.info(
                        "%s reused lot | mo=%s product=%s lot=%s",
                        _LOG,
                        mo.name,
                        mo.product_id.display_name,
                        lot.name,
                    )
        return super()._produce_tinting_duplicate_now(production)

    def _get_next_negative_pos_lot_for_mo(self, mo, exclude_lot_ids=False):
        exclude_lot_ids = exclude_lot_ids or set()
        Quant = self.env["stock.quant"].sudo()
        domain = [
            ("product_id", "=", mo.product_id.id),
            ("location_id", "child_of", mo.location_dest_id.id),
            ("lot_id", "!=", False),
            ("quantity", "<", 0),
        ]
        if exclude_lot_ids:
            domain.append(("lot_id", "not in", list(exclude_lot_ids)))

        quants = Quant.search(domain, order="in_date asc, id asc")
        for quant in quants:
            if not self._is_pos_preassigned_lot(quant.lot_id):
                continue
            if float_compare(abs(quant.quantity), 0.0, precision_rounding=mo.product_uom_id.rounding) <= 0:
                continue
            return quant.lot_id
        return self.env["stock.lot"]

    def _is_pos_preassigned_lot(self, lot):
        return bool(lot and lot.name and lot.name.startswith("POS-"))
