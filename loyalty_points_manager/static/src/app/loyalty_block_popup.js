/** @odoo-module **/

/**
 * loyalty_block_popup.js
 *
 * Re-patches ControlButtons._applyReward to fix a missing `await` in Odoo's
 * pos_loyalty implementation that prevents our async unpaid_invoice_guard from
 * surfacing its error string to the cashier.
 *
 * ─── Root cause ──────────────────────────────────────────────────────────────
 *   pos_loyalty/control_buttons.js:176 calls:
 *       const result = order._applyReward(reward, coupon_id, args);
 *   without `await`.  Because our unpaid_invoice_guard makes _applyReward async,
 *   `result` is a Promise.  The subsequent `this.notification.add(result)` receives
 *   a Promise object — nothing useful is shown to the cashier.
 *
 * ─── Fix ─────────────────────────────────────────────────────────────────────
 *   This patch replaces _applyReward with a version that:
 *     1. `await`s order._applyReward() — waits for the async guard to resolve
 *     2. Shows an AlertDialog (modal) instead of a transient notification —
 *        the cashier cannot miss a modal and must explicitly dismiss it
 *
 * ─── Scope ───────────────────────────────────────────────────────────────────
 *   Only the discount/loyalty-redemption code path (the `else` branch) is
 *   changed.  The multi-product selection path and the free-product path are
 *   preserved exactly as pos_loyalty wrote them.
 */

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

console.log("[loyalty_block_popup] module loaded");

patch(ControlButtons.prototype, {

    /**
     * Apply a loyalty reward with correct async handling and proper error display.
     *
     * Replaces pos_loyalty's _applyReward wholesale so that order._applyReward
     * (which is async due to the unpaid_invoice_guard patch) is properly awaited
     * and errors are shown as modal AlertDialogs rather than transient toasts.
     *
     * Logic is identical to pos_loyalty's version except:
     *   - `await order._applyReward(...)` instead of plain call
     *   - error displayed via AlertDialog (modal) instead of notification.add()
     *
     * @override
     */
    async _applyReward(reward, coupon_id, potentialQty) {
        const order = this.pos.get_order();
        order.uiState.disabledRewards.delete(reward.id);

        console.log(
            "[loyalty_block_popup] _applyReward" +
            " | reward_id=" + (reward?.id ?? "?") +
            " | reward_type=" + (reward?.reward_type ?? "?") +
            " | coupon_id=" + coupon_id
        );

        const args = {};

        // ── Multi-product selection (unchanged from pos_loyalty) ──────────────
        if (reward.reward_type === "product" && reward.multi_product) {
            const productsList = reward.reward_product_ids.map((product_id) => ({
                id: product_id.id,
                label: product_id.display_name,
                item: product_id,
            }));
            const selectedProduct = await makeAwaitable(this.dialog, SelectionPopup, {
                title: _t("Please select a product for this reward"),
                list: productsList,
            });
            if (!selectedProduct) {
                return false;
            }
            args["product"] = selectedProduct;
        }

        // ── Free product reward path (unchanged from pos_loyalty) ─────────────
        if (
            (reward.reward_type == "product" && reward.program_id.applies_on !== "both") ||
            (reward.program_id.applies_on == "both" && potentialQty)
        ) {
            await this.pos.addLineToCurrentOrder(
                {
                    product_id: args["product"] || reward.reward_product_ids[0],
                    qty: potentialQty || 1,
                },
                {}
            );
            return true;
        }

        // ── Discount / loyalty redemption path — FIXED ────────────────────────
        // pos_loyalty calls order._applyReward without await; if the method is
        // async (our unpaid_invoice_guard makes it so), result is a Promise and
        // notification.add(Promise) shows nothing useful.  We await here.
        const result = await order._applyReward(reward, coupon_id, args);

        console.log(
            "[loyalty_block_popup] order._applyReward resolved" +
            " | result=" + (typeof result === "string" ? '"' + result.substring(0, 80) + '"' : result)
        );

        if (result && result !== true) {
            // Show as a modal AlertDialog so the cashier cannot miss it.
            // (The loyalty UI's standard notification is a brief transient toast
            //  that disappears before the cashier notices it.)
            this.dialog.add(AlertDialog, {
                title: _t("Loyalty Redemption Blocked"),
                body: String(result),
            });
            console.warn("[loyalty_block_popup] AlertDialog shown for block:", result);
        }

        this.pos.updateRewards();
        return result;
    },
});
