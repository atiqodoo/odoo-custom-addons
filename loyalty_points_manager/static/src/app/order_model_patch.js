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

        const scaleFactor = this._getNetEarningScaleFactor();

        // ── Zero-payment guard ────────────────────────────────────────────────
        // If the entire order is covered by loyalty redemption (scale = 0),
        // no money changes hands at all.  Earning 0 points regardless of
        // rule type — including unit-based rules which are otherwise
        // discount-immune (they would survive the proportional scaling below).
        //
        // This prevents a customer from "gaming" the program by spending just
        // enough points to zero the bill while still earning full unit points.
        if (scaleFactor <= 0) {
            for (const program of programs) {
                if (!result[program.id]?.length) continue;
                result[program.id] = result[program.id].map((e) => ({ ...e, points: 0 }));
            }
            console.log(
                "[loyalty_zero_pay] pointsForPrograms: scale=0 (fully covered by redemption)" +
                " → earning zeroed on all programs"
            );
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
     * @returns {number} value in [0, 1]
     */
    _getNetEarningScaleFactor() {
        const allLines = this.get_orderlines();
        const productLines = allLines.filter((l) => !l.is_reward_line);
        const rewardLines  = allLines.filter((l) => l.is_reward_line);

        const grossTotal = productLines.reduce(
            (s, l) => s + (l.get_price_with_tax ? l.get_price_with_tax() : 0), 0
        );
        if (grossTotal <= 0) return 1;

        const totalDeductions = rewardLines.reduce(
            (s, l) => s + Math.abs(l.get_price_with_tax ? l.get_price_with_tax() : 0), 0
        );

        return Math.max(0, Math.min(1, (grossTotal - totalDeductions) / grossTotal));
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
