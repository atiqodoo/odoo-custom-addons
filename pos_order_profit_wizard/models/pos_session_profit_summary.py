# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PosSession(models.Model):
    _inherit = "pos.session"

    # --- Stored fields: fast list-view aggregation from already-stored order fields ---

    session_total_selling_price = fields.Float(
        string="Total Selling Price",
        compute="_compute_session_stored_summary",
        store=True,
        digits="Product Price",
    )
    session_total_profit = fields.Float(
        string="Session Profit",
        compute="_compute_session_stored_summary",
        store=True,
        digits="Product Price",
    )
    session_profit_margin_pct = fields.Float(
        string="Profit Margin (%)",
        compute="_compute_session_stored_summary",
        store=True,
        digits=(16, 2),
    )

    # --- Non-stored: detailed cost breakdown, computed live on the form view only ---

    session_total_cost_incl_vat = fields.Float(
        string="Total Cost (incl. VAT + Landed Costs)",
        compute="_compute_session_cost_detail",
        digits="Product Price",
    )

    @api.depends("order_ids.wizard_grand_total_profit", "order_ids.amount_total")
    def _compute_session_stored_summary(self):
        for session in self:
            total_selling = sum(session.order_ids.mapped("amount_total"))
            total_profit = sum(session.order_ids.mapped("wizard_grand_total_profit"))
            margin_pct = (total_profit / total_selling * 100) if total_selling else 0.0
            session.session_total_selling_price = total_selling
            session.session_total_profit = total_profit
            session.session_profit_margin_pct = margin_pct

    @api.depends(
        "order_ids.lines",
        "order_ids.lines.product_id",
        "order_ids.lines.product_id.standard_price",
        "order_ids.lines.product_id.taxes_id",
        "order_ids.lines.product_id.taxes_id.amount",
        "order_ids.lines.product_id.taxes_id.amount_type",
        "order_ids.lines.qty",
    )
    def _compute_session_cost_detail(self):
        for session in self:
            total_cost = 0.0
            for order in session.order_ids:
                for line in order.lines:
                    product = line.product_id
                    if not product:
                        continue
                    vat_rate = 0.0
                    for tax in product.taxes_id:
                        if tax.amount_type == "percent":
                            vat_rate += tax.amount
                    cost_incl_vat = product.standard_price * (1 + vat_rate / 100)
                    total_cost += cost_incl_vat * line.qty
            session.session_total_cost_incl_vat = total_cost
