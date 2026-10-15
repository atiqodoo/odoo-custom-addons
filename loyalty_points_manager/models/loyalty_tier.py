# -*- coding: utf-8 -*-
import json
import logging
import operator

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_TIER_HEAD = "[LPM_TIER_ENGINE]"
_RESOLVE_HEAD = "[LPM_TIER_RESOLVER]"
_COND_HEAD = "[LPM_TIER_CONDITION]"
_CANDIDATE_HEAD = "[LPM_TIER_CANDIDATE]"
_APPLY_HEAD = "[LPM_TIER_APPLY]"


class LoyaltyProgram(models.Model):
    _inherit = "loyalty.program"

    lpm_tier_earning_policy = fields.Selection(
        [
            ("none", "Base Program Only"),
            ("multiplier", "Tier Multiplier"),
            ("tier_product_rules", "Tier Product Rules"),
            ("variant_rules_multiplier_fallback", "Variant Rules + Multiplier Fallback"),
            ("highest_result", "Highest Result Wins"),
            ("lowest_result", "Lowest Result Wins"),
        ],
        string="Tier Earning Policy",
        default="none",
        required=True,
        help="Controls how tier candidates are selected. No stacking is done unless a custom module overrides the engine.",
    )
    lpm_tier_override_base_eligibility = fields.Boolean(
        string="Tier Product Rules Override Base Eligibility",
        default=False,
        help="When disabled, tier rules only modify orders that already earned base points from the program.",
    )
    lpm_cod_tier_freeze_policy = fields.Selection(
        [
            ("order", "Freeze at COD Order"),
            ("payment", "Resolve at Payment Collection"),
        ],
        string="COD Tier Policy",
        default="order",
        required=True,
    )
    lpm_tier_ids = fields.One2many(
        "loyalty.tier",
        "program_id",
        string="Loyalty Tiers",
    )


class LoyaltyTier(models.Model):
    _name = "loyalty.tier"
    _description = "Loyalty Tier"
    _order = "program_id, sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    program_id = fields.Many2one("loyalty.program", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="program_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="program_id.currency_id", readonly=True)
    sequence = fields.Integer(default=10)
    multiplier = fields.Float(default=1.0, required=True)
    match_policy = fields.Selection(
        [("all", "All Conditions"), ("any", "Any Condition")],
        default="all",
        required=True,
    )
    valid_from = fields.Date()
    valid_to = fields.Date()
    condition_ids = fields.One2many("loyalty.tier.condition", "tier_id", string="Conditions")
    product_rule_ids = fields.One2many("loyalty.tier.product.rule", "tier_id", string="Product Rules")

    _sql_constraints = [
        (
            "loyalty_tier_multiplier_non_negative",
            "CHECK(multiplier >= 0)",
            "Tier multiplier cannot be negative.",
        ),
    ]

    @api.constrains("code")
    def _check_code(self):
        for tier in self:
            if tier.code and " " in tier.code:
                raise ValidationError(_("Tier code cannot contain spaces."))


class LoyaltyTierCondition(models.Model):
    _name = "loyalty.tier.condition"
    _description = "Loyalty Tier Condition"
    _order = "tier_id, sequence, id"

    tier_id = fields.Many2one("loyalty.tier", required=True, ondelete="cascade")
    program_id = fields.Many2one(related="tier_id.program_id", store=True, readonly=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    condition_type = fields.Selection(
        [
            ("lifetime_spend", "Lifetime Spend"),
            ("period_spend", "Period Spend"),
            ("points_balance", "Points Balance"),
            ("paid_order_count", "Paid Order Count"),
            ("partner_tag", "Customer Tag"),
        ],
        required=True,
    )
    operator = fields.Selection(
        [
            (">=", "Greater Than or Equal"),
            (">", "Greater Than"),
            ("<=", "Less Than or Equal"),
            ("<", "Less Than"),
            ("=", "Equal"),
            ("!=", "Not Equal"),
        ],
        default=">=",
        required=True,
    )
    value_float = fields.Float(string="Value")
    period_days = fields.Integer(default=365)
    partner_category_id = fields.Many2one("res.partner.category", string="Customer Tag")


class LoyaltyTierProductRule(models.Model):
    _name = "loyalty.tier.product.rule"
    _description = "Loyalty Tier Product Rule"
    _order = "tier_id, sequence, id"

    tier_id = fields.Many2one("loyalty.tier", required=True, ondelete="cascade")
    program_id = fields.Many2one(related="tier_id.program_id", store=True, readonly=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    product_id = fields.Many2one("product.product", string="Product Variant")
    product_tmpl_id = fields.Many2one("product.template", string="Product")
    categ_id = fields.Many2one("product.category", string="Product Category")
    uom_id = fields.Many2one("uom.uom", string="Rule UoM")
    points_per_qty = fields.Float(default=0.0)
    points_per_amount = fields.Float(default=0.0)
    min_qty = fields.Float(default=0.0)
    stop_at_first_match = fields.Boolean(default=True)

    @api.constrains("points_per_qty", "points_per_amount")
    def _check_points(self):
        for rule in self:
            if rule.points_per_qty < 0 or rule.points_per_amount < 0:
                raise ValidationError(_("Tier product rule points cannot be negative."))


class LoyaltyTierEngine(models.AbstractModel):
    _name = "loyalty.tier.engine"
    _description = "Loyalty Tier Engine"

    def lpm_apply_tier_earning_policy(self, partner, program, source_order, base_points, source_label=None):
        partner = partner.commercial_partner_id or partner
        program = program.sudo()
        base_points = float(base_points or 0.0)

        if not partner or not program or program.lpm_tier_earning_policy == "none":
            self._lpm_log_apply(
                partner, program, source_order, base_points, base_points,
                policy=program.lpm_tier_earning_policy if program else "none",
                reason="policy_none_or_missing",
                source_label=source_label,
            )
            return self._lpm_result(base_points, base_points, False, policy="none")

        if base_points <= 0 and not program.lpm_tier_override_base_eligibility:
            self._lpm_log_apply(
                partner, program, source_order, base_points, base_points,
                policy=program.lpm_tier_earning_policy,
                reason="no_base_points_and_no_override",
                source_label=source_label,
            )
            return self._lpm_result(base_points, base_points, False, policy=program.lpm_tier_earning_policy)

        tier_result = self.lpm_resolve_partner_tier(partner, program, source_order=source_order, source_label=source_label)
        tier = tier_result.get("tier")
        if not tier:
            self._lpm_log_apply(
                partner, program, source_order, base_points, base_points,
                policy=program.lpm_tier_earning_policy,
                reason="no_tier_matched",
                source_label=source_label,
            )
            return self._lpm_result(base_points, base_points, False, policy=program.lpm_tier_earning_policy)

        candidates = self._lpm_build_candidates(partner, program, tier, source_order, base_points)
        final_points, selected_key = self._lpm_select_candidate(program.lpm_tier_earning_policy, candidates, base_points)

        _logger.info(
            "%s SELECTED | source=%s | partner=%s | partner_id=%s | program=%s | program_id=%s "
            "| tier=%s | tier_id=%s | policy=%s | base=%.6f | selected=%s | final=%.6f | candidates=%s",
            _APPLY_HEAD,
            source_label or self._lpm_source_name(source_order),
            partner.display_name,
            partner.id,
            program.display_name,
            program.id,
            tier.display_name,
            tier.id,
            program.lpm_tier_earning_policy,
            base_points,
            selected_key,
            final_points,
            json.dumps(candidates, sort_keys=True),
        )
        return self._lpm_result(
            base_points,
            final_points,
            True,
            tier=tier,
            policy=program.lpm_tier_earning_policy,
            selected_key=selected_key,
            candidates=candidates,
        )

    def lpm_resolve_partner_tier(self, partner, program, source_order=None, source_label=None):
        today = fields.Date.context_today(self)
        tiers = program.lpm_tier_ids.filtered(
            lambda tier: tier.active
            and (not tier.valid_from or tier.valid_from <= today)
            and (not tier.valid_to or tier.valid_to >= today)
        ).sorted(lambda tier: (tier.sequence, tier.id))

        matched = self.env["loyalty.tier"]
        evaluations = []
        for tier in tiers:
            tier_eval = self._lpm_evaluate_tier(partner, tier, source_order=source_order)
            evaluations.append(tier_eval)
            if tier_eval["passed"]:
                matched |= tier

        selected = matched[-1:] if matched else self.env["loyalty.tier"]
        _logger.info(
            "%s RESULT | source=%s | partner=%s | partner_id=%s | program=%s | program_id=%s "
            "| selected_tier=%s | selected_tier_id=%s | evaluations=%s",
            _RESOLVE_HEAD,
            source_label or self._lpm_source_name(source_order),
            partner.display_name,
            partner.id,
            program.display_name,
            program.id,
            selected.display_name if selected else False,
            selected.id if selected else False,
            json.dumps(evaluations, sort_keys=True),
        )
        return {"tier": selected, "evaluations": evaluations}

    def _lpm_evaluate_tier(self, partner, tier, source_order=None):
        conditions = tier.condition_ids.filtered("active")
        if not conditions:
            return {"tier_id": tier.id, "tier": tier.display_name, "passed": True, "conditions": []}

        condition_results = [
            self._lpm_evaluate_condition(partner, condition, source_order=source_order)
            for condition in conditions
        ]
        passed_values = [result["passed"] for result in condition_results]
        passed = all(passed_values) if tier.match_policy == "all" else any(passed_values)
        return {
            "tier_id": tier.id,
            "tier": tier.display_name,
            "passed": passed,
            "match_policy": tier.match_policy,
            "conditions": condition_results,
        }

    def _lpm_evaluate_condition(self, partner, condition, source_order=None):
        provider = self._lpm_tier_condition_providers().get(condition.condition_type)
        if not provider:
            value = 0.0
            passed = False
            reason = "no_provider"
        else:
            value = provider(partner, condition, source_order=source_order)
            passed = self._lpm_compare(value, condition.operator, condition.value_float)
            reason = "evaluated"

        result = {
            "condition_id": condition.id,
            "type": condition.condition_type,
            "operator": condition.operator,
            "expected": condition.value_float,
            "actual": value,
            "passed": passed,
            "reason": reason,
        }
        _logger.debug(
            "%s EVALUATED | partner_id=%s | tier_id=%s | result=%s",
            _COND_HEAD,
            partner.id,
            condition.tier_id.id,
            json.dumps(result, sort_keys=True),
        )
        return result

    def _lpm_tier_condition_providers(self):
        return {
            "lifetime_spend": self._lpm_condition_lifetime_spend,
            "period_spend": self._lpm_condition_period_spend,
            "points_balance": self._lpm_condition_points_balance,
            "paid_order_count": self._lpm_condition_paid_order_count,
            "partner_tag": self._lpm_condition_partner_tag,
        }

    def _lpm_condition_lifetime_spend(self, partner, condition, source_order=None):
        return self._lpm_paid_spend(partner, condition.program_id)

    def _lpm_condition_period_spend(self, partner, condition, source_order=None):
        start_date = fields.Datetime.subtract(fields.Datetime.now(), days=condition.period_days or 365)
        return self._lpm_paid_spend(partner, condition.program_id, start_date=start_date)

    def _lpm_condition_points_balance(self, partner, condition, source_order=None):
        cards = self.env["loyalty.card"].sudo().search([
            ("partner_id", "=", partner.id),
            ("program_id", "=", condition.program_id.id),
        ])
        return sum(float(card.points or 0.0) for card in cards)

    def _lpm_condition_paid_order_count(self, partner, condition, source_order=None):
        start_date = None
        if condition.period_days:
            start_date = fields.Datetime.subtract(fields.Datetime.now(), days=condition.period_days)
        domain = [
            ("partner_id.commercial_partner_id", "=", partner.id),
            ("state", "in", ["paid", "done", "invoiced"]),
        ]
        if start_date:
            domain.append(("date_order", ">=", start_date))
        return self.env["pos.order"].sudo().search_count(domain)

    def _lpm_condition_partner_tag(self, partner, condition, source_order=None):
        if not condition.partner_category_id:
            return 0.0
        return 1.0 if condition.partner_category_id in partner.category_id else 0.0

    def _lpm_paid_spend(self, partner, program, start_date=None):
        AccountMove = self.env["account.move"].sudo()
        PosOrder = self.env["pos.order"].sudo()

        move_domain = [
            ("commercial_partner_id", "=", partner.id),
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "=", "paid"),
        ]
        pos_domain = [
            ("partner_id.commercial_partner_id", "=", partner.id),
            ("state", "in", ["paid", "done", "invoiced"]),
        ]
        if start_date:
            move_domain.append(("invoice_date", ">=", fields.Date.to_date(start_date)))
            pos_domain.append(("date_order", ">=", start_date))

        invoice_total = sum(float(move.amount_total_signed or 0.0) for move in AccountMove.search(move_domain))
        pos_total = sum(float(order.amount_total or 0.0) for order in PosOrder.search(pos_domain))
        return invoice_total + pos_total

    def _lpm_build_candidates(self, partner, program, tier, source_order, base_points):
        multiplier_points = round(base_points * float(tier.multiplier or 0.0), 6)
        product_rule_points = self._lpm_compute_tier_product_rule_points(tier, source_order)
        variant_fallback_points = (
            self._lpm_compute_variant_rule_multiplier_fallback_points(tier, source_order, base_points)
            if program.lpm_tier_earning_policy == "variant_rules_multiplier_fallback"
            else 0.0
        )
        candidates = {
            "base_program_points": round(base_points, 6),
            "tier_multiplier_points": multiplier_points,
            "tier_product_rule_points": product_rule_points,
        }
        if program.lpm_tier_earning_policy == "variant_rules_multiplier_fallback":
            candidates["variant_rules_multiplier_fallback_points"] = variant_fallback_points
        _logger.debug(
            "%s BUILT | source=%s | partner_id=%s | program_id=%s | tier_id=%s | candidates=%s",
            _CANDIDATE_HEAD,
            self._lpm_source_name(source_order),
            partner.id,
            program.id,
            tier.id,
            json.dumps(candidates, sort_keys=True),
        )
        return candidates

    def _lpm_select_candidate(self, policy, candidates, base_points):
        if policy == "multiplier":
            return candidates.get("tier_multiplier_points", base_points), "tier_multiplier_points"
        if policy == "tier_product_rules":
            return candidates.get("tier_product_rule_points", 0.0), "tier_product_rule_points"
        if policy == "variant_rules_multiplier_fallback":
            return (
                candidates.get("variant_rules_multiplier_fallback_points", 0.0),
                "variant_rules_multiplier_fallback_points",
            )
        if policy == "highest_result":
            positives = {key: value for key, value in candidates.items() if value > 0}
            if positives:
                selected_key = max(positives, key=positives.get)
                return positives[selected_key], selected_key
            return 0.0, "no_positive_candidate"
        if policy == "lowest_result":
            positives = {key: value for key, value in candidates.items() if value > 0}
            if positives:
                selected_key = min(positives, key=positives.get)
                return positives[selected_key], selected_key
            return 0.0, "no_positive_candidate"
        return base_points, "base_program_points"

    def _lpm_compute_tier_product_rule_points(self, tier, source_order):
        if not source_order:
            return 0.0
        total = 0.0
        rules = tier.product_rule_ids.filtered("active").sorted(lambda rule: (rule.sequence, rule.id))
        if not rules:
            return 0.0

        for line in self._lpm_source_product_lines(source_order):
            total += self._lpm_compute_line_tier_product_rule_points(tier, line, rules, source_order)["points"]
        return round(total, 6)

    def _lpm_compute_line_tier_product_rule_points(self, tier, line, rules=None, source_order=None):
        rules = rules or tier.product_rule_ids.filtered("active").sorted(lambda rule: (rule.sequence, rule.id))
        line_total = 0.0
        matched_rule_ids = []
        for rule in rules:
            if not self._lpm_product_rule_matches_line(rule, line):
                continue
            qty = self._lpm_line_qty_in_rule_uom(line, rule)
            if rule.min_qty and qty < rule.min_qty:
                continue
            amount = self._lpm_line_amount(line)
            line_points = qty * float(rule.points_per_qty or 0.0) + amount * float(rule.points_per_amount or 0.0)
            line_total += line_points
            matched_rule_ids.append(rule.id)
            _logger.debug(
                "%s PRODUCT_RULE | source=%s | tier_id=%s | rule_id=%s | line_id=%s "
                "| product_id=%s | qty=%.6f | amount=%.6f | line_points=%.6f",
                _CANDIDATE_HEAD,
                self._lpm_source_name(source_order) if source_order else "unknown",
                tier.id,
                rule.id,
                line.id,
                line.product_id.id,
                qty,
                amount,
                line_points,
            )
            if rule.stop_at_first_match:
                break
        return {
            "points": round(line_total, 6),
            "matched": bool(matched_rule_ids),
            "matched_rule_ids": matched_rule_ids,
        }

    def _lpm_compute_variant_rule_multiplier_fallback_points(self, tier, source_order, base_points):
        if not source_order:
            return 0.0

        source_name = self._lpm_source_name(source_order)
        _logger.info(
            "%s VARIANT_FALLBACK_START | source=%s | tier_id=%s | base_points=%.6f | multiplier=%.6f",
            _APPLY_HEAD,
            source_name,
            tier.id,
            float(base_points or 0.0),
            float(tier.multiplier or 0.0),
        )
        try:
            lines = self._lpm_source_product_lines(source_order)
            rules = tier.product_rule_ids.filtered("active").sorted(lambda rule: (rule.sequence, rule.id))
            total_line_amount = sum(max(self._lpm_line_amount(line), 0.0) for line in lines)
            total_line_qty = sum(max(self._lpm_line_qty(line), 0.0) for line in lines)
            total = 0.0
            details = []

            for line in lines:
                rule_result = self._lpm_compute_line_tier_product_rule_points(tier, line, rules, source_order)
                if rule_result["matched"]:
                    line_points = rule_result["points"]
                    basis = "product_rule"
                else:
                    amount = max(self._lpm_line_amount(line), 0.0)
                    qty = max(self._lpm_line_qty(line), 0.0)
                    line_base_points = (
                        float(base_points or 0.0) * amount / total_line_amount
                        if total_line_amount
                        else float(base_points or 0.0) * qty / total_line_qty
                        if total_line_qty
                        else 0.0
                    )
                    line_points = line_base_points * float(tier.multiplier or 0.0)
                    basis = "multiplier_fallback"

                total += line_points
                details.append({
                    "line_id": line.id,
                    "product_id": line.product_id.id,
                    "basis": basis,
                    "points": round(line_points, 6),
                    "matched_rule_ids": rule_result["matched_rule_ids"],
                })

            final_points = round(total, 6)
            _logger.info(
                "%s VARIANT_FALLBACK_END | source=%s | tier_id=%s | base_points=%.6f "
                "| final_points=%.6f | details=%s",
                _APPLY_HEAD,
                source_name,
                tier.id,
                float(base_points or 0.0),
                final_points,
                json.dumps(details, sort_keys=True),
            )
            return final_points
        except Exception as error:
            _logger.exception(
                "%s VARIANT_FALLBACK_ERROR | source=%s | tier_id=%s | base_points=%.6f | error=%s",
                _APPLY_HEAD,
                source_name,
                tier.id,
                float(base_points or 0.0),
                error,
            )
            raise

    def _lpm_source_product_lines(self, source_order):
        if source_order._name == "sale.order":
            return source_order.order_line.filtered(lambda line: not line.display_type and not line.reward_id and line.product_id)
        if source_order._name == "pos.order":
            return source_order.lines.filtered(lambda line: not line.is_reward_line and line.product_id)
        return self.env[source_order._name]

    def _lpm_product_rule_matches_line(self, rule, line):
        product = line.product_id
        if not product:
            return False
        if rule.product_id:
            return product == rule.product_id
        if rule.product_tmpl_id:
            return product.product_tmpl_id == rule.product_tmpl_id
        if rule.categ_id:
            product_path = product.categ_id.parent_path or ""
            rule_path = rule.categ_id.parent_path or ""
            return product.categ_id == rule.categ_id or (bool(rule_path) and product_path.startswith(rule_path))
        return True

    def _lpm_line_qty_in_rule_uom(self, line, rule):
        qty = self._lpm_line_qty(line)
        line_uom = getattr(line, "product_uom", False) or getattr(line, "product_uom_id", False) or line.product_id.uom_id
        if rule.uom_id and line_uom:
            return line_uom._compute_quantity(qty, rule.uom_id)
        return qty

    def _lpm_line_qty(self, line):
        return float(getattr(line, "product_uom_qty", False) or getattr(line, "qty", 0.0) or 0.0)

    def _lpm_line_amount(self, line):
        return float(
            getattr(line, "price_total", False)
            or getattr(line, "price_subtotal_incl", False)
            or getattr(line, "price_subtotal", 0.0)
            or 0.0
        )

    def _lpm_compare(self, left, op, right):
        operators = {
            ">=": operator.ge,
            ">": operator.gt,
            "<=": operator.le,
            "<": operator.lt,
            "=": operator.eq,
            "!=": operator.ne,
        }
        return operators.get(op, operator.ge)(float(left or 0.0), float(right or 0.0))

    def _lpm_result(self, base_points, final_points, tier_applied, tier=None, policy=None, selected_key=None, candidates=None):
        return {
            "base_points": round(float(base_points or 0.0), 6),
            "final_points": round(float(final_points or 0.0), 6),
            "tier_applied": bool(tier_applied),
            "tier_id": tier.id if tier else False,
            "tier_code": tier.code if tier else False,
            "tier_name": tier.display_name if tier else False,
            "tier_multiplier": float(tier.multiplier or 0.0) if tier else 1.0,
            "policy": policy,
            "selected_key": selected_key,
            "candidates": candidates or {},
        }

    def _lpm_log_apply(self, partner, program, source_order, base_points, final_points, policy=None, reason=None, source_label=None):
        _logger.info(
            "%s SKIPPED | source=%s | partner=%s | partner_id=%s | program=%s | program_id=%s "
            "| policy=%s | reason=%s | base=%.6f | final=%.6f",
            _APPLY_HEAD,
            source_label or self._lpm_source_name(source_order),
            partner.display_name if partner else False,
            partner.id if partner else False,
            program.display_name if program else False,
            program.id if program else False,
            policy,
            reason,
            base_points,
            final_points,
        )

    def _lpm_source_name(self, source_order):
        if not source_order:
            return "unknown"
        return "%s:%s" % (source_order._name, source_order.display_name)
