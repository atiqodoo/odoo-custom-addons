# -*- coding: utf-8 -*-
"""Audit provisional POS lot cost against actual tinting MO cost."""

import logging

from odoo import api, fields, models
from odoo.tools.float_utils import float_is_zero


_logger = logging.getLogger(__name__)
_LOG = "[PT][POS_LOT_COST]"


class PaintTintingPosLotCostAudit(models.Model):
    _name = "paint.tinting.pos.lot.cost.audit"
    _description = "Paint Tinting POS Lot Cost Audit"
    _order = "date desc, id desc"

    name = fields.Char(required=True, readonly=True, default="New", copy=False)
    date = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    production_id = fields.Many2one("mrp.production", readonly=True, index=True)
    product_id = fields.Many2one("product.product", required=True, readonly=True, index=True)
    lot_id = fields.Many2one("stock.lot", required=True, readonly=True, index=True)
    pos_order_id = fields.Many2one("pos.order", readonly=True, index=True)
    negative_svl_id = fields.Many2one("stock.valuation.layer", readonly=True, index=True)
    provisional_unit_cost = fields.Float(readonly=True, digits="Product Price")
    provisional_total_value = fields.Monetary(readonly=True, currency_field="currency_id")
    actual_unit_cost = fields.Float(readonly=True, digits="Product Price")
    actual_total_value = fields.Monetary(readonly=True, currency_field="currency_id")
    cost_difference = fields.Monetary(readonly=True, currency_field="currency_id")
    quantity = fields.Float(readonly=True, digits="Product Unit of Measure")
    currency_id = fields.Many2one("res.currency", required=True, readonly=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True)
    note = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "paint.tinting.pos.lot.cost.audit"
                ) or "PT/POSLOT/AUDIT"
        return super().create(vals_list)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def button_mark_done(self):
        candidates = self._pt_capture_pos_negative_lot_cost_candidates()
        result = super().button_mark_done()
        self._pt_create_pos_lot_cost_audits(candidates)
        return result

    def _pt_capture_pos_negative_lot_cost_candidates(self):
        candidates = {}
        for mo in self:
            lot = mo.lot_producing_id
            if not lot or not mo.product_id or not lot.name.startswith("POS-"):
                continue
            svl = self.env["stock.valuation.layer"].sudo().search(
                [
                    ("product_id", "=", mo.product_id.id),
                    ("lot_id", "=", lot.id),
                    ("quantity", "<", 0),
                ]
                + ([("pos_negative_origin", "=", True)] if "pos_negative_origin" in self.env["stock.valuation.layer"]._fields else []),
                order="create_date asc, id asc",
                limit=1,
            )
            if not svl:
                continue
            candidates[mo.id] = {
                "lot_id": lot.id,
                "negative_svl_id": svl.id,
                "pos_order_id": svl.pos_order_id.id if "pos_order_id" in svl._fields else False,
                "provisional_unit_cost": svl.unit_cost,
                "provisional_total_value": abs(svl.value),
                "quantity": abs(svl.quantity),
            }
            _logger.info(
                "%s captured | mo=%s product=%s lot=%s svl=%s provisional_unit=%.4f",
                _LOG,
                mo.name,
                mo.product_id.display_name,
                lot.name,
                svl.id,
                svl.unit_cost,
            )
        return candidates

    def _pt_create_pos_lot_cost_audits(self, candidates):
        Audit = self.env["paint.tinting.pos.lot.cost.audit"].sudo()
        for mo in self:
            data = candidates.get(mo.id)
            if not data or mo.state != "done":
                continue
            finished_svls = mo.move_finished_ids.stock_valuation_layer_ids.filtered(
                lambda svl: svl.product_id == mo.product_id
                and svl.quantity > 0
                and (not svl.lot_id or svl.lot_id.id == data["lot_id"])
            )
            actual_total = sum(finished_svls.mapped("value"))
            actual_qty = sum(finished_svls.mapped("quantity")) or mo.qty_produced or mo.product_qty
            actual_unit = actual_total / actual_qty if actual_qty else 0.0
            difference = actual_total - data["provisional_total_value"]
            currency = mo.company_id.currency_id

            existing = Audit.search(
                [("production_id", "=", mo.id), ("lot_id", "=", data["lot_id"])],
                limit=1,
            )
            if existing:
                continue

            audit = Audit.create(
                {
                    "production_id": mo.id,
                    "product_id": mo.product_id.id,
                    "lot_id": data["lot_id"],
                    "pos_order_id": data["pos_order_id"],
                    "negative_svl_id": data["negative_svl_id"],
                    "provisional_unit_cost": data["provisional_unit_cost"],
                    "provisional_total_value": data["provisional_total_value"],
                    "actual_unit_cost": actual_unit,
                    "actual_total_value": actual_total,
                    "cost_difference": difference,
                    "quantity": data["quantity"],
                    "currency_id": currency.id,
                    "company_id": mo.company_id.id,
                    "note": "Audit only; no journal entry posted automatically.",
                }
            )
            _logger.info(
                "%s audit created | audit=%s mo=%s lot=%s provisional=%.4f actual=%.4f diff=%.4f",
                _LOG,
                audit.name,
                mo.name,
                audit.lot_id.name,
                audit.provisional_total_value,
                audit.actual_total_value,
                audit.cost_difference,
            )
            if not float_is_zero(difference, precision_rounding=currency.rounding):
                mo.message_post(
                    body=(
                        "<b>POS Lot Cost Difference Audit</b><br/>"
                        "Lot: <b>%s</b><br/>"
                        "Provisional POS value: %.4f<br/>"
                        "Actual MO value: %.4f<br/>"
                        "Difference: <b>%.4f</b><br/>"
                        "Audit: %s<br/>"
                        "No journal entry was posted automatically."
                    )
                    % (
                        audit.lot_id.display_name,
                        audit.provisional_total_value,
                        audit.actual_total_value,
                        audit.cost_difference,
                        audit.name,
                    )
                )
