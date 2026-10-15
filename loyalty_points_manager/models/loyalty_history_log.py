# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_HISTORY_HEAD = "[LPM_LOYALTY_HISTORY_LOG]"


class LoyaltyHistoryLog(models.Model):
    _inherit = "loyalty.history"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="card_id.company_id",
        store=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        related="card_id.partner_id",
        store=True,
        readonly=True,
    )
    program_id = fields.Many2one(
        "loyalty.program",
        string="Program",
        related="card_id.program_id",
        store=True,
        readonly=True,
    )
    current_points_balance = fields.Float(
        string="Current Points Balance",
        related="card_id.points",
        store=True,
        readonly=True,
    )
    net_points = fields.Float(
        string="Net Points",
        compute="_compute_lpm_history_summary",
        store=True,
        readonly=True,
    )
    transaction_type = fields.Selection(
        [
            ("earned", "Earned"),
            ("redeemed", "Redeemed"),
            ("mixed", "Earned and Redeemed"),
            ("neutral", "Neutral"),
        ],
        string="Transaction Type",
        compute="_compute_lpm_history_summary",
        store=True,
        readonly=True,
    )
    source_type = fields.Selection(
        [
            ("pos", "POS"),
            ("sale", "Sales Order"),
            ("manual", "Manual Adjustment"),
            ("import", "Import / Balance Sync"),
            ("other", "Other"),
        ],
        string="Source",
        compute="_compute_lpm_source_type",
        store=True,
        readonly=True,
    )
    source_reference = fields.Char(
        string="Source Reference",
        compute="_compute_lpm_source_reference",
        store=True,
        readonly=True,
    )

    @api.depends("issued", "used")
    def _compute_lpm_history_summary(self):
        for history in self:
            issued = float(history.issued or 0.0)
            used = float(history.used or 0.0)
            history.net_points = issued - used
            if issued and used:
                history.transaction_type = "mixed"
            elif issued:
                history.transaction_type = "earned"
            elif used:
                history.transaction_type = "redeemed"
            else:
                history.transaction_type = "neutral"

    @api.depends("order_model")
    def _compute_lpm_source_type(self):
        for history in self:
            if history.order_model == "pos.order":
                history.source_type = "pos"
            elif history.order_model == "sale.order":
                history.source_type = "sale"
            elif history.order_model == "loyalty.points.adjustment":
                history.source_type = "manual"
            elif history.order_model == "res.partner":
                history.source_type = "import"
            else:
                history.source_type = "other"

    @api.depends("order_model", "order_id")
    def _compute_lpm_source_reference(self):
        for history in self:
            history.source_reference = False
            if not history.order_model or not history.order_id:
                continue
            try:
                source = self.env[history.order_model].browse(history.order_id).exists()
                history.source_reference = source.display_name if source else False
            except Exception as error:
                _logger.debug(
                    "%s SOURCE_REFERENCE_SKIPPED | history_id=%s | order_model=%s "
                    "| order_id=%s | error=%s",
                    _HISTORY_HEAD,
                    history.id,
                    history.order_model,
                    history.order_id,
                    error,
                )
