/** @odoo-module **/

/**
 * orderline_redemption_patch.js
 *
 * Enables partial loyalty redemption editing through a SINGLE patch on
 * OrderSummary._setValue — the UI entry point for all numpad input.
 *
 * WHY NOT patch PosOrderline.set_quantity / set_unit_price:
 *   Those methods are called internally by the POS reward engine (updateRewards,
 *   _applyReward, _finalizeValidation) dozens of times per order, not just on
 *   cashier input.  Putting a balance guard there fires on EVERY internal call
 *   with partnerPoints = 0 (loyalty card not resolved in that context) and
 *   crashes payment finalization.  The model layer must NEVER block the POS
 *   reward engine's own calls.
 *
 * CORRECT ARCHITECTURE:
 *   ┌── Cashier types number on numpad while reward line selected
 *   │       OrderSummary._setValue(val)           ← only user-facing entry point
 *   │           ├─ Is loyalty reward line? → treat val as POINTS TO REDEEM
 *   │           │       validate: requestedPoints ≤ effectiveAvailable
 *   │           │       apply:    _applyPartialRedemption(line, points)
 *   │           │           price_unit = -(points × KES_per_point)
 *   │           │           points_cost = points
 *   │           │           qty stays 1 (no fractional quantities shown)
 *   │           │       FAIL → AlertDialog, return (do nothing)
 *   │           └─ Everything else → super._setValue (pos_loyalty → base)
 *   │
 *   └── Internal POS calls (updateRewards, _applyReward, finalization)
 *           set_quantity() called directly  ← NO guard, never blocked
 *
 * Why price_unit, not qty:
 *   The old approach (set_quantity to a fraction like 0.37) had two bugs:
 *     1. Visually confusing — cashier sees "qty: 0.37" on a discount line
 *     2. points_cost was never updated — backend still saw the full cost
 *   Changing price_unit keeps qty=1 and produces a clean KES discount amount.
 *   points_cost is updated so the backend sees exactly what was requested.
 *
 * KES-per-point ratio stability:
 *   kesPerPoint = |price_unit| / points_cost  (for qty=1)
 *   This ratio is preserved when we write both fields together, so intermediate
 *   keystrokes (typing "5" then "0" to get "50") always produce the right result.
 *
 * Do NOT call updateRewards() after editing:
 *   updateRewards() re-runs Odoo's reward engine which auto-reapplies the reward
 *   at the maximum applicable amount, overwriting the cashier's edit immediately.
 *
 * Validation policy (matches order_model_patch._getRealCouponPoints):
 *   Maximum redeemable = card.points (DB balance) − costs of OTHER reward lines
 *   already on this order for the same coupon.
 *   Current-order EARNING points are NOT counted — no pre-spending.
 *
 * Backend safety net:
 *   models/pos_order_override.py re-validates using the updated points_cost value.
 */

import { patch } from "@web/core/utils/patch";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(OrderSummary.prototype, {

    /**
     * Intercept numpad input on loyalty discount reward lines.
     *
     * The typed value is interpreted as POINTS TO REDEEM (not qty, not KES).
     * Conversion to KES discount is handled by _applyPartialRedemption().
     */
    _setValue(val) {
        const line = this.currentOrder?.get_selected_orderline();

        console.log(
            "[loyalty_partial] _setValue" +
            " | val=" + JSON.stringify(val) +
            " | is_reward=" + (line?.is_reward_line ?? false) +
            " | reward_id=" + (line?.reward_id?.id ?? "none") +
            " | coupon_id=" + (line?.coupon_id?.id ?? "none") +
            " | current price_unit=" + (line?.price_unit ?? "n/a") +
            " | current points_cost=" + (line?.points_cost ?? "n/a")
        );

        if (
            line?.is_reward_line &&
            line.reward_id &&
            !line.isGiftCardOrEWalletReward?.() &&
            val !== '' && val !== 'remove'
        ) {
            const requestedPoints = parseFloat(val);

            if (!isNaN(requestedPoints) && requestedPoints > 0) {
                if (this._isPartialRedemptionAllowed(line, requestedPoints)) {
                    this._applyPartialRedemption(line, requestedPoints);
                }
            } else {
                console.log("[loyalty_partial] _setValue: skipping — not a positive number:", val);
            }

            return; // Never fall through to super for reward-line numeric edits
        }

        return super._setValue(val);
    },

    // ─────────────────────────────────────────────────────────────────────────
    // Validation
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Check whether redeeming `requestedPoints` stays within the customer's
     * current DB balance (no pre-spending of current-order earning).
     *
     * effectiveAvailable = card.points (DB) − costs of OTHER reward lines
     *                      already on this order for the same coupon.
     *
     * @param {PosOrderline} line           - selected reward orderline
     * @param {number}        requestedPoints - points cashier wants to redeem
     * @returns {boolean}
     */
    _isPartialRedemptionAllowed(line, requestedPoints) {
        const couponId = line.coupon_id?.id;
        if (!couponId) {
            console.log("[loyalty_partial] no couponId — allowing (backend will check)");
            return true;
        }

        const card = this.pos.models?.['loyalty.card']?.get(couponId);
        if (!card) {
            console.log("[loyalty_partial] card not in cache (coupon=" + couponId + ") — allowing");
            return true;
        }

        const dbPoints = card.points || 0;

        // Subtract costs of OTHER reward lines for the same coupon on this order
        let otherRewardCosts = 0;
        for (const ol of this.currentOrder.get_orderlines()) {
            if (ol.is_reward_line && ol.coupon_id?.id === couponId && ol !== line) {
                otherRewardCosts += ol.points_cost || 0;
            }
        }
        const effectiveAvailable = Math.max(0, dbPoints - otherRewardCosts);

        console.log(
            "[loyalty_partial] _isPartialRedemptionAllowed" +
            " | coupon=" + couponId +
            " | db_points=" + dbPoints +
            " | other_reward_costs=" + otherRewardCosts +
            " | effective_available=" + effectiveAvailable +
            " | requested=" + requestedPoints.toFixed(2)
        );

        if (requestedPoints > effectiveAvailable + 0.001) {
            console.warn(
                "[loyalty_partial] BLOCKED: " + requestedPoints.toFixed(2) +
                " > effective_available=" + effectiveAvailable
            );
            this.dialog.add(AlertDialog, {
                title: _t("Redemption Exceeds Balance"),
                body: _t(
                    "Cannot apply %(new)s points — customer only has %(avail)s points available.",
                    {
                        new:   requestedPoints.toFixed(0),
                        avail: effectiveAvailable.toFixed(0),
                    }
                ),
            });
            return false;
        }

        console.log("[loyalty_partial] ALLOWED: " + requestedPoints.toFixed(2) + " ≤ " + effectiveAvailable);
        return true;
    },

    // ─────────────────────────────────────────────────────────────────────────
    // Application: price_unit + points_cost (NOT qty)
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Apply a partial redemption by updating price_unit and points_cost.
     *
     * Changing price_unit (not qty) keeps the quantity at 1 so the cashier
     * sees a clean "1 × -50.00 KSh" line instead of "0.37 × -135.00 KSh".
     * Updating points_cost ensures the backend deducts exactly the right points.
     *
     * KES-per-point ratio is derived from the line's own state:
     *   kesPerPoint = (qty × |price_unit|) / points_cost
     * This ratio is self-stable: after each intermediate keystroke we write
     * both price_unit and points_cost, so the ratio stays constant.
     *
     * Example (1 pt = 1 KES, auto-applied 135 pts):
     *   state:  qty=1, price_unit=-135, points_cost=135
     *   type "5"  → kesPerPoint=1, newPU=-5,  cost=5
     *   type "50" → kesPerPoint=5/5=1, newPU=-50, cost=50  ✓
     *
     * @param {PosOrderline} line   - the reward line being edited
     * @param {number}        points - validated points to redeem
     */
    _applyPartialRedemption(line, points) {
        const existingCost  = line.points_cost || 0;
        const existingQty   = Math.abs(
            typeof line.get_quantity === 'function' ? line.get_quantity() : (line.qty || 1)
        );
        const existingPU    = line.price_unit || 0;                      // negative for discounts
        const totalKES      = existingQty * Math.abs(existingPU);        // total KES discount on the line now

        // ── KES-per-point rate ───────────────────────────────────────────────
        // Priority 1: reward record's authoritative field
        const rewardDPP = line.reward_id?.discount_per_point || 0;
        let kesPerPoint;
        if (rewardDPP > 0) {
            kesPerPoint = rewardDPP;
            console.log("[loyalty_partial] kesPerPoint from reward.discount_per_point = " + kesPerPoint);
        } else if (existingCost > 0 && totalKES > 0) {
            // Derived from line's own state — stable across intermediate keystrokes
            kesPerPoint = totalKES / existingCost;
            console.log(
                "[loyalty_partial] kesPerPoint derived: " + totalKES.toFixed(2) +
                " KES / " + existingCost + " pts = " + kesPerPoint.toFixed(4)
            );
        } else {
            kesPerPoint = 1; // last resort: 1 pt = 1 KES
            console.log("[loyalty_partial] kesPerPoint fallback = 1");
        }

        const newDiscountKES = points * kesPerPoint;
        const discountSign   = existingPU <= 0 ? -1 : 1; // discount lines are negative
        const newPriceUnit   = discountSign * newDiscountKES;

        console.log(
            "[loyalty_partial] _applyPartialRedemption" +
            " | " + points + " pts × " + kesPerPoint.toFixed(4) + " KES/pt" +
            " = " + newDiscountKES.toFixed(2) + " KES" +
            " | old: qty=" + existingQty + " PU=" + existingPU.toFixed(2) + " cost=" + existingCost +
            " | new: PU=" + newPriceUnit.toFixed(2) + " cost=" + points
        );

        // ── Write both fields atomically ─────────────────────────────────────
        // price_unit drives what the cashier sees (KES discount on the line)
        // points_cost is what the backend reads to count redeemed points
        if (typeof line.set_unit_price === 'function') {
            line.set_unit_price(newPriceUnit);
        } else {
            line.price_unit = newPriceUnit;
        }
        line.points_cost = points;

        // ── Normalize qty to 1 if needed (keeps display clean) ───────────────
        // Discount lines almost always start at qty=1; normalise just in case.
        if (existingQty !== 1) {
            console.log("[loyalty_partial] normalizing qty " + existingQty + " → 1 (price_unit already adjusted)");
            if (typeof line.set_quantity === 'function') {
                const sign = (typeof line.get_quantity === 'function' ? line.get_quantity() : 1) < 0 ? -1 : 1;
                line.set_quantity(sign * 1);
            }
        }

        // Do NOT call this.pos.updateRewards() — it would re-apply the reward
        // at maximum points, immediately overwriting the cashier's edit.
    },
});
