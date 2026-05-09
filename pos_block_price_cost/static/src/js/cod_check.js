/** @odoo-module **/

/**
 * cod_check.js
 * ─────────────
 * Patches ProductScreen.onCodButtonClick (added by pos_cod's CodButton.js).
 *
 * When the cashier clicks the COD button on the Product Screen, this module
 * intercepts BEFORE the CodWizard dialog opens:
 *   1. Collects all positive-qty order lines and their tax-inclusive prices.
 *   2. Calls pos.session.validate_cod_below_cost via ORM RPC.
 *      The server compares each line's selling price (incl. VAT) against its
 *      cost price (standard_price + applicable taxes).
 *   3. If any line is priced below cost:
 *        → opens CodBelowCostDialog showing product-level details
 *        → blocks the dispatch — CodWizard never opens
 *   4. If all lines are at or above cost, proceeds to super.onCodButtonClick()
 *      which opens the wizard as normal.
 *
 * Refund lines (qty ≤ 0) are always exempt.
 * Relies on pos_cod loading first (pos_cod is listed in module depends).
 * Does NOT alter validateOrder or any other existing check.
 */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

console.log("pos_block_price_cost: cod_check.js loaded");

// ── Error-detail dialog ───────────────────────────────────────────────────────

export class CodBelowCostDialog extends Component {
    static template = "pos_block_price_cost.CodBelowCostDialog";
    static components = { Dialog };
    static props = {
        offenders: Array,
        onDismiss: Function,
        close: Function,          // injected by the dialog service
    };

    onOk() {
        this.props.close();       // removes the dialog
        this.props.onDismiss();   // resolves the blocking promise in onCodButtonClick
    }
}

// ── ProductScreen patch ───────────────────────────────────────────────────────
// Loads AFTER pos_cod's CodButton.js (guaranteed by the pos_cod dependency),
// so super.onCodButtonClick() correctly calls the CodWizard dispatch flow.

patch(ProductScreen.prototype, {

    setup(...args) {
        super.setup(...args);
        this._codCheckOrm    = useService("orm");
        this._codCheckDialog = useService("dialog");
    },

    // ── Intercept COD button click ────────────────────────────────────────────

    async onCodButtonClick() {
        console.log(
            "pos_block_price_cost [cod_check]: COD button clicked — running below-cost check"
        );

        const blocked = await this._codCheckBelowCostForCod();

        if (blocked) {
            console.log(
                "pos_block_price_cost [cod_check]: COD dispatch BLOCKED — below-cost items found"
            );
            return;
        }

        // All lines are at or above cost — hand off to CodButton's wizard flow
        return super.onCodButtonClick(...arguments);
    },

    // ── Gather lines → RPC → show dialog if needed ───────────────────────────

    async _codCheckBelowCostForCod() {
        const order = this.currentOrder;
        if (!order) return false;

        // Dual-API: SaaS getOrderlines() / Enterprise get_orderlines() / reactive .orderlines
        const allLines = order.getOrderlines
            ? order.getOrderlines()
            : (order.get_orderlines ? order.get_orderlines() : order.orderlines || []);

        const lines = [];

        for (const line of allLines) {
            // ── Resolve quantity ──────────────────────────────────────────────
            const qty = line.getQuantity
                ? line.getQuantity()
                : (line.get_quantity ? line.get_quantity() : line.qty ?? 0);

            if (qty <= 0) continue;   // skip refunds / zero-qty lines

            // ── Resolve product ───────────────────────────────────────────────
            const product = line.getProduct
                ? line.getProduct()
                : (line.get_product ? line.get_product() : null);

            if (!product || !product.standard_price) continue;

            // ── Tax-inclusive selling price (per unit) ────────────────────────
            // get_all_prices(1) returns per-unit prices with discount already applied.
            // priceWithTax is the definitive customer-facing price inclusive of VAT.
            let priceInclTax = 0;
            try {
                priceInclTax = line.get_all_prices(1).priceWithTax;
            } catch (_) {
                continue;   // line not yet fully initialised
            }

            // ── Tax IDs (after fiscal-position mapping) ───────────────────────
            const rawTaxes = line.get_taxes ? line.get_taxes() : [];
            const taxIds   = (rawTaxes || []).map(t => t.id);

            lines.push({
                product_id: product.id,
                price_incl: priceInclTax,
                tax_ids:    taxIds,
            });
        }

        if (!lines.length) return false;

        // ── Server-side cost check ────────────────────────────────────────────
        let offenders = [];
        try {
            const sessionId = this.pos.session.id;
            offenders = await this._codCheckOrm.call(
                "pos.session",
                "validate_cod_below_cost",
                [[sessionId], lines]
            );
        } catch (err) {
            console.error(
                "pos_block_price_cost [cod_check]: RPC error during cost check →", err
            );
            return false;   // fail open — do not block on server error
        }

        if (!offenders.length) return false;

        console.warn(
            `pos_block_price_cost [cod_check]: ${offenders.length} line(s) below cost — blocking COD dispatch`
        );

        // ── Show error dialog and wait for dismissal ──────────────────────────
        await new Promise(resolve => {
            this._codCheckDialog.add(CodBelowCostDialog, {
                offenders,
                onDismiss: resolve,
            });
        });

        return true;   // blocked — caller should return without opening wizard
    },
});
