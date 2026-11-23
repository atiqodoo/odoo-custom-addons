"""Transaction-time evidence. Allocations are explicitly distinguished from rules."""
import copy
import json
import logging

from markupsafe import Markup, escape

from odoo import api, fields, models

_logger = logging.getLogger(__name__)
_HEAD = "[LPM][AUDIT]"
_POINT_DIGITS = (16, 6)
# Identity marker cannot be supplied through an RPC context/payload.
_AUDIT_CONTEXT_TOKEN = object()


def _audit_result_summary(result):
    """Keep operation logs concise; full evidence belongs in the audit records."""
    return {key: value for key, value in result.items() if key != "audit"}


class _AuditCapture:
    """Identity-hashed envelope: collecting evidence must not change an ORM context hash."""

    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        self.values[key] = value


class LoyaltyAuditEvent(models.Model):
    _name = "loyalty.audit.event"
    _description = "Loyalty Award Evidence"
    _order = "id"
    _rec_name = "trigger"

    # Sales cancellation removes standard history; retain the evidence separately.
    history_id = fields.Many2one("loyalty.history", ondelete="set null", index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    event_key = fields.Char(required=True, index=True)
    card_id = fields.Many2one("loyalty.card", ondelete="set null", index=True)
    source_model = fields.Char()
    source_order_id = fields.Integer()
    source_reference = fields.Char()
    origin_session_id = fields.Many2one("pos.session", string="Order POS Session", ondelete="set null")
    collection_session_id = fields.Many2one("pos.session", string="COD Collection Session", ondelete="set null")
    trigger = fields.Char(required=True)
    captured_at = fields.Datetime(default=fields.Datetime.now, required=True)
    policy = fields.Char()
    tier_name = fields.Char()
    multiplier = fields.Float(digits=_POINT_DIGITS)
    reason = fields.Char()
    evidence_quality = fields.Selection([("captured", "Captured"), ("partial", "Partial evidence")], required=True)
    balance_before = fields.Float(digits=_POINT_DIGITS)
    balance_after = fields.Float(digits=_POINT_DIGITS)
    issued = fields.Float(digits=_POINT_DIGITS)
    used = fields.Float(digits=_POINT_DIGITS)
    base_points = fields.Float(digits=_POINT_DIGITS)
    evidence_json = fields.Text()
    payment_details = fields.Text()
    line_ids = fields.One2many("loyalty.audit.line", "event_id")
    condition_ids = fields.One2many("loyalty.audit.condition", "event_id")

    _sql_constraints = [
        ("event_key_unique", "unique(history_id, event_key)", "This loyalty event has already been captured."),
    ]

    @api.model
    def _source_lines(self, source):
        if source._name == "pos.order":
            return source.lines
        if source._name == "sale.order":
            return source.order_line
        return self.env["sale.order.line"]

    @api.model
    def _prepare_evidence(self, source, program, result, trace):
        """Freeze source/rule values, without computing another earning result."""
        trace = trace.values if isinstance(trace, _AuditCapture) else trace
        engine = self.env["loyalty.tier.engine"]
        earning_lines = engine._lpm_source_product_lines(source) if source else []
        rows = []
        for line in self._source_lines(source) if source else []:
            uom = getattr(line, "product_uom", False) or getattr(line, "product_uom_id", False)
            rows.append({
                "source_model": line._name, "source_line_id": line.id,
                "product_name": line.product_id.display_name or line.name or "",
                "category_name": line.product_id.categ_id.display_name or "",
                "quantity": engine._lpm_line_qty(line), "uom_name": uom.display_name if uom else "",
                "unit_price": line.price_unit, "discount": line.discount,
                "amount": engine._lpm_line_amount(line),
                "amount_untaxed": line.price_subtotal,
                "taxes": (line.tax_ids if "tax_ids" in line._fields else line.tax_id).mapped("name"),
                "eligible": line in earning_lines,
                "reward": bool(getattr(line, "is_reward_line", False) or getattr(line, "reward_id", False)),
                "coupon_id": line.coupon_id.id if "coupon_id" in line._fields else False,
                "points_cost": line.points_cost if "points_cost" in line._fields else 0.0,
            })
        rule_fields = ["active", "mode", "reward_point_mode", "reward_point_amount",
                       "reward_point_split", "minimum_qty", "minimum_amount",
                       "minimum_amount_tax_mode", "product_ids", "product_category_id"]
        return {
            "version": 1, "evaluated_at": fields.Datetime.to_string(fields.Datetime.now()),
            "currency": source.currency_id.name if source else False,
            "currency_rounding": source.currency_id.rounding if source else False,
            "source_model": source._name if source else False,
            "source_id": source.id if source else False,
            "source_reference": source.display_name if source else False,
            "base_rules": program.rule_ids.sudo().read(rule_fields) if program else [],
            "tier_rules": program.lpm_tier_ids.product_rule_ids.sudo().read([
                "tier_id", "active", "sequence", "product_id", "product_tmpl_id", "categ_id",
                "uom_id", "points_per_qty", "points_per_amount", "min_qty", "stop_at_first_match",
            ]) if program else [],
            "tier_conditions": program.lpm_tier_ids.condition_ids.sudo().read([
                "tier_id", "active", "condition_type", "operator", "value_float",
                "period_days", "partner_category_id",
            ]) if program else [],
            "decision": {k: v for k, v in result.items() if k != "audit"},
            "trace": copy.deepcopy(trace), "lines": rows,
        }

    @api.model
    def _record(self, history, source, result=None, *, event_key, trigger,
                issued=None, used=None, before=None, extra=None):
        """Private server workflow: persist alongside the actual movement, once."""
        history.ensure_one()
        _logger.debug("%s[START] history_id=%s trigger=%s", _HEAD, history.id, trigger)
        try:
            events = self.sudo()
            existing = events.search([("history_id", "=", history.id), ("event_key", "=", event_key)], limit=1)
            if existing:
                _logger.debug("%s[END] history_id=%s outcome=already_captured", _HEAD, history.id)
                return existing
            issued = float(history.issued if issued is None else issued)
            used = float(history.used if used is None else used)
            fallback_reason = "redemption_only" if not issued else "Original earning evidence unavailable"
            result = result or {"base_points": 0.0, "final_points": 0.0,
                                "policy": "redemption_only" if not issued else "unavailable"}
            quality = "captured" if result.get("audit") or not issued else "partial"
            evidence = copy.deepcopy(result.get("audit")) or self._prepare_evidence(
                source, history.program_id, result, {"reason": fallback_reason},
            )
            after = float(history.card_id.points)
            before = after - issued + used if before is None else float(before)
            # Derive event after from its own movement; the live balance may include later events.
            after = before + issued - used
            event = events.create({
                "history_id": history.id, "company_id": source.company_id.id,
                "card_id": history.card_id.id, "source_model": source._name,
                "source_order_id": source.id, "source_reference": source.display_name,
                "origin_session_id": source.session_id.id if source._name == "pos.order" else False,
                "collection_session_id": (extra or {}).get("collection_session_id"),
                "event_key": event_key, "trigger": trigger,
                "evidence_quality": quality,
                "policy": result.get("policy"), "tier_name": result.get("tier_name") or "No tier applied",
                "multiplier": result.get("tier_multiplier", 1.0),
                "reason": evidence.get("trace", {}).get("reason") or result.get("selected_key") or trigger,
                "base_points": result.get("base_points", 0.0),
                "balance_before": before, "balance_after": after, "issued": issued, "used": used,
                "evidence_json": json.dumps(evidence, indent=2, default=str),
                "payment_details": json.dumps(extra or {}, indent=2, default=str),
            })
            rows = self._contributions(evidence, issued, used, history.card_id.id, extra=extra)
            self.env["loyalty.audit.line"].sudo().create([
                {"event_id": event.id, **row} for row in rows
            ])
            conditions = []
            for tier in evidence.get("trace", {}).get("evaluations", []):
                for condition in tier.get("conditions", []):
                    conditions.append({
                        "event_id": event.id, "tier_name": tier["tier"],
                        "condition_type": condition["type"], "operator": condition["operator"],
                        "actual": condition["actual"], "expected": condition["expected"],
                        "passed": condition["passed"], "tier_passed": tier["passed"],
                    })
            self.env["loyalty.audit.condition"].sudo().create(conditions)
            _logger.debug("%s[END] history_id=%s event_id=%s lines=%s issued=%s used=%s",
                          _HEAD, history.id, event.id, len(rows), issued, used)
            return event
        except Exception:
            _logger.exception("%s[ERROR] history_id=%s trigger=%s", _HEAD, history.id, trigger)
            raise

    def _record_cancellation(self, source, before_by_card):
        """Preserve what cancellation actually did, even when standard history is deleted."""
        _logger.debug("%s[CANCEL][START] model=%s order_id=%s", _HEAD, source._name, source.id)
        for card in self.card_id:
            originals = self.filtered(lambda event: event.card_id == card)
            key = "cancel:%s:%s:%s:%s" % (source._name, source.id, max(originals.ids), card.id)
            if self.sudo().search_count([("event_key", "=", key)]):
                continue
            before = before_by_card[card.id]
            after = card.points
            delta = after - before
            expected = -sum(event.issued - event.used for event in originals)
            event = self.sudo().create({
                "company_id": source.company_id.id, "card_id": card.id,
                "source_model": source._name, "source_order_id": source.id,
                "source_reference": source.display_name, "event_key": key,
                "trigger": "Sales cancellation", "evidence_quality": "captured",
                "policy": "actual_cancellation_movement", "balance_before": before,
                "balance_after": after, "issued": delta,
                "reason": "Actual net movement; compare expected reversal in evidence",
                "evidence_json": json.dumps({"original_event_ids": originals.ids,
                    "expected_net_reversal": expected, "actual_net_movement": delta,
                    "difference": round(delta - expected, 6)}, indent=2),
            })
            self.env["loyalty.audit.line"].sudo().create({
                "event_id": event.id, "product_name": "Cancellation net card movement",
                "method": "Order-level cancellation movement", "earned": delta,
                "explanation": "Signed net movement actually posted by the cancellation workflow. "
                               "Original product calculations remain in the referenced audit events.",
            })
        _logger.debug("%s[CANCEL][END] model=%s order_id=%s", _HEAD, source._name, source.id)

    @api.model
    def _line_contribution_providers(self):
        """Extensions can explain additional engine candidates without rewriting the writer."""
        return {
            "base_program_points": self._explain_base_share,
            "tier_multiplier_points": self._explain_multiplier_share,
            "tier_product_rule_points": self._explain_product_rule,
            "variant_rules_multiplier_fallback_points": self._explain_fallback,
            "no_positive_candidate": self._explain_zero,
        }

    @api.model
    def _explain_base_share(self, values):
        return values["share"], "Allocated base share (order-level calculation)"

    @api.model
    def _explain_multiplier_share(self, values):
        decision = values["decision"]
        base = decision.get("base_points", 0.0)
        points = values["share"] * decision.get("final_points", 0.0) / base if base else 0.0
        return points, "Allocated tier-multiplied order total"

    @api.model
    def _explain_product_rule(self, values):
        details = values["product"]
        return details.get("points", 0.0), (
            "Tier product rule" if details.get("rules") else "No matching tier product rule"
        )

    @api.model
    def _explain_fallback(self, values):
        contribution = values["fallback"].get(values["line_id"], {})
        return contribution.get("points", 0.0), contribution.get("basis", "No captured contribution")

    @api.model
    def _explain_zero(self, values):
        return 0.0, "No positive policy candidate"

    @api.model
    def _contributions(self, evidence, issued, used, card_id, extra=None):
        """Use captured tier contributions; base totals remain labelled allocations.

        Order/split rounding and COD collection deltas stay visible in a separate
        reconciliation row instead of being attributed to a fictitious product rule.
        """
        decision = evidence.get("decision", {})
        trace = evidence.get("trace", {})
        lines = evidence.get("lines", [])
        eligible = [line for line in lines if line["eligible"]]
        denominator = sum(line["amount"] for line in eligible)
        base = decision.get("base_points", 0.0)
        selected = decision.get("selected_key") or "base_program_points"
        provider = self._line_contribution_providers().get(selected)
        fallback = {row["line_id"]: row for row in trace.get("fallback_lines", [])}
        product = trace.get("product_lines", {})
        rows = []
        for line in lines:
            share = base * line["amount"] / denominator if line["eligible"] and denominator else 0.0
            details = product.get(str(line["source_line_id"]), {})
            points = 0.0
            method = "Excluded / informational line"
            if line["eligible"]:
                if provider:
                    points, method = provider({"share": share, "decision": decision, "product": details,
                                               "fallback": fallback, "line_id": line["source_line_id"]})
                else:
                    method = "Unknown engine candidate; see order-level reconciliation"
            cost = line["points_cost"] if line["reward"] and line["coupon_id"] == card_id else 0.0
            full_points = points
            if extra and "paid_ratio" in extra:
                full_total = decision.get("final_points", 0.0)
                points = points * issued / full_total if full_total else 0.0
                method += " / allocated collection delta"
            rows.append({
                **{key: line[key] for key in ("source_model", "source_line_id", "product_name",
                   "category_name", "quantity", "uom_name", "unit_price", "discount", "amount")},
                "base_share": round(share, 6), "method": method,
                "earned": round(points, 6), "used": cost,
                "full_order_points": round(full_points, 6),
                "explanation": json.dumps(details, indent=2, default=str),
            })
        difference = round(issued - sum(row["earned"] for row in rows), 6)
        used_difference = round(used - sum(row["used"] for row in rows), 6)
        if difference or used_difference:
            rows.append({
                "product_name": "Order-level reconciliation",
                "method": "Order-level / rounding / collection delta",
                "earned": difference, "used": used_difference,
                "explanation": "Difference between captured full-order contributions and this posted event. "
                               "For COD, see payment details for the collection ratio and prior awards. "
                               "This amount is not an independently calculated product award.",
            })
        return rows


class LoyaltyAuditLine(models.Model):
    _name = "loyalty.audit.line"
    _description = "Loyalty Order Line Evidence"
    _order = "id"
    _rec_name = "product_name"

    event_id = fields.Many2one("loyalty.audit.event", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="event_id.company_id", store=True, index=True)
    history_id = fields.Many2one(related="event_id.history_id", store=True, index=True)
    source_model = fields.Char()
    source_line_id = fields.Integer()
    product_name = fields.Char(required=True)
    category_name = fields.Char()
    quantity = fields.Float(digits="Product Unit of Measure")
    uom_name = fields.Char()
    unit_price = fields.Float(digits="Product Price")
    discount = fields.Float()
    amount = fields.Float(digits="Product Price")
    base_share = fields.Float(string="Allocated Base Points", digits=_POINT_DIGITS)
    method = fields.Char()
    earned = fields.Float(digits=_POINT_DIGITS)
    full_order_points = fields.Float(digits=_POINT_DIGITS)
    used = fields.Float(digits=_POINT_DIGITS)
    explanation = fields.Text()


class LoyaltyAuditCondition(models.Model):
    _name = "loyalty.audit.condition"
    _description = "Loyalty Tier Condition Evidence"
    _order = "id"

    event_id = fields.Many2one("loyalty.audit.event", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="event_id.company_id", store=True, index=True)
    tier_name = fields.Char()
    condition_type = fields.Char()
    operator = fields.Char()
    actual = fields.Float(digits=_POINT_DIGITS)
    expected = fields.Float(digits=_POINT_DIGITS)
    passed = fields.Boolean()
    tier_passed = fields.Boolean()


class LoyaltyHistoryAudit(models.Model):
    _inherit = "loyalty.history"

    audit_event_ids = fields.One2many("loyalty.audit.event", "history_id", groups="loyalty_points_manager.group_loyalty_auditor")
    audit_line_ids = fields.One2many("loyalty.audit.line", "history_id", groups="loyalty_points_manager.group_loyalty_auditor")
    audit_status = fields.Selection([
        ("captured", "Captured at transaction"),
        ("partial", "Partial capture / reconciliation required"),
        ("unavailable", "Historical calculation unavailable"),
    ], compute="_compute_audit_summary", groups="loyalty_points_manager.group_loyalty_auditor")
    audit_issued_difference = fields.Float(compute="_compute_audit_summary", digits=_POINT_DIGITS,
                                          groups="loyalty_points_manager.group_loyalty_auditor")
    audit_used_difference = fields.Float(compute="_compute_audit_summary", digits=_POINT_DIGITS,
                                        groups="loyalty_points_manager.group_loyalty_auditor")
    current_source_lines_html = fields.Html(compute="_compute_current_source_lines",
                                           groups="loyalty_points_manager.group_loyalty_auditor")

    @api.depends("audit_event_ids.issued", "audit_event_ids.used", "audit_event_ids.evidence_quality", "issued", "used")
    def _compute_audit_summary(self):
        for history in self:
            history.audit_issued_difference = round(history.issued - sum(history.audit_event_ids.mapped("issued")), 6)
            history.audit_used_difference = round(history.used - sum(history.audit_event_ids.mapped("used")), 6)
            history.audit_status = "unavailable" if not history.audit_event_ids else (
                "partial" if history.audit_issued_difference or history.audit_used_difference
                or any(event.evidence_quality == "partial" for event in history.audit_event_ids) else "captured"
            )

    @api.depends("order_model", "order_id")
    def _compute_current_source_lines(self):
        for history in self:
            history.current_source_lines_html = False
            if history.order_model not in ("pos.order", "sale.order") or not history.order_id:
                continue
            source = self.env[history.order_model].browse(history.order_id).exists()
            if not source or not source.has_access("read"):
                continue
            rows = []
            engine = self.env["loyalty.tier.engine"]
            for line in self.env["loyalty.audit.event"]._source_lines(source):
                uom = getattr(line, "product_uom", False) or getattr(line, "product_uom_id", False)
                rows.append(Markup("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>") % (
                    escape(line.product_id.display_name or line.name or ""),
                    engine._lpm_line_qty(line), escape(uom.display_name if uom else ""), engine._lpm_line_amount(line),
                ))
            history.current_source_lines_html = Markup(
                "<p>Current source values only. These do not establish the historical loyalty calculation.</p>"
                "<table class='table table-sm'><thead><tr><th>Product / Line</th><th>Quantity</th>"
                "<th>UoM</th><th>Amount</th></tr></thead><tbody>%s</tbody></table>"
            ) % Markup("").join(rows)
