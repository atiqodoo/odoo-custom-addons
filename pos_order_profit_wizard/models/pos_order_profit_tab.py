# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    wizard_cost_price_incl_vat = fields.Float(
        string="Cost Price (incl. VAT)",
        compute="_compute_wizard_profit",
        digits="Product Price",
    )
    wizard_profit_per_unit = fields.Float(
        string="Profit / Unit",
        compute="_compute_wizard_profit",
        digits="Product Price",
    )
    wizard_total_profit = fields.Float(
        string="Total Profit",
        compute="_compute_wizard_profit",
        digits="Product Price",
    )

    @api.depends(
        "product_id",
        "product_id.standard_price",
        "product_id.taxes_id",
        "product_id.taxes_id.amount",
        "product_id.taxes_id.amount_type",
        "price_unit",
        "qty",
    )
    def _compute_wizard_profit(self):
        for line in self:
            product = line.product_id
            standard_price = product.standard_price if product else 0.0

            vat_rate = 0.0
            if product:
                for tax in product.taxes_id:
                    if tax.amount_type == "percent":
                        vat_rate += tax.amount

            cost_incl_vat = standard_price * (1 + vat_rate / 100)
            profit_per_unit = line.price_unit - cost_incl_vat
            total_profit = profit_per_unit * line.qty

            line.wizard_cost_price_incl_vat = cost_incl_vat
            line.wizard_profit_per_unit = profit_per_unit
            line.wizard_total_profit = total_profit


class PosOrder(models.Model):
    _inherit = "pos.order"

    wizard_grand_total_profit = fields.Float(
        string="Grand Total Profit",
        compute="_compute_wizard_grand_total_profit",
        digits="Product Price",
    )

    @api.depends("lines.wizard_total_profit")
    def _compute_wizard_grand_total_profit(self):
        for order in self:
            order.wizard_grand_total_profit = sum(order.lines.mapped("wizard_total_profit"))
