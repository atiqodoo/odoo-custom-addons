# -*- coding: utf-8 -*-

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockLandedCost(models.Model):
    _inherit = "stock.landed.cost"

    def button_validate(self):
        snapshots = {}
        for cost in self:
            products = cost.valuation_adjustment_lines.mapped("product_id")
            if not products and cost.picking_ids:
                products = cost.picking_ids.move_ids.mapped("product_id")
            if products:
                snapshots[cost.id] = {product.id: product.standard_price for product in products}
                _logger.debug("[POS_AUTO_PRICE] landed cost snapshot cost=%s costs=%s", cost.name, snapshots[cost.id])

        result = super().button_validate()

        service = self.env["pos.auto.variant.price.service"]
        for cost in self:
            old_costs = snapshots.get(cost.id)
            if not old_costs:
                continue
            products = self.env["product.product"].browse(old_costs.keys())
            try:
                service.process_products(products, old_cost_by_product=old_costs, trigger="landed_cost", source=cost)
            except Exception:
                _logger.exception("[POS_AUTO_PRICE] landed cost processing failed for cost=%s", cost.name)
        return result
