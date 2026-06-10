# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    # Persist so the list view can fetch profit per line without re-computing
    wizard_total_profit = fields.Float(
        string="Total Profit",
        compute="_compute_wizard_profit",
        store=True,
        digits="Product Price",
    )


class PosOrder(models.Model):
    _inherit = "pos.order"

    # Persist so the Orders list view can display profit for all rows efficiently
    wizard_grand_total_profit = fields.Float(
        string="Grand Total Profit",
        compute="_compute_wizard_grand_total_profit",
        store=True,
        digits="Product Price",
    )
    wizard_profit_margin_pct = fields.Float(
        string="Profit Margin (%)",
        compute="_compute_wizard_profit_margin_pct",
        store=True,
        digits=(16, 2),
    )

    @api.depends("wizard_grand_total_profit", "amount_total")
    def _compute_wizard_profit_margin_pct(self):
        for order in self:
            if order.amount_total:
                order.wizard_profit_margin_pct = (order.wizard_grand_total_profit / order.amount_total) * 100
            else:
                order.wizard_profit_margin_pct = 0.0
