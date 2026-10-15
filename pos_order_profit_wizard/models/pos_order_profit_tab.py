# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    wizard_cost_price_incl_vat = fields.Monetary(
        string="Cost Price (incl. VAT)",
        compute="_compute_wizard_profit",
        store=True,
        currency_field="currency_id",
    )
    wizard_profit_per_unit = fields.Monetary(
        string="Profit / Unit",
        compute="_compute_wizard_profit",
        store=True,
        currency_field="currency_id",
    )
    wizard_total_profit = fields.Monetary(
        string="Total Profit",
        compute="_compute_wizard_profit",
        store=True,
        currency_field="currency_id",
    )

    @api.depends(
        "product_id",
        "product_id.taxes_id",
        "product_id.taxes_id.amount",
        "product_id.taxes_id.amount_type",
        "price_unit",
        "price_subtotal_incl",
        "qty",
        "wizard_log_cost_price_incl",
        "wizard_log_cost_snapshot_at",
    )
    def _compute_wizard_profit(self):
        for line in self:
            cost_total_incl = line._wizard_get_cost_total_incl_for_profit()
            total_profit = line.price_subtotal_incl - cost_total_incl
            cost_incl_vat = cost_total_incl / line.qty if line.qty else 0.0
            profit_per_unit = total_profit / line.qty if line.qty else 0.0

            line.wizard_cost_price_incl_vat = cost_incl_vat
            line.wizard_profit_per_unit = profit_per_unit
            line.wizard_total_profit = total_profit
