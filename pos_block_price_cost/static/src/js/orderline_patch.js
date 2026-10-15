/** @odoo-module **/

/**
 * orderline_patch.js
 * ───────────────────
 * Patches PosOrderline.prototype to detect in real-time when a line
 * goes below cost (on price change or discount change).
 *
 * Uses the same dual-API pattern (saas/legacy) as the proven working
 * implementation to handle both Odoo 18 SaaS and Enterprise builds.
 *
 * Behaviour:
 *   - Logs a console.warn when price drops below cost (badge turns red in UI)
 *   - Does NOT auto-reset the price (cashier can still try to proceed)
 *   - Hard block happens later at PaymentScreen.validateOrder / COD button (pos_restriction.js)
 *   - Refund / return lines (qty < 0) are always skipped
 */

import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { Orderline } from "@point_of_sale/app/generic_components/orderline/orderline";
import { patch } from "@web/core/utils/patch";

// Allow pcBelowCost through OWL's strict prop shape validator
Orderline.props.line.shape.pcBelowCost = { type: Boolean, optional: true };

console.log("pos_block_price_cost: orderline_patch.js loaded");

function getCostInclTax(line, cost) {
    const prices = line.get_all_prices(1);
    const taxMultiplier = prices.priceWithoutTax ? prices.priceWithTax / prices.priceWithoutTax : 1;
    return {
        costInclTax: cost * taxMultiplier,
        priceInclTax: prices.priceWithTax,
    };
}

patch(PosOrderline.prototype, {

    // ── Price setters ─────────────────────────────────────────────────────────

    set_unit_price(price) {
        const result = super.set_unit_price(...arguments);
        this._pcCheckBelowCost();
        return result;
    },

    // ── Discount setters ──────────────────────────────────────────────────────

    set_discount(discount) {
        const result = super.set_discount(...arguments);
        this._pcCheckBelowCost();
        return result;
    },

    // ── Core check ───────────────────────────────────────────────────────────

    _pcCheckBelowCost() {
        const qty = this.get_quantity ? this.get_quantity() : this.qty;
        if (qty < 0) return;   // skip refund lines

        const product = this.get_product ? this.get_product() : null;
        if (!product) return;

        const cost = product.standard_price || 0;
        if (cost <= 0) return;

        let prices;
        try {
            prices = getCostInclTax(this, cost);
        } catch (_) {
            return;
        }

        if (prices.priceInclTax < prices.costInclTax) {
            console.warn(
                `pos_block_price_cost: BELOW COST - ` +
                `VAT-inclusive selling=${prices.priceInclTax.toFixed(2)} ` +
                `< VAT-inclusive cost=${prices.costInclTax.toFixed(2)}`
            );
        }
    },

    // ── Expose below-cost flag through the display data for the XML badge ─────

    getDisplayData() {
        const data = super.getDisplayData(...arguments);
        const qty = this.get_quantity ? this.get_quantity() : this.qty;
        if (qty >= 0) {
            const product = this.get_product ? this.get_product() : null;
            const cost = product && product.standard_price || 0;
            if (cost > 0) {
                try {
                    const prices = getCostInclTax(this, cost);
                    data.pcBelowCost = prices.priceInclTax < prices.costInclTax;
                } catch (_) {
                    // orderline not fully initialised yet — skip
                }
            }
        }
        return data;
    },
});
