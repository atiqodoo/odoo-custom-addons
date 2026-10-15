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

    # --- Non-stored: detailed cost breakdown, using frozen POS line snapshots when present ---

    session_total_cost_incl_vat = fields.Float(
        string="Total Frozen Cost (incl. VAT)",
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
        "order_ids.lines.tax_ids",
        "order_ids.lines.tax_ids_after_fiscal_position",
        "order_ids.lines.qty",
        "order_ids.lines.wizard_log_cost_price_incl",
        "order_ids.lines.wizard_log_cost_snapshot_at",
    )
    def _compute_session_cost_detail(self):
        for session in self:
            total_cost = 0.0
            for order in session.order_ids:
                for line in order.lines:
                    total_cost += line._wizard_get_cost_total_incl_for_profit()
            session.session_total_cost_incl_vat = total_cost
