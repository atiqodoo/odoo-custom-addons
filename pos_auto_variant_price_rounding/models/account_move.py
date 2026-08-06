# -*- coding: utf-8 -*-

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    def _post(self, soft=True):
        snapshots = {}
        for move in self:
            if move.move_type not in ("in_invoice", "in_refund", "in_receipt"):
                continue
            products = move.invoice_line_ids.filtered(
                lambda line: line.product_id and line.display_type in (False, "product")
            ).mapped("product_id")
            if products:
                snapshots[move.id] = {product.id: product.standard_price for product in products}
                _logger.debug("[POS_AUTO_PRICE] vendor bill snapshot bill=%s costs=%s", move.display_name, snapshots[move.id])

        posted = super()._post(soft=soft)

        service = self.env["pos.auto.variant.price.service"]
        for move in posted:
            old_costs = snapshots.get(move.id)
            if not old_costs:
                continue
            products = self.env["product.product"].browse(old_costs.keys())
            try:
                service.with_company(move.company_id).process_products(
                    products,
                    old_cost_by_product=old_costs,
                    trigger="vendor_bill",
                    source=move,
                )
            except Exception:
                _logger.exception("[POS_AUTO_PRICE] vendor bill processing failed for bill=%s", move.display_name)
        return posted
