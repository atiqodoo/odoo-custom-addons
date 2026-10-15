# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.tools.float_utils import float_is_zero


class PosOrder(models.Model):
    _inherit = "pos.order"

    wizard_total_cost_price_incl_vat = fields.Monetary(
        string="Cost Price (Inclusive)",
        compute="_compute_wizard_profit_metrics",
        store=True,
        currency_field="currency_id",
        index=True,
    )
    wizard_grand_total_profit = fields.Monetary(
        string="Profit Amount",
        compute="_compute_wizard_profit_metrics",
        store=True,
        currency_field="currency_id",
        index=True,
    )
    wizard_profit_margin_pct = fields.Float(
        string="Profit Margin (%)",
        compute="_compute_wizard_profit_metrics",
        store=True,
        digits=(16, 2),
        index=True,
        aggregator="avg",
    )

    @api.depends(
        "amount_total",
        "currency_id",
        "lines.price_subtotal_incl",
        "lines.wizard_log_cost_price_incl",
        "lines.wizard_log_cost_snapshot_at",
    )
    def _compute_wizard_profit_metrics(self):
        for order in self:
            total_cost_incl = sum(
                line._wizard_get_cost_total_incl_for_profit()
                for line in order.lines
            )
            profit_amount = order.amount_total - total_cost_incl
            margin_pct = 0.0

            if order.currency_id and not float_is_zero(
                order.amount_total,
                precision_rounding=order.currency_id.rounding,
            ):
                margin_pct = profit_amount / order.amount_total * 100
            elif order.amount_total:
                margin_pct = profit_amount / order.amount_total * 100

            order.wizard_total_cost_price_incl_vat = total_cost_incl
            order.wizard_grand_total_profit = profit_amount
            order.wizard_profit_margin_pct = margin_pct
