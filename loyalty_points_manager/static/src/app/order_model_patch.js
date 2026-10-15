/** @odoo-module **/

/**
 * order_model_patch.js
 *
 * Patches PosOrder.prototype to intercept the loyalty earning pipeline and
 * apply the net-earning engine (discount-aware, double-earning-safe).
 *
 * CORRECT PATCH POINT (Odoo 18 Enterprise):
 *   pos_loyalty computes earned points inside `pointsForPrograms(programs)`.
 *   That result is stored in `uiState.couponPointChanges` and then read by
 *   `getLoyaltyPoints()` to produce the summary displayed in the UI.
 *   Patching `pointsForPrograms` is the single correct entry point — it is
 *   the only place where raw line values are converted to program points.
 *
 * What this patch does:
 *   1. Calls super.pointsForPrograms() to get Odoo's standard result.
 *   2. Computes _getNetEarningScaleFactor():
 *         scale = (gross_product_total - all_reward_line_deductions) / gross_product_total
 *   3. For each program's result, separates unit-rule points (discount-immune)
 *      from money-rule points, applies scale to money portion only.
 *   4. Exposes getNetLoyaltyPoints() for the widget to consume.
 */

import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

patch(PosOrder.prototype, {

    // ─────────────────────────────────────────────────────────────────────────
    // Core earning override
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Override Odoo's earning pipeline to apply net-earning logic:
     *   • Deduct reward/discount line values from the money-rule earning base
     *   • Keep unit-rule points unchanged (they depend on qty, not value)
     *
     * @param {Array} programs - loyalty.program records active in this session
     * @returns {Object} { program.id: [{points: number}, ...] }
     */
    pointsForPrograms(programs) {
        const result = super.pointsForPrograms(...arguments);

        if (this._lpmPartnerCanEarnLoyaltyPoints() === false) {
            return this._lpmZeroEarnedLoyaltyResult(
                result,
                programs,
                "partner earning disabled"
            );
        }

        const scaleFactor = this._getNetEarningScaleFactor();

        // ── Zero-payment guard (fixed) ────────────────────────────────────────
        // If the entire order is covered by loyalty redemption (scale = 0),
        // no money changes hands so no points should be earned.
        //
        // FIX: The previous implementation set points = 0 for every entry, which
        // wiped BOTH earning AND spending (since 'points' is the net delta:
        // earned − spent).  A customer who redeemed 100 pts would have those 100
        // pts NOT deducted from their card because the net delta was forced to 0.
        //
        // Correct behaviour: zero the earning portion only.  The spending
        // deduction must survive so the card balance is reduced.
        // We derive spending-per-coupon directly from reward-line points_cost
        // values — the same field the backend reads — so both sides agree.
        if (scaleFactor <= 0) {
            console.log(
                "[loyalty_zero_pay] pointsForPrograms: scale=0" +
                " (fully covered by redemption) → zeroing earning, preserving spending"
            );

            for (const program of programs) {
                if (!result[program.id]?.length) continue;

                result[program.id] = result[program.id].map((entry) => {
                    const couponId = entry.coupon_id;

                    // Sum points_cost from every reward line that belongs to this coupon
                    let costFromLines = 0;
                    for (const line of this.get_orderlines()) {
                        if (
                            line.is_reward_line &&
                            (line.coupon_id?.id ?? line.coupon_id) === couponId &&
                            (line.points_cost || 0) > 0
                        ) {
                            costFromLines += line.points_cost;
                        }
                    }

                    // points = −spending (earning zeroed, spending preserved as deduction)
                    const correctedPoints = -costFromLines;

                    console.log(
                        "[loyalty_zero_pay]   program=" + program.id +
                        " | coupon=" + couponId +
                        " | original_points=" + entry.points +
                        " | original_won=" + (entry.won ?? "?") +
                        " | cost_from_reward_lines=" + costFromLines.toFixed(2) +
                        " | corrected_points=" + correctedPoints.toFixed(2)
                    );

                    return { ...entry, points: correctedPoints, won: 0 };
                });
            }
            return result;
        }

        // If there are no deductions, the scale is 1.0 → nothing to adjust
        if (scaleFactor >= 1.0) return result;

        for (const program of programs) {
            const entries = result[program.id];
            if (!entries?.length) continue;

            // Compute what unit-rules alone contribute (they must NOT be scaled)
            const unitPoints = this._computeUnitOnlyPoints(program);

            result[program.id] = entries.map((entry) => {
                // Isolate the value-rule (money) portion of the points
                const moneyPoints = Math.max(0, entry.points - unitPoints);
                // Apply net deduction scale to money portion only
                const scaledTotal = unitPoints + moneyPoints * scaleFactor;
                return { ...entry, points: Math.round(scaledTotal * 100) / 100 };
            });
        }

        return result;
    },

    // ─────────────────────────────────────────────────────────────────────────
    // Helpers
    // ─────────────────────────────────────────────────────────────────────────

    _lpmPartnerCanEarnLoyaltyPoints() {
        const partner = this.get_partner?.();
        if (!partner) {
            return true;
        }
        return partner.lpm_can_earn_loyalty_points !== false;
    },

    _lpmZeroEarnedLoyaltyResult(result, programs, reason) {
        console.log(
            "[LPM_PARTNER_LOYALTY_POLICY] POS_EARN_ZEROED_FRONTEND | reason=" + reason
        );

        for (const program of programs) {
            if (!result[program.id]?.length) continue;

            result[program.id] = result[program.id].map((entry) => {
                const couponId = entry.coupon_id;
                let costFromLines = 0;

                for (const line of this.get_orderlines()) {
                    if (
                        line.is_reward_line &&
                        (line.coupon_id?.id ?? line.coupon_id) === couponId &&
                        (line.points_cost || 0) > 0
                    ) {
                        costFromLines += line.points_cost;
                    }
                }

                const correctedPoints = costFromLines > 0 ? -costFromLines : 0;
                return { ...entry, points: correctedPoints, won: 0 };
            });
        }
        return result;
    },

    /**
     * The scale factor collapses the two-pass proportional distribution from
     * the earning engine into a single multiplier that is equivalent for all
     * order lines combined.
     *
     * scale = (gross_product_total - deductions) / gross_product_total
     *
     * Proof of equivalence with per-line proportional allocation:
     *   net_i = V_i × (V - D) / V  →  Σ net_i = (V-D)/V × ΣV_i = scale × gross_subtotal
     *
     * FIX: The previous implementation used `l.get_price_with_tax ? f() : 0`,
     * which is a truthiness check — valid but silently returns 0 if the method
     * name differs in this Odoo version.  The robust getter below tries multiple
     * APIs (matching loyalty_earning_engine.js _getTaxInclusiveTotal) before
     * falling back to the stored field price_subtotal_incl.
     *
     * FIX: The previous `if (grossTotal <= 0) return 1` caused the zero-payment
     * guard to NEVER fire when product-line prices all resolved to 0 (API miss).
     * Now: if product lines exist but all return 0, log a warning and return 1
     * (conservative — do not prevent earning when we cannot verify prices).
     * If there are genuinely no product lines, return 0 (no earning base).
     *
     * @returns {number} value in [0, 1]
     */
    _getNetEarningScaleFactor() {
        const allLines    = this.get_orderlines();
        const productLines = allLines.filter((l) => !l.is_reward_line);
        const rewardLines  = allLines.filter((l) => l.is_reward_line);

        // Robust tax-inclusive price getter — mirrors _getTaxInclusiveTotal in
        // loyalty_earning_engine.js.  Tries the live method first, then falls
        // back to the stored computed field so we always get a value.
        const getLineTaxTotal = (l) => {
            if (typeof l.get_price_with_tax === 'function') {
                return l.get_price_with_tax();
            }
            if (typeof l.get_all_prices === 'function') {
                const prices = l.get_all_prices();
                if (prices && typeof prices.priceWithTax === 'number') {
                    return prices.priceWithTax;
                }
            }
            // Final fallback: stored field (always available, set at line creation)
            return l.price_subtotal_incl ?? 0;
        };

        const grossTotal = productLines.reduce(
            (s, l) => s + Math.max(0, getLineTaxTotal(l)), 0
        );

        console.log(
            "[loyalty_scale] _getNetEarningScaleFactor"
            + " | product_lines=" + productLines.length
            + " | reward_lines=" + rewardLines.length
            + " | grossTotal=" + grossTotal.toFixed(4)
        );

        if (grossTotal <= 0) {
            if (productLines.length === 0) {
                // No product lines at all — no earning base
                console.log("[loyalty_scale] no product lines → scale=0 (no earning base)");
                return 0;
            }
            // Product lines exist but all returned 0 — price API could not be resolved.
            // Conservative: do not zero earning; let Odoo handle this normally.
            console.warn(
                "[loyalty_scale] product lines exist (" + productLines.length + ")" +
                " but grossTotal=0 — price API could not be resolved for any line." +
                " Defaulting to scale=1 (conservative, no adjustment)."
            );
            return 1;
        }

        const totalDeductions = rewardLines.reduce(
            (s, l) => s + Math.abs(getLineTaxTotal(l)), 0
        );

        const scale = Math.max(0, Math.min(1, (grossTotal - totalDeductions) / grossTotal));

        console.log(
            "[loyalty_scale] _getNetEarningScaleFactor"
            + " | totalDeductions=" + totalDeductions.toFixed(4)
            + " | scale=" + scale.toFixed(6)
        );

        return scale;
    },

    /**
     * Compute the points contributed exclusively by unit-based rules in a program.
     * These are discount-immune (based on physical quantity, not monetary value)
     * and must NOT be scaled by the net deduction factor.
     *
     * @param {Object} program - loyalty.program record
     * @returns {number}
     */
    _computeUnitOnlyPoints(program) {
        let pts = 0;
        const orderlines = this.get_orderlines();

        for (const rule of program.rule_ids) {
            if (rule.reward_point_mode !== 'unit') continue;

            for (const line of orderlines) {
                if (line.is_reward_line) continue;
                if (line.ignoreLoyaltyPoints?.({ program })) continue;

                if (rule.any_product || rule.validProductIds?.has(line.product_id?.id)) {
                    pts += rule.reward_point_amount * Math.abs(
                        line.get_quantity ? line.get_quantity() : (line.qty || 0)
                    );
                }
            }
        }

        return pts;
    },

    /**
     * Aggregates "points won" across all loyalty programs for display in the
     * LoyaltyPointsWidget. Reads from getLoyaltyPoints() which in turn reads
     * from uiState.couponPointChanges (populated by our patched pointsForPrograms).
     *
     * Called by: loyalty_points_widget.js (OrderSummary getter)
     *
     * @returns {number} total whole-number points to earn on this order
     */
    getNetLoyaltyPoints() {
        const summaries = this.getLoyaltyPoints();
        const total = summaries.reduce((sum, entry) => sum + (entry.points?.won || 0), 0);
        return Math.max(0, Math.round(total));
    },

    // ─────────────────────────────────────────────────────────────────────────
    // No-pre-spend guard: cap redemption to existing DB balance only
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Override Odoo's available-points calculation to EXCLUDE the earning
     * contribution of the current order.
     *
     * Odoo standard (pos_order.js ~L462):
     *   points = dbCoupon.points + pe.points (earning this order) - reward_line_costs
     *
     * This override:
     *   points = dbCoupon.points - reward_line_costs
     *
     * Why: customers must not be able to redeem points they have not yet earned.
     *   The display (getLoyaltyPoints / LoyaltyPointsWidget) still shows the
     *   projected earning — the cap only applies to what can be redeemed now.
     *
     * Used by:
     *   • getClaimableRewards() — which reward buttons are shown
     *   • _applyReward()        — guard before reward line is created
     *
     * @param {number} coupon_id
     * @returns {number} points available for redemption right now
     */
    _getRealCouponPoints(coupon_id) {
        // 1. Get Odoo's full result (db + earning + reward-line deductions)
        const standardPoints = super._getRealCouponPoints(...arguments);

        // 2. Find how much earning was baked in by couponPointChanges
        let earningAdded = 0;
        Object.values(this.uiState.couponPointChanges).some((pe) => {
            if (pe.coupon_id !== coupon_id) return false;

            const program = this.models["loyalty.program"].get(pe.program_id);
            // Mirrors Odoo's own guard: "future" programs never add earning here
            if (program?.applies_on !== "future" && pe.points > 0) {
                earningAdded = pe.points;
            }
            return true; // stop after first match (coupon appears once)
        });

        // 3. Subtract the earning to get the "existing balance only" figure
        const cappedPoints = Math.max(0, standardPoints - earningAdded);

        const dbBalance = this.models["loyalty.card"].get(coupon_id)?.points ?? "?";
        console.log(
            "[loyalty_no_pre_spend] _getRealCouponPoints" +
            " | coupon=" + coupon_id +
            " | db_balance=" + dbBalance +
            " | earning_this_order=" + earningAdded +
            " | odoo_standard=" + standardPoints +
            " | capped_to_existing=" + cappedPoints
        );

        return cappedPoints;
    },
});
