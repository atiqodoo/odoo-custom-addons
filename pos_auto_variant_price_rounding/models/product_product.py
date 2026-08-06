# -*- coding: utf-8 -*-

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = "product.product"

    pos_auto_price_last_inclusive_cost = fields.Float(
        string="Last Auto Price Inclusive Cost",
        readonly=True,
        copy=False,
        digits="Product Price",
    )
    pos_auto_price_last_sale_price = fields.Float(
        string="Last Auto Price Sale Price",
        readonly=True,
        copy=False,
        digits="Product Price",
    )
    pos_auto_price_last_log_id = fields.Many2one(
        "pos.auto.variant.price.log",
        string="Last Auto Price Log",
        readonly=True,
        copy=False,
    )

    def write(self, vals):
        should_track = (
            "standard_price" in vals
            and not self.env.context.get("skip_pos_auto_variant_price")
            and not self.env.context.get("disable_auto_svl")
        )
        old_cost_by_product = {}
        if should_track:
            old_cost_by_product = {product.id: product.standard_price for product in self}
            _logger.debug("[POS_AUTO_PRICE] manual cost snapshot=%s vals=%s", old_cost_by_product, vals)

        result = super().write(vals)

        if should_track:
            try:
                self.env["pos.auto.variant.price.service"].process_products(
                    self,
                    old_cost_by_product=old_cost_by_product,
                    trigger="manual_cost",
                    source=None,
                )
            except Exception:
                _logger.exception("[POS_AUTO_PRICE] manual cost processing failed for products=%s", self.ids)
        return result
