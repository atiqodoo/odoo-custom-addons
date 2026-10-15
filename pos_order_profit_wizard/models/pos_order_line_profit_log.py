# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models
from odoo.tools.float_utils import float_is_zero


_logger = logging.getLogger(__name__)
RECEIPTED_POS_STATES = ("paid", "invoiced", "done")


class PosOrder(models.Model):
    _inherit = "pos.order"

    def action_pos_order_paid(self):
        result = super().action_pos_order_paid()
        self.lines._wizard_capture_profit_cost_snapshot()
        return result

    def write(self, vals):
        result = super().write(vals)
        if vals.get("state") in RECEIPTED_POS_STATES:
            self.mapped("lines")._wizard_capture_profit_cost_snapshot()
        return result


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    wizard_log_order_ref_id = fields.Many2one(
        comodel_name="pos.order",
        string="Order Ref",
        related="order_id",
        store=True,
        index=True,
    )
    wizard_log_date_order = fields.Datetime(
        string="Order Date",
        related="order_id.date_order",
        store=True,
        index=True,
    )
    wizard_log_session_id = fields.Many2one(
        comodel_name="pos.session",
        string="Session",
        related="order_id.session_id",
        store=True,
        index=True,
    )
    wizard_log_cashier_id = fields.Many2one(
        comodel_name="res.users",
        string="Cashier",
        related="order_id.user_id",
        store=True,
        index=True,
    )
    wizard_log_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        related="order_id.partner_id",
        store=True,
        index=True,
    )
    wizard_log_config_id = fields.Many2one(
        comodel_name="pos.config",
        string="Point of Sale",
        related="order_id.config_id",
        store=True,
        index=True,
    )
    wizard_log_state = fields.Selection(
        string="POS State",
        related="order_id.state",
        store=True,
        index=True,
    )
    wizard_log_price_incl = fields.Monetary(
        string="Price",
        compute="_compute_wizard_profit_log",
        store=True,
        currency_field="currency_id",
    )
    wizard_log_cost_price_incl = fields.Monetary(
        string="Cost Price (Inclusive)",
        currency_field="currency_id",
        copy=False,
        readonly=True,
    )
    wizard_log_cost_snapshot_at = fields.Datetime(
        string="Cost Snapshot At",
        copy=False,
        readonly=True,
        index=True,
    )
    wizard_log_profit_amount_incl = fields.Monetary(
        string="Profit Amount (Incl)",
        compute="_compute_wizard_profit_log",
        store=True,
        currency_field="currency_id",
    )
    wizard_log_profit_margin_pct = fields.Float(
        string="Profit Margin %",
        compute="_compute_wizard_profit_log",
        store=True,
        digits=(16, 2),
    )

    @api.depends(
        "price_subtotal_incl",
        "wizard_log_cost_price_incl",
        "currency_id",
    )
    def _compute_wizard_profit_log(self):
        _logger.debug("[POS PROFIT ORDER LIST] computing %s order line(s)", len(self))
        for line in self:
            currency = line.currency_id
            price_incl = line.price_subtotal_incl
            cost_total_incl = line.wizard_log_cost_price_incl
            profit_amount = price_incl - cost_total_incl
            margin_pct = 0.0
            if currency and not float_is_zero(price_incl, precision_rounding=currency.rounding):
                margin_pct = profit_amount / price_incl * 100
            elif price_incl:
                margin_pct = profit_amount / price_incl * 100

            line.wizard_log_price_incl = price_incl
            line.wizard_log_profit_amount_incl = profit_amount
            line.wizard_log_profit_margin_pct = margin_pct

            _logger.debug(
                "[POS PROFIT ORDER LIST] line_id=%s order=%s product_id=%s qty=%.4f "
                "price_incl=%.4f frozen_cost_total_incl=%.4f profit_incl=%.4f "
                "margin_pct=%.2f cost_snapshot_at=%s cashier_id=%s",
                line.id,
                line.order_id.name,
                line.product_id.id if line.product_id else False,
                line.qty,
                price_incl,
                cost_total_incl,
                profit_amount,
                margin_pct,
                line.wizard_log_cost_snapshot_at,
                line.order_id.user_id.id,
            )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.filtered(lambda line: line.order_id.state in RECEIPTED_POS_STATES)._wizard_capture_profit_cost_snapshot()
        return lines

    def _wizard_capture_profit_cost_snapshot(self):
        lines_to_snapshot = self.filtered(lambda line: not line.wizard_log_cost_snapshot_at)
        snapshot_at = fields.Datetime.now()
        _logger.debug(
            "[POS PROFIT ORDER LIST] snapshot request lines=%s pending=%s snapshot_at=%s",
            len(self),
            len(lines_to_snapshot),
            snapshot_at,
        )
        for line in lines_to_snapshot:
            cost_total_incl, cost_unit_excl, taxes = line._wizard_get_current_cost_total_incl()
            line.write({
                "wizard_log_cost_price_incl": cost_total_incl,
                "wizard_log_cost_snapshot_at": snapshot_at,
            })
            _logger.info(
                "[POS PROFIT ORDER LIST] frozen cost snapshot line_id=%s order=%s product_id=%s "
                "qty=%.4f cost_unit_excl=%.4f cost_total_incl=%.4f snapshot_at=%s taxes=%s",
                line.id,
                line.order_id.name,
                line.product_id.id if line.product_id else False,
                line.qty,
                cost_unit_excl,
                cost_total_incl,
                snapshot_at,
                taxes.mapped("display_name"),
            )

    def _wizard_get_current_cost_total_incl(self):
        self.ensure_one()
        product = self.product_id
        currency = self.currency_id
        taxes = self.tax_ids_after_fiscal_position or self.tax_ids
        cost_unit_excl = product.standard_price if product else 0.0

        if taxes:
            tax_result = taxes.compute_all(
                cost_unit_excl,
                currency=currency,
                quantity=abs(self.qty),
                product=product,
                partner=self.order_id.partner_id,
                handle_price_include=False,
            )
            cost_total_incl = tax_result["total_included"]
        else:
            cost_total_incl = cost_unit_excl * abs(self.qty)

        if self.qty < 0:
            cost_total_incl = -abs(cost_total_incl)

        return cost_total_incl, cost_unit_excl, taxes

    def _wizard_get_cost_total_incl_for_profit(self):
        self.ensure_one()
        if self.wizard_log_cost_snapshot_at:
            return self.wizard_log_cost_price_incl
        cost_total_incl, _cost_unit_excl, _taxes = self._wizard_get_current_cost_total_incl()
        return cost_total_incl

    def _wizard_get_profit_amount_incl_for_profit(self):
        self.ensure_one()
        return self.price_subtotal_incl - self._wizard_get_cost_total_incl_for_profit()

    def action_open_profit_log_order(self):
        self.ensure_one()
        _logger.debug(
            "[POS PROFIT ORDER LIST] opening source order from line_id=%s order_id=%s order=%s",
            self.id,
            self.order_id.id,
            self.order_id.name,
        )
        return {
            "type": "ir.actions.act_window",
            "name": self.order_id.display_name,
            "res_model": "pos.order",
            "res_id": self.order_id.id,
            "view_mode": "form",
            "target": "current",
        }
