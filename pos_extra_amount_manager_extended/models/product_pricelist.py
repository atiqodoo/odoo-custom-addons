# -*- coding: utf-8 -*-
"""
Pricelist helpers for post-sale POS extra amount calculation.

The standard product.pricelist API returns a fallback product sales price when
no concrete pricelist rule exists. For commission audit, this module needs to
know whether the product was explicitly configured on the order pricelist.
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    def _pos_extra_find_product_rule(self, product, quantity=1.0, date=False):
        """Return the best explicit product/template rule for ``product``.

        Category and global rules are intentionally ignored. The business rule
        here is strict: if the product itself was not configured on this
        pricelist, a user should add it post-sale before extra is calculated.
        """
        self.ensure_one()
        product.ensure_one()

        date = date or fields.Datetime.now()
        qty = quantity or 1.0
        qty_in_product_uom = qty

        _logger.debug(
            "[POS Pricelist][%s] Searching explicit rule | product_id=%s | "
            "template_id=%s | qty=%.4f | date=%s",
            self.id,
            product.id,
            product.product_tmpl_id.id,
            qty,
            date,
        )

        domain = [
            ('pricelist_id', '=', self.id),
            ('applied_on', 'in', ['0_product_variant', '1_product']),
            '|', ('product_id', '=', product.id),
                 ('product_tmpl_id', '=', product.product_tmpl_id.id),
            '|', ('date_start', '=', False), ('date_start', '<=', date),
            '|', ('date_end', '=', False), ('date_end', '>=', date),
        ]
        rules = self.env['product.pricelist.item'].with_context(active_test=False).search(domain)

        for rule in rules:
            if rule._is_applicable_for(product, qty_in_product_uom):
                _logger.info(
                    "[POS Pricelist][%s] Explicit rule found | rule_id=%s | "
                    "product=%s | applied_on=%s | fixed_price=%.4f",
                    self.id,
                    rule.id,
                    product.display_name,
                    rule.applied_on,
                    rule.fixed_price or 0.0,
                )
                return rule

        _logger.warning(
            "[POS Pricelist][%s] No explicit product/template rule found | "
            "product_id=%s | product=%s",
            self.id,
            product.id,
            product.display_name,
        )
        return self.env['product.pricelist.item']


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    pos_added_from_order_line_id = fields.Many2one(
        'pos.order.line',
        string='Added From POS Line',
        readonly=True,
        copy=False,
        help="POS order line that created this post-sale pricelist rule."
    )

    pos_added_from_order_id = fields.Many2one(
        related='pos_added_from_order_line_id.order_id',
        string='Added From POS Order',
        store=True,
        readonly=True,
    )
