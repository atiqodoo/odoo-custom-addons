/** @odoo-module **/

/**
 * global_discount_check.js
 * ─────────────────────────
 * Patches PaymentScreen.validateOrder to block validation when a global
 * discount product line (e.g. "GENERAL DISCOUNT APPLIED") reduces the
 * order total by more than the total tax-inclusive profit of all real
 * product lines.
 *
 * How the global discount is detected
 * ─────────────────────────────────────
 * The global discount in this POS is a special product line added to
 * the order — NOT an order.discount_percent field.  That line has:
 *   • product.id  === pos.config.discount_product_id   (primary check)
 *   • price_unit  < 0   (negative — it subtracts from the total)
 *   • standard_price === 0   (the discount product itself carries no cost)
 *
 * Fallback heuristic (used only when config ID is unavailable):
 *   negative priceWithTax  +  standard_price === 0  +  qty >= 0
 *
 * Tax-inclusive calculation (selling prices are always tax-inclusive)
 * ────────────────────────────────────────────────────────────────────
 *   taxMultiplier     = priceWithTax / priceWithoutTax   (per real product)
 *   costInclTax       = standard_price × taxMultiplier
 *   lineProfitInclTax = (priceWithTax − costInclTax) × qty
 *   totalProfit       = Σ lineProfitInclTax   (real lines, qty > 0 only)
 *
 *   globalDiscountAmt = Σ |priceWithTax × qty|  of all discount product lines
 *
 *   BLOCK if: globalDiscountAmt > totalProfit
 *
 * Numerical example (from live order log):
 *   Product  priceWithTax=2650  standard_price=2151  taxMultiplier=1.16
 *   costInclTax = 2151 × 1.16 = 2495.16
 *   lineProfit  = (2650 − 2495.16) × 1 = 154.84
 *   discountAmt = |−795 × 1| = 795
 *   795 > 154.84  → BLOCK ✓
 *
 * Refund lines (qty < 0) are always exempt.
 * Loaded AFTER pos_restriction.js → outermost patch, this check runs first.
 * Reuses _pcRequestManagerOverride() defined by pos_restriction.js.
 */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

console.log("pos_block_price_cost: global_discount_check.js loaded");

// ── Resolve Many2one field to a plain integer ID ──────────────────────────────
// pos.config.discount_product_id storage format varies across Odoo builds:
//   plain integer, [id, name] tuple, or reactive object with .id property.
function _resolveId(val) {
    if (!val && val !== 0) return null;
    if (Array.isArray(val))         return val[0];
    if (typeof val === 'object')    return val.id || null;
    return val;
}

patch(PaymentScreen.prototype, {

    async validateOrder(isForceValidate) {
        const order = this.currentOrder;
        if (!order) return super.validateOrder(...arguments);

        // ── Resolve discount product ID from POS config ───────────────────────
        const discountProductId = _resolveId(
            this.pos && this.pos.config && this.pos.config.discount_product_id
        );

        // ── Collect lines (dual-API: SaaS getOrderlines / Enterprise get_orderlines)
        const lines = order.getOrderlines
            ? order.getOrderlines()
            : order.get_orderlines();

        let globalDiscountAmount = 0;  // absolute tax-inclusive value of discount lines
        let totalProfit          = 0;  // Σ (priceWithTax − costInclTax) × qty

        for (const line of lines) {

            // ── Resolve product ───────────────────────────────────────────────
            const product = line.getProduct
                ? line.getProduct()
                : (line.get_product ? line.get_product() : null);

            if (!product) continue;

            // ── Resolve per-unit prices ───────────────────────────────────────
            // get_all_prices(1) → prices for qty=1, reflecting any per-line discount.
            let priceWithTax, priceWithoutTax;
            try {
                const prices = line.get_all_prices(1);
                priceWithTax    = prices.priceWithTax;
                priceWithoutTax = prices.priceWithoutTax;
            } catch (_) {
                continue;  // line not yet fully initialised
            }

            // ── Resolve quantity ──────────────────────────────────────────────
            const qty = line.getQuantity
                ? line.getQuantity()
                : (line.get_quantity ? line.get_quantity() : line.qty);

            // ── Detect discount product line ──────────────────────────────────
            // Primary:  product.id matches the configured discount_product_id
            // Fallback: negative selling price + zero cost (config unavailable)
            const isDiscountLine = discountProductId !== null
                ? (product.id === discountProductId)
                : (product.standard_price === 0 && priceWithTax < 0 && qty >= 0);

            if (isDiscountLine) {
                // price_unit is negative by design; take absolute value
                globalDiscountAmount += Math.abs(priceWithTax * qty);
                continue;  // exclude from profit calculation
            }

            // ── Skip refund / return lines ────────────────────────────────────
            if (qty < 0) continue;

            // ── Tax-inclusive profit for this line ────────────────────────────
            // standard_price is ALWAYS tax-exclusive in Odoo.
            // Gross it up using this line's own tax ratio so both sides
            // of the subtraction are in the same tax-inclusive space.
            const cost = product.standard_price || 0;

            const taxMultiplier = (priceWithoutTax && priceWithoutTax !== 0)
                ? priceWithTax / priceWithoutTax
                : 1;

            const costInclTax = cost * taxMultiplier;

            totalProfit += (priceWithTax - costInclTax) * qty;
        }

        // ── No discount line on this order — nothing to check ─────────────────
        if (globalDiscountAmount <= 0) {
            return super.validateOrder(...arguments);
        }

        console.log(
            `pos_block_price_cost [global_discount_check]: ` +
            `globalDiscountAmt=${globalDiscountAmount.toFixed(2)}  ` +
            `totalProfitInclTax=${totalProfit.toFixed(2)}`
        );

        // ── Block when discount erases all profit ─────────────────────────────
        if (globalDiscountAmount > totalProfit) {

            const discountFmt = globalDiscountAmount.toFixed(2);
            const profitFmt   = totalProfit.toFixed(2);

            const summary = [
                _t("Global Discount Amount") + `: ${discountFmt}`,
                _t("Total Order Profit (incl. VAT)") + `: ${profitFmt}`,
                _t("The discount exceeds total profit — sale results in a net loss."),
            ];

            console.warn(
                `pos_block_price_cost [global_discount_check]: BLOCKED — ` +
                `globalDiscountAmt (${discountFmt}) > totalProfitInclTax (${profitFmt})`
            );

            const granted = await this._pcRequestManagerOverride(summary);

            if (!granted) {
                console.log(
                    "pos_block_price_cost [global_discount_check]: " +
                    "Override DENIED or cancelled — validation blocked"
                );
                return false;
            }

            console.log(
                "pos_block_price_cost [global_discount_check]: Override GRANTED — proceeding"
            );
        }

        // ── Pass through to pos_restriction.js per-line check ────────────────
        return super.validateOrder(...arguments);
    },
});
