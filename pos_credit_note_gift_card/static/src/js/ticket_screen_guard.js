/** @odoo-module **/
/**
 * ticket_screen_guard.js
 * ======================
 * Patches the POS TicketScreen to block non-returnable products
 * BEFORE the refund order is created.
 *
 * Two interception points:
 *   1. _onUpdateSelectedOrderline  — when the cashier enters a qty in the
 *      return numpad for a specific line.
 *   2. _prepareAutoRefundOnOrder   — when the screen auto-selects the first
 *      line for refund (e.g. single-line orders).
 *
 * For each blocked product a persistent notification banner is shown with
 * the product name and the configured "not returnable" message, and the
 * numpad is reset so the cashier cannot proceed.
 *
 * Additionally, when the cashier selects a line belonging to a tinted-paint
 * or other non-returnable product for the first time, a warning banner
 * explains why it is blocked before any qty is entered.
 *
 * Integration with pos_loyalty
 * ----------------------------
 * The guard runs AFTER the pos_loyalty ticket-screen patch which already
 * blocks eWallet/gift-card reward lines.  Both patches coexist because
 * they target different conditions.
 *
 * Logging
 * -------
 * Set window.CN_DEBUG = true in the browser console for verbose output.
 */

import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ReturnOrderValidator } from "./return_order_validator";

const LOG_PREFIX = "[TicketScreenGuard]";

function dbg(...args) {
    if (window.CN_DEBUG) {
        console.debug(LOG_PREFIX, ...args);
    }
}

patch(TicketScreen.prototype, {
    // -------------------------------------------------------------------------
    // Setup — inject notification service
    // -------------------------------------------------------------------------

    setup() {
        super.setup(...arguments);
        // notification may already be injected by pos_loyalty; guard duplication
        if (!this.notification) {
            this.notification = useService("notification");
        }
        dbg("TicketScreenGuard patch active.");
    },

    // -------------------------------------------------------------------------
    // Intercept line selection — show banner when non-returnable line is picked
    // -------------------------------------------------------------------------

    _onUpdateSelectedOrderline() {
        const order = this.getSelectedOrder();
        if (!order) {
            return this.numberBuffer.reset();
        }

        const selectedId  = this.getSelectedOrderlineId();
        const orderline   = order.lines.find((l) => l.id == selectedId);

        if (orderline && this._isCreditNoteNonReturnable(orderline)) {
            this._showNonReturnableNotification(orderline);
            return this.numberBuffer.reset();
        }

        return super._onUpdateSelectedOrderline(...arguments);
    },

    // -------------------------------------------------------------------------
    // Intercept auto-refund — block if any line is non-returnable
    // -------------------------------------------------------------------------

    _prepareAutoRefundOnOrder(order) {
        const selectedId = this.getSelectedOrderlineId();
        const orderline  = selectedId
            ? order.lines.find((l) => l.id == selectedId)
            : null;

        if (orderline && this._isCreditNoteNonReturnable(orderline)) {
            this._showNonReturnableNotification(orderline);
            return false;
        }
        return super._prepareAutoRefundOnOrder(...arguments);
    },

    // -------------------------------------------------------------------------
    // Also validate the entire order before the refund is executed
    // (doRefund is the final action button)
    // -------------------------------------------------------------------------

    async _onDoRefund() {
        const order = this.getSelectedOrder();
        if (order) {
            const blocked = ReturnOrderValidator.hasNonReturnableLines(order);
            if (blocked.length > 0) {
                for (const b of blocked) {
                    dbg("Blocking refund — non-returnable:", b.product);
                    this.notification.add(
                        _t(
                            "'%(product)s' cannot be returned or refunded.",
                            { product: b.product }
                        ),
                        { type: "danger", sticky: true }
                    );
                }
                return;
            }
        }
        return super._onDoRefund?.(...arguments);
    },

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    /**
     * Returns true if the given order line's product is flagged as
     * non-returnable by this module's ``pos_not_returnable`` field.
     *
     * @param {Object} orderline — POS order-line model instance
     * @returns {boolean}
     */
    _isCreditNoteNonReturnable(orderline) {
        if (!orderline || !orderline.product_id) return false;
        const product = orderline.product_id;
        const notReturnable = Boolean(
            product.pos_not_returnable ||
            (product.product_tmpl_id && product.product_tmpl_id.pos_not_returnable)
        );
        dbg(
            "_isCreditNoteNonReturnable product='%s' →",
            product.display_name || product.name || "?",
            notReturnable,
        );
        return notReturnable;
    },

    /**
     * Show a persistent danger notification listing the product name and
     * explaining why the return is blocked.
     *
     * @param {Object} orderline
     */
    _showNonReturnableNotification(orderline) {
        const name =
            orderline.product_id?.display_name ||
            orderline.product_id?.name ||
            _t("This product");
        dbg("Showing non-returnable notification for:", name);
        this.notification.add(
            _t(
                "'%(product)s' is not eligible for return or refund.\n" +
                "Once sold, this product cannot be returned.",
                { product: name }
            ),
            { type: "danger", sticky: false, timeout: 6000 }
        );
    },
});
