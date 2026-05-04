# -*- coding: utf-8 -*-
import logging
from odoo import models, api
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)


class PosOrderLoyaltyOverride(models.Model):
    _inherit = 'pos.order'

    # -------------------------------------------------------------------------
    # Entry point — Odoo 18 signature: _process_order(self, order, existing_order)
    # `order` is the raw order dict (session_id, partner_id, lines, … at top level)
    # There is NO `draft` parameter — it is computed internally from order['state']
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Zero-payment earning guard — mirrors frontend order_model_patch.js
    # -------------------------------------------------------------------------

    def confirm_coupon_programs(self, coupon_data):
        """
        Backend safety net for the zero-payment earning rule:
        if the order total is 0 (entire bill covered by loyalty redemption),
        strip any earning (positive point changes) from coupon_data before
        the parent method applies them to loyalty.card records.

        The frontend already zeroes earning via pointsForPrograms() when
        scaleFactor = 0.  This override is the server-side defence against
        any bypass or race condition.

        coupon_data structure (from frontend, keys may be strings or ints):
          { coupon_id: { 'points': net_change, 'won': earned, 'spent': redeemed, ... } }
        'points' = earned − redeemed  (positive = net gain, negative = net spend)
        """
        precision = (self.currency_id.rounding if self.currency_id else None) or 0.01

        _logger.debug(
            "[loyalty_backend] confirm_coupon_programs | order=%s | amount_total=%.4f",
            self.name, self.amount_total,
        )

        if float_is_zero(self.amount_total, precision_rounding=precision):
            _logger.info(
                "[loyalty_backend] ZERO-PAYMENT guard | order=%s | amount_total=%.4f"
                " → zeroing all earning points in coupon_data",
                self.name, self.amount_total,
            )
            cleaned = {}
            for k, vals in coupon_data.items():
                pts = vals.get('points', 0)
                if pts > 0:
                    _logger.debug(
                        "[loyalty_backend]   coupon %s: earned %.2f pts → zeroed", k, pts,
                    )
                    vals = {**vals, 'points': 0, 'won': 0}
                cleaned[k] = vals
            coupon_data = cleaned

        return super().confirm_coupon_programs(coupon_data)

    # -------------------------------------------------------------------------
    # Entry point — Odoo 18 signature: _process_order(self, order, existing_order)
    # -------------------------------------------------------------------------

    @api.model
    def _process_order(self, order, existing_order):
        partner_id = order.get('partner_id')
        order_name = order.get('name', 'unknown')

        _logger.debug(
            "[loyalty_backend] _process_order called | order=%s | partner_id=%s | existing=%s",
            order_name, partner_id, existing_order is not None,
        )

        if partner_id:
            self._validate_loyalty_redemption_backend(order, partner_id)
        else:
            _logger.debug(
                "[loyalty_backend] _process_order: no partner on order %s — skipping loyalty check",
                order_name,
            )

        return super()._process_order(order, existing_order)

    # -------------------------------------------------------------------------
    # Redemption guard — atomic, race-condition safe
    # -------------------------------------------------------------------------

    def _validate_loyalty_redemption_backend(self, order, partner_id):
        """
        Audit log only — does NOT block the order.

        The primary enforcement is the frontend points-balance pre-check in
        _applyReward (unpaid_invoice_guard.js).  A backend raise here is too
        coarse: POS loyalty auto-applies rewards without the cashier's intent,
        so blocking the ENTIRE checkout when the auto-applied reward is over
        budget creates false-positive "Validation Error" dialogs on ordinary
        cash transactions.

        We keep the detection so that any slip-through (frontend bypassed or
        card balance changed between session start and payment) is visible in
        server logs.  The SELECT FOR UPDATE lock is kept so concurrent
        redemptions from multiple terminals are serialised and the log entry
        reflects the true locked balance at payment time.
        """
        order_name = order.get('name', 'unknown')

        _logger.debug(
            "[loyalty_backend] _validate_loyalty_redemption_backend | order=%s | partner_id=%s",
            order_name, partner_id,
        )

        loyalty_card = self.env['loyalty.card'].search(
            [
                ('partner_id', '=', partner_id),
                ('program_id.program_type', '=', 'loyalty'),
            ],
            order='points desc',
            limit=1,
        )

        if not loyalty_card:
            _logger.debug(
                "[loyalty_backend] No loyalty card found for partner_id=%s — skipping redemption check",
                partner_id,
            )
            return

        _logger.debug(
            "[loyalty_backend] Loyalty card found | card_id=%s | program=%s | points_before_lock=%.2f",
            loyalty_card.id,
            loyalty_card.program_id.name,
            loyalty_card.points,
        )

        # Row-level lock: serialise concurrent redemptions for the same card
        self.env.cr.execute(
            "SELECT points FROM loyalty_card WHERE id = %s FOR UPDATE",
            (loyalty_card.id,),
        )
        row = self.env.cr.fetchone()
        current_points = float(row[0]) if row else 0.0

        _logger.debug(
            "[loyalty_backend] Row-locked balance | card_id=%s | locked_points=%.2f",
            loyalty_card.id, current_points,
        )

        total_redeemed = self._extract_redeemed_points(order)

        _logger.debug(
            "[loyalty_backend] Redemption audit | order=%s | requested=%.2f | available=%.2f | partner=%s",
            order_name, total_redeemed, current_points, partner_id,
        )

        if total_redeemed > 0 and total_redeemed > current_points + 0.001:
            _logger.warning(
                "[loyalty_backend] AUDIT: order=%s | requested=%.0f pts > available=%.0f pts"
                " | partner_id=%s | card_id=%s"
                " — frontend guard should have blocked this; allowing through (backend does not raise)",
                order_name, total_redeemed, current_points,
                partner_id, loyalty_card.id,
            )
        else:
            _logger.debug(
                "[loyalty_backend] PASSED | order=%s | redeemed=%.2f | remaining_after_order=%.2f",
                order_name,
                total_redeemed,
                current_points - total_redeemed,
            )

    def _extract_redeemed_points(self, order):
        """
        Sum the points_cost of every reward line in the order.

        `points_cost` is declared in pos_loyalty/models/pos_order.py (line 226)
        and is always serialised in the POS order payload for Odoo 18.

        Fallback for edge cases: estimate from line value / discount_per_point.

        Order lines arrive as ORM create-tuples: [0, 0, {vals}]
        """
        lines = order.get('lines', [])
        total_points = 0.0

        _logger.debug(
            "[loyalty_backend] _extract_redeemed_points | processing %d order lines",
            len(lines),
        )

        for idx, entry in enumerate(lines):
            if isinstance(entry, (list, tuple)) and len(entry) == 3:
                vals = entry[2]
            elif isinstance(entry, dict):
                vals = entry
            else:
                _logger.debug(
                    "[loyalty_backend]   line[%d]: unexpected format %s — skipped",
                    idx, type(entry).__name__,
                )
                continue

            if not vals.get('is_reward_line'):
                continue

            # Primary: pos_loyalty always sets points_cost on reward lines
            points_cost = vals.get('points_cost') or 0
            if points_cost:
                _logger.debug(
                    "[loyalty_backend]   reward line[%d]: points_cost=%.2f | reward_id=%s",
                    idx, float(points_cost), vals.get('reward_id'),
                )
                total_points += float(points_cost)
                continue

            # Fallback: derive from monetary value ÷ discount_per_point
            reward_id = vals.get('reward_id')
            if not reward_id:
                _logger.debug(
                    "[loyalty_backend]   reward line[%d]: no points_cost and no reward_id — skipped",
                    idx,
                )
                continue

            reward = self.env['loyalty.reward'].browse(reward_id).exists()
            if not reward or not reward.discount_per_point:
                _logger.debug(
                    "[loyalty_backend]   reward line[%d]: reward_id=%s has no discount_per_point — skipped",
                    idx, reward_id,
                )
                continue

            line_value = abs(vals.get('price_subtotal_incl', 0.0))
            estimated = line_value / reward.discount_per_point
            _logger.debug(
                "[loyalty_backend]   reward line[%d]: fallback estimate"
                " | line_value=%.2f | discount_per_point=%.4f | estimated_points=%.2f",
                idx, line_value, reward.discount_per_point, estimated,
            )
            total_points += estimated

        _logger.debug(
            "[loyalty_backend] _extract_redeemed_points total: %.2f", total_points,
        )
        return total_points

    # -------------------------------------------------------------------------
    # Net earning base — server mirror of loyalty_earning_engine.js
    # -------------------------------------------------------------------------

    def _compute_net_earning_base_server(self, order_lines_data):
        """
        Compute the tax-inclusive net paid value per product line after:
          Pass 1 — proportional allocation of global discount rewards
          Pass 2 — proportional allocation of other redemption rewards

        Mirrors computeNetLineValues() in loyalty_earning_engine.js.

        Returns: { line_index: net_paid_value }
        """
        product_lines = [l for l in order_lines_data if not l.get('is_reward_line')]
        discount_lines = [
            l for l in order_lines_data
            if l.get('is_reward_line') and l.get('reward_type') == 'discount'
        ]
        other_reward_lines = [
            l for l in order_lines_data
            if l.get('is_reward_line') and l.get('reward_type') != 'discount'
        ]

        gross = {}
        grand_total = 0.0
        for idx, line in enumerate(product_lines):
            val = abs(line.get('price_subtotal_incl', 0.0))
            gross[idx] = val
            grand_total += val

        _logger.debug(
            "[loyalty_backend] _compute_net_earning_base_server"
            " | product_lines=%d | grand_total=%.2f"
            " | discount_lines=%d | other_reward_lines=%d",
            len(product_lines), grand_total,
            len(discount_lines), len(other_reward_lines),
        )

        if grand_total == 0.0:
            return {i: 0.0 for i in range(len(product_lines))}

        discount_pool = sum(abs(l.get('price_subtotal_incl', 0.0)) for l in discount_lines)
        discount_share = _distribute_proportionally(gross, discount_pool, grand_total)
        post_discount = {k: max(0.0, gross[k] - discount_share[k]) for k in gross}

        redemption_pool = sum(abs(l.get('price_subtotal_incl', 0.0)) for l in other_reward_lines)
        pd_total = sum(post_discount.values())
        redemption_share = _distribute_proportionally(post_discount, redemption_pool, pd_total)

        net = {k: max(0.0, post_discount[k] - redemption_share[k]) for k in post_discount}

        _logger.debug(
            "[loyalty_backend] _compute_net_earning_base_server result"
            " | discount_pool=%.2f | redemption_pool=%.2f | net_total=%.2f",
            discount_pool, redemption_pool, sum(net.values()),
        )

        return net


# -------------------------------------------------------------------------
# Module-level helper
# -------------------------------------------------------------------------

def _distribute_proportionally(values_dict, pool, base_total):
    """
    Allocate `pool` across entries of `values_dict` proportionally to their
    values. Applies Largest Remainder Method to eliminate rounding drift so
    that sum(result.values()) == pool exactly.
    """
    if pool <= 0.0 or base_total <= 0.0:
        return {k: 0.0 for k in values_dict}

    result = {}
    fractionals = []
    total_floored = 0.0

    for k, v in values_dict.items():
        exact = (v / base_total) * pool
        floored = int(exact * 100) / 100.0
        result[k] = floored
        total_floored += floored
        fractionals.append((exact - floored, k))

    residual = round(pool - total_floored, 2)
    fractionals.sort(reverse=True)
    for _, k in fractionals:
        if residual <= 0.0:
            break
        bump = min(0.01, residual)
        result[k] = round(result[k] + bump, 2)
        residual = round(residual - bump, 2)

    return result
