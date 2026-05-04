/** @odoo-module **/

/**
 * pos_restriction.js
 * ───────────────────
 * Patches PaymentScreen.validateOrder.
 * Uses proven dual-API (saas/legacy) pattern for orderlines iteration.
 *
 * If any positive-qty line is priced below cost:
 *   → shows ManagerPinDialog (manager must enter PIN to override)
 *   → if PIN denied or cancelled → blocks validation
 *   → if PIN accepted → proceeds to super.validateOrder
 *
 * Refund lines (qty < 0) are always exempt.
 */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ManagerPinDialog } from "./manager_pin_dialog";

console.log("pos_block_price_cost: pos_restriction.js loaded");

patch(PaymentScreen.prototype, {

    async validateOrder(isForceValidate) {
        const order = this.currentOrder;
        if (!order) return super.validateOrder(...arguments);

        // ── Collect offending lines using dual-API ────────────────────────────
        // Support both getOrderlines() (SaaS) and get_orderlines() (Enterprise)
        const lines = order.getOrderlines
            ? order.getOrderlines()
            : order.get_orderlines();

        const offenders = [];

        for (const line of lines) {
            // ── Skip refunds ──────────────────────────────────────────────────
            const qty = line.getQuantity
                ? line.getQuantity()
                : (line.get_quantity ? line.get_quantity() : line.qty);

            if (qty < 0) continue;

            // ── Get product ───────────────────────────────────────────────────
            const product = line.getProduct
                ? line.getProduct()
                : (line.get_product ? line.get_product() : null);

            if (!product) continue;

            const cost = product.standard_price || 0;
            if (cost <= 0) continue;

            // ── Effective ex-VAT price (apples-to-apples vs standard_price) ──────
            let effectiveExVat;
            try {
                effectiveExVat = line.get_all_prices(1).priceWithoutTax;
            } catch (_) {
                continue;
            }

            if (effectiveExVat < cost) {
                offenders.push(
                    `${product.display_name}  —  ` +
                    `${_t("Cost")}: ${cost.toFixed(2)}  |  ` +
                    `${_t("Selling (ex-VAT)")}: ${effectiveExVat.toFixed(2)}`
                );
            }
        }

        // ── If offenders found → request manager PIN ──────────────────────────
        if (offenders.length > 0) {
            console.warn(
                `pos_block_price_cost: ${offenders.length} below-cost line(s) ` +
                `— requesting manager PIN`
            );

            const granted = await this._pcRequestManagerOverride(offenders);

            if (!granted) {
                console.log(
                    "pos_block_price_cost: Override DENIED or cancelled — validation blocked"
                );
                return false;
            }

            console.log("pos_block_price_cost: Override GRANTED — proceeding");
        }

        return super.validateOrder(...arguments);
    },

    // ── Show manager PIN dialog and await result ──────────────────────────────

    _pcRequestManagerOverride(invalidLines) {
        return new Promise((resolve) => {
            this.dialog.add(ManagerPinDialog, {
                invalidLines,
                onConfirm: (employeeName) => {
                    console.log(
                        `pos_block_price_cost: Override granted by '${employeeName}'`
                    );
                    resolve(true);
                },
                onCancel: () => {
                    resolve(false);
                },
            });
        });
    },
});