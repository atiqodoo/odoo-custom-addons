# -*- coding: utf-8 -*-

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        snapshots = {}
        for picking in self:
            if picking.state == "done":
                continue
            if picking.picking_type_code != "incoming" or picking.location_id.usage != "supplier":
                continue
            products = picking.move_ids.filtered(lambda move: move.state not in ("done", "cancel")).mapped("product_id")
            if products:
                snapshots[picking.id] = {product.id: product.standard_price for product in products}
                _logger.debug("[POS_AUTO_PRICE] receipt snapshot picking=%s costs=%s", picking.name, snapshots[picking.id])

        result = super()._action_done()

        service = self.env["pos.auto.variant.price.service"]
        for picking in self:
            old_costs = snapshots.get(picking.id)
            if not old_costs:
                continue
            products = self.env["product.product"].browse(old_costs.keys())
            try:
                service.process_products(products, old_cost_by_product=old_costs, trigger="receipt", source=picking)
            except Exception:
                _logger.exception("[POS_AUTO_PRICE] receipt processing failed for picking=%s", picking.name)
        return result
