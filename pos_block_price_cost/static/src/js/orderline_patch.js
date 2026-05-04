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
 *   - Shows a browser alert warning immediately when price drops below cost
 *   - Does NOT auto-reset the price (cashier is warned but can still try to proceed)
 *   - Hard block happens later at PaymentScreen.validateOrder (pos_restriction.js)
 *   - Refund / return lines (qty < 0) are always skipped
 */

import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { Orderline } from "@point_of_sale/app/generic_components/orderline/orderline";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// Allow pcBelowCost through OWL's strict prop shape validator
Orderline.props.line.shape.pcBelowCost = { type: Boolean, optional: true };

// Stored outside the reactive model to avoid OWL reactivity interference
const _pcAlertTimers = new WeakMap();

console.log("pos_block_price_cost: orderline_patch.js loaded");

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

    // ── Core check (debounced — fires 700 ms after last keystroke) ───────────

    _pcCheckBelowCost() {
        // Cancel any pending alert from the previous keystroke
        clearTimeout(_pcAlertTimers.get(this));
        _pcAlertTimers.delete(this);

        const qty = this.get_quantity ? this.get_quantity() : this.qty;
        if (qty < 0) return;   // skip refund lines

        const product = this.get_product ? this.get_product() : null;
        if (!product) return;

        const cost = product.standard_price || 0;
        if (cost <= 0) return;

        // Use ex-VAT unit price so we compare apples-to-apples with standard_price
        let effectiveExVat, priceWithTax, priceWithoutTax;
        try {
            const prices = this.get_all_prices(1);
            effectiveExVat = prices.priceWithoutTax;
            priceWithTax = prices.priceWithTax;
            priceWithoutTax = prices.priceWithoutTax;
        } catch (_) {
            return;
        }

        if (effectiveExVat < cost) {
            console.warn(
                `pos_block_price_cost: BELOW COST — ` +
                `ex-VAT effective=${effectiveExVat.toFixed(2)} < cost=${cost}`
            );
            // Show cost inclusive of VAT using the same tax ratio as the selling price
            const vatRatio = priceWithoutTax !== 0 ? priceWithTax / priceWithoutTax : 1;
            const costIncVat = cost * vatRatio;
            const msg = (
                "⚠ " + _t("Price Below Cost") + "\n\n" +
                product.display_name + "\n" +
                _t("Cost (inc. VAT): ") + costIncVat.toFixed(2) + "\n" +
                _t("Selling (inc. VAT): ") + priceWithTax.toFixed(2) + "\n\n" +
                _t("A manager PIN will be required to complete this sale.")
            );
            _pcAlertTimers.set(this, setTimeout(() => {
                _pcAlertTimers.delete(this);
                alert(msg);
            }, 30000));
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
                    const effectiveExVat = this.get_all_prices(1).priceWithoutTax;
                    data.pcBelowCost = effectiveExVat < cost;
                } catch (_) {
                    // orderline not fully initialised yet — skip
                }
            }
        }
        return data;
    },
});