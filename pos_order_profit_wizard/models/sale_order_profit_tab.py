# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api


_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    so_profit_cost_incl_vat = fields.Float(
        string="Cost Price (incl. VAT)",
        compute="_compute_so_profit",
        digits="Product Price",
    )
    so_profit_per_unit = fields.Float(
        string="Profit / Unit",
        compute="_compute_so_profit",
        digits="Product Price",
    )
    so_profit_total = fields.Float(
        string="Total Profit",
        compute="_compute_so_profit",
        digits="Product Price",
    )

    @api.depends(
        "product_id",
        "product_id.standard_price",
        "purchase_price",
        "tax_id",
        "tax_id.amount",
        "tax_id.amount_type",
        "tax_id.price_include",
        "price_unit",
        "product_uom_qty",
        "currency_id",
        "order_id.partner_id",
        "order_id.partner_shipping_id",
    )
    def _compute_so_profit(self):
        for line in self:
            product = line.product_id
            fallback_cost_excl = product.standard_price if product else 0.0
            cost_excl_vat = (
                line.purchase_price
                if "purchase_price" in line._fields
                else fallback_cost_excl
            )

            if line.tax_id:
                tax_result = line.tax_id.compute_all(
                    cost_excl_vat,
                    currency=line.currency_id,
                    quantity=1.0,
                    product=product,
                    partner=line.order_id.partner_shipping_id or line.order_id.partner_id,
                    handle_price_include=False,
                )
                cost_incl_vat = tax_result["total_included"]
                tax_amount = cost_incl_vat - cost_excl_vat
            else:
                cost_incl_vat = cost_excl_vat
                tax_amount = 0.0

            profit_per_unit = line.price_unit - cost_incl_vat
            total_profit = profit_per_unit * line.product_uom_qty

            _logger.debug(
                "[SO PROFIT TAB] line_id=%s product_id=%s cost_excl=%.4f "
                "tax_amount=%.4f cost_incl=%.4f price_unit=%.4f qty=%.4f "
                "profit_unit=%.4f profit_total=%.4f taxes=%s",
                line.id,
                product.id if product else False,
                cost_excl_vat,
                tax_amount,
                cost_incl_vat,
                line.price_unit,
                line.product_uom_qty,
                profit_per_unit,
                total_profit,
                line.tax_id.mapped("display_name"),
            )

            line.so_profit_cost_incl_vat = cost_incl_vat
            line.so_profit_per_unit = profit_per_unit
            line.so_profit_total = total_profit


class SaleOrder(models.Model):
    _inherit = "sale.order"

    so_grand_total_profit = fields.Float(
        string="Grand Total Profit",
        compute="_compute_so_grand_total_profit",
        digits="Product Price",
    )

    @api.depends("order_line.so_profit_total")
    def _compute_so_grand_total_profit(self):
        for order in self:
            order.so_grand_total_profit = sum(order.order_line.mapped("so_profit_total"))
