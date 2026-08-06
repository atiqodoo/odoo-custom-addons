# -*- coding: utf-8 -*-

from odoo import models, fields, api


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
        "tax_id",
        "tax_id.amount",
        "tax_id.amount_type",
        "price_unit",
        "product_uom_qty",
    )
    def _compute_so_profit(self):
        for line in self:
            product = line.product_id
            standard_price = product.standard_price if product else 0.0

            vat_rate = 0.0
            for tax in line.tax_id:
                if tax.amount_type == "percent":
                    vat_rate += tax.amount

            cost_incl_vat = standard_price * (1 + vat_rate / 100)
            profit_per_unit = line.price_unit - cost_incl_vat
            total_profit = profit_per_unit * line.product_uom_qty

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
