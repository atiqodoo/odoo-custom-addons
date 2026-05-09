/** @odoo-module **/

/**
 * global_discount_check.js
 * ─────────────────────────
 * Patches PaymentScreen.validateOrder AND ProductScreen.onCodButtonClick to
 * block when a global discount product line reduces the order total by more
 * than the total tax-inclusive profit of all real product lines.
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
 *
 * COD check (ProductScreen.onCodButtonClick):
 *   Same profit-vs-discount logic runs when the cashier clicks the COD button.
 *   Loaded BEFORE cod_check.js → runs as an inner patch (after cod_check.js's
 *   below-cost guard but before the CodWizard opens).
 */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { ManagerPinDialog } from "./manager_pin_dialog";

console.log("pos_block_price_cost: global_discount_check.js loaded");

// ── Resolve Many2one field to a plain integer ID ──────────────────────────────
// pos.config.discount_product_id storage format varies across Odoo builds:
//   plain integer, [id, name] tuple, or reactive object with .id property.
function _resolveId(val) {
    if (!val && val !== 0) return null;
    if (Array.isArray(val))      return val[0];
    if (typeof val === 'object') return val.id || null;
    return val;
}

// ── Compute globalDiscountAmount and totalProfit for any order ────────────────
function _computeDiscountAndProfit(order, discountProductId) {
    // Odoo 18: getOrderlines() (SaaS) | get_orderlines() (Enterprise) | .orderlines (reactive)
    const lines = order.getOrderlines
        ? order.getOrderlines()
        : (order.get_orderlines
            ? order.get_orderlines()
            : [...(order.orderlines || [])]);

    let globalDiscountAmount = 0;
    let totalProfit          = 0;

    for (const line of lines) {
        const product = line.getProduct
            ? line.getProduct()
            : (line.get_product ? line.get_product() : null);

        if (!product) continue;

        let priceWithTax, priceWithoutTax;
        try {
            const prices    = line.get_all_prices(1);
            priceWithTax    = prices.priceWithTax;
            priceWithoutTax = prices.priceWithoutTax;
        } catch (_) {
            continue;
        }

        const qty = line.getQuantity
            ? line.getQuantity()
            : (line.get_quantity ? line.get_quantity() : line.qty);

        const isDiscountLine = discountProductId !== null
            ? (product.id === discountProductId)
            : (product.standard_price === 0 && priceWithTax < 0 && qty >= 0);

        if (isDiscountLine) {
            globalDiscountAmount += Math.abs(priceWithTax * qty);
            continue;
        }

        if (qty < 0) continue;

        const cost          = product.standard_price || 0;
        const taxMultiplier = (priceWithoutTax && priceWithoutTax !== 0)
            ? priceWithTax / priceWithoutTax
            : 1;
        const costInclTax   = cost * taxMultiplier;

        totalProfit += (priceWithTax - costInclTax) * qty;
    }

    return { globalDiscountAmount, totalProfit };
}

// ── Show ManagerPinDialog via an explicit dialog service ──────────────────────
// Used by the ProductScreen patch which cannot call this._pcRequestManagerOverride
// (that method only exists on PaymentScreen via pos_restriction.js).
function _openManagerPinDialog(dialogService, invalidLines) {
    return new Promise((resolve) => {
        dialogService.add(ManagerPinDialog, {
            invalidLines,
            onConfirm: (employeeName) => {
                console.log(
                    `pos_block_price_cost [global_discount_check]: Override granted by '${employeeName}'`
                );
                resolve(true);
            },
            onCancel: () => resolve(false),
        });
    });
}

// ── PaymentScreen patch ───────────────────────────────────────────────────────

patch(PaymentScreen.prototype, {

    async validateOrder(isForceValidate) {
        const order = this.currentOrder;
        if (!order) return super.validateOrder(...arguments);

        const discountProductId = _resolveId(
            this.pos && this.pos.config && this.pos.config.discount_product_id
        );

        const { globalDiscountAmount, totalProfit } =
            _computeDiscountAndProfit(order, discountProductId);

        if (globalDiscountAmount <= 0) {
            return super.validateOrder(...arguments);
        }

        console.log(
            `pos_block_price_cost [global_discount_check]: ` +
            `globalDiscountAmt=${globalDiscountAmount.toFixed(2)}  ` +
            `totalProfitInclTax=${totalProfit.toFixed(2)}`
        );

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

        return super.validateOrder(...arguments);
    },
});

// ── ProductScreen patch — COD button global-discount guard ────────────────────
// Intercepts onCodButtonClick BEFORE the CodWizard opens.
// Load order: global_discount_check.js (inner) < cod_check.js (outer).
// Execution order on click: cod_check below-cost guard → this guard → CodWizard.

patch(ProductScreen.prototype, {

    setup(...args) {
        super.setup(...args);
        this._gdCodDialog = useService("dialog");
    },

    async onCodButtonClick() {
        console.log("pos_block_price_cost [global_discount_check/COD]: onCodButtonClick — patch reached");

        const order = this.currentOrder;
        if (!order) return super.onCodButtonClick(...arguments);

        const discountProductId = _resolveId(
            this.pos && this.pos.config && this.pos.config.discount_product_id
        );

        console.log(
            `pos_block_price_cost [global_discount_check/COD]: discountProductId=${discountProductId}`
        );

        let globalDiscountAmount, totalProfit;
        try {
            ({ globalDiscountAmount, totalProfit } =
                _computeDiscountAndProfit(order, discountProductId));
        } catch (err) {
            console.error(
                "pos_block_price_cost [global_discount_check/COD]: _computeDiscountAndProfit threw →", err
            );
            return super.onCodButtonClick(...arguments);
        }

        console.log(
            `pos_block_price_cost [global_discount_check/COD]: ` +
            `globalDiscountAmt=${globalDiscountAmount.toFixed(2)}  ` +
            `totalProfitInclTax=${totalProfit.toFixed(2)}`
        );

        if (globalDiscountAmount <= 0) {
            return super.onCodButtonClick(...arguments);
        }

        console.log(
            `pos_block_price_cost [global_discount_check/COD]: ` +
            `discount detected — evaluating profit...`
        );

        if (globalDiscountAmount > totalProfit) {
            const discountFmt = globalDiscountAmount.toFixed(2);
            const profitFmt   = totalProfit.toFixed(2);

            const summary = [
                _t("Global Discount Amount") + `: ${discountFmt}`,
                _t("Total Order Profit (incl. VAT)") + `: ${profitFmt}`,
                _t("The discount exceeds total profit — COD order results in a net loss."),
            ];

            console.warn(
                `pos_block_price_cost [global_discount_check/COD]: BLOCKED — ` +
                `globalDiscountAmt (${discountFmt}) > totalProfitInclTax (${profitFmt})`
            );

            const granted = await _openManagerPinDialog(this._gdCodDialog, summary);

            if (!granted) {
                console.log(
                    "pos_block_price_cost [global_discount_check/COD]: " +
                    "Override DENIED or cancelled — COD dispatch blocked"
                );
                return;
            }

            console.log(
                "pos_block_price_cost [global_discount_check/COD]: Override GRANTED — proceeding with COD"
            );
        }

        return super.onCodButtonClick(...arguments);
    },
});
