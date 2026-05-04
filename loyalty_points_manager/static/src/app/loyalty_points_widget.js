/** @odoo-module **/

/**
 * loyalty_points_widget.js
 *
 * Adds a reactive "Points to Earn" display to the POS OrderSummary component.
 *
 * Approach:
 *   Rather than creating a standalone OWL sub-component (which requires
 *   patching the static `components` registry), we patch OrderSummary.prototype
 *   to expose computed getters.  An XML template extension (loyalty_points_widget.xml)
 *   then references these getters to render the display.
 *
 * Reactivity:
 *   `this.pos` in OrderSummary is made reactive by `usePos()` (set in setup()).
 *   Any getter that reads `this.currentOrder` (which reads `this.pos.get_order()`)
 *   is tracked by OWL's reactivity system — the template re-renders automatically
 *   whenever the order total, lines, or reward lines change.
 *
 * Dependency:
 *   `order_model_patch.js` must be loaded first (adds PosOrder.getNetLoyaltyPoints).
 *   Load order is guaranteed by the manifest's asset declaration sequence.
 */

import { patch } from "@web/core/utils/patch";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";

patch(OrderSummary.prototype, {

    /**
     * Returns the total loyalty points this order will earn using the
     * net-earning engine (post discount and redemption deductions).
     *
     * getNetLoyaltyPoints() is injected onto PosOrder by order_model_patch.js.
     * Falls back to 0 if there is no active order or no loyalty program.
     *
     * @returns {number} whole-number points
     */
    get netLoyaltyPoints() {
        const order = this.currentOrder;
        if (!order) return 0;
        if (typeof order.getNetLoyaltyPoints === 'function') {
            return order.getNetLoyaltyPoints();
        }
        return 0;
    },

    /**
     * True when there is a partner on the order AND the order will earn points.
     * Used in the XML template to conditionally show the widget.
     *
     * @returns {boolean}
     */
    get hasEarnablePoints() {
        const order = this.currentOrder;
        if (!order?.get_partner?.()) return false;
        return this.netLoyaltyPoints > 0;
    },
});
