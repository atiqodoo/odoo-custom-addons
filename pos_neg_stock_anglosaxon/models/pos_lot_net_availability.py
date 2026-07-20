# -*- coding: utf-8 -*-
"""Cap existing POS lot allocation by the product's net source stock."""

import logging

from odoo import models
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)
_LOG = "[NegStock][POS_LOT_NET_CAP]"


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _iter_available_lots_for_move(self, move):
        """Do not reuse positive lot rows that are offset by lotless debt."""
        product = move.product_id
        rounding = product.uom_id.rounding
        source_quants = self.env["stock.quant"].sudo().search(
            [
                ("product_id", "=", product.id),
                ("location_id", "child_of", move.location_id.id),
            ]
        )
        net_available = sum(
            source_quants.mapped(lambda quant: quant.quantity - quant.reserved_quantity)
        )
        remaining = max(net_available, 0.0)

        for lot, available_qty in super()._iter_available_lots_for_move(move):
            if float_compare(remaining, 0.0, precision_rounding=rounding) <= 0:
                break
            allocated = min(available_qty, remaining)
            if float_compare(allocated, 0.0, precision_rounding=rounding) > 0:
                yield lot, allocated
                remaining -= allocated

        positive_lot_available = sum(
            max(quant.quantity - quant.reserved_quantity, 0.0)
            for quant in source_quants.filtered("lot_id")
        )
        if float_compare(
            positive_lot_available,
            max(net_available, 0.0),
            precision_rounding=rounding,
        ) > 0:
            _logger.warning(
                "%s capped | picking=%s move=%s product=%s net_available=%.4f "
                "positive_lot_available=%.4f",
                _LOG,
                self.name,
                move.id,
                product.display_name,
                net_available,
                positive_lot_available,
            )

