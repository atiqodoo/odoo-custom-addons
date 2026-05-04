/** @odoo-module **/
/**
 * credit_note_service.js
 * ======================
 * Thin JSON-RPC wrapper around the five Python controller endpoints at
 * /pos/credit_note/*.
 *
 * Uses Odoo 18's ``rpc`` helper from ``@web/core/network/rpc`` (NOT
 * the legacy ``jsonrpc`` — that identifier does not exist in Odoo 18).
 *
 * All public methods return Promises that resolve to the raw ``payload``
 * from the server, or throw an Error with the server's ``error`` string.
 *
 * Logging
 * -------
 * Set window.CN_DEBUG = true in the browser console for verbose logs.
 */

import { rpc } from "@web/core/network/rpc";

const LOG_PREFIX = "[CreditNoteService]";

function dbg(...args) {
    if (window.CN_DEBUG) {
        console.debug(LOG_PREFIX, ...args);
    }
}

export class CreditNoteService {
    constructor(env) {
        this.env = env;
        dbg("Service instantiated.");
    }

    // =========================================================================
    // validate_return
    // =========================================================================

    /**
     * Pre-flight check before the cashier issues a credit note.
     * @param {number} orderId
     * @param {number} configId
     * @returns {Promise<{ok, errors, warnings, lines_info}>}
     */
    async validateReturn(orderId, configId) {
        dbg("validateReturn", { orderId, configId });
        return this._call("/pos/credit_note/validate_return", {
            order_id:  orderId,
            config_id: configId,
        });
    }

    // =========================================================================
    // compute_amount
    // =========================================================================

    /**
     * Compute the net gift-card amount applying discount + commission config.
     * @param {number} orderId
     * @param {number} configId
     * @returns {Promise<{total, currency, breakdown}>}
     */
    async computeAmount(orderId, configId) {
        dbg("computeAmount", { orderId, configId });
        return this._call("/pos/credit_note/compute_amount", {
            order_id:  orderId,
            config_id: configId,
        });
    }

    // =========================================================================
    // issue
    // =========================================================================

    /**
     * Create the loyalty.card (gift card) on the server.
     *
     * order_id is optional (the return order may not yet be server-synced in
     * Odoo 18 POS when the credit note button is clicked).  When provided the
     * gift card is linked to the order; when absent the card is still created.
     *
     * @param {number}      configId
     * @param {number}      amount
     * @param {number|null} partnerId
     * @param {string}      reason
     * @param {number|null} orderId   — optional server integer order id
     * @returns {Promise<{card_id, code, amount, program}>}
     */
    async issueCreditNote(configId, amount, partnerId = false, reason = "", orderId = false) {
        dbg("issueCreditNote", { configId, amount, partnerId, reason, orderId });
        return this._call("/pos/credit_note/issue", {
            config_id:  configId,
            amount:     amount,
            partner_id: partnerId || false,
            reason:     reason,
            order_id:   (typeof orderId === "number") ? orderId : false,
        });
    }

    // =========================================================================
    // line_commission
    // =========================================================================

    /**
     * Fetch total_extra_amount, total_base_profit, and qty for the given
     * ORIGINAL-SALE order line IDs so the commission deduction can be
     * computed correctly (return lines always have those fields zeroed).
     *
     * @param {number[]} lineIds  — IDs of original pos.order.line records
     * @returns {Promise<Object>}  { "id": {total_extra_amount, total_base_profit, qty} }
     */
    async getLineCommission(lineIds) {
        if (!lineIds || !lineIds.length) {
            dbg("getLineCommission: empty list — skipping RPC");
            return {};
        }
        dbg("getLineCommission", { lineIds });
        return this._call("/pos/credit_note/line_commission", { line_ids: lineIds });
    }

    // =========================================================================
    // original_order_info
    // =========================================================================

    /**
     * Fetch discount + commission summary of the original sale order.
     * @param {number} originalOrderId
     * @returns {Promise<Object>}
     */
    async getOriginalOrderInfo(originalOrderId) {
        dbg("getOriginalOrderInfo", { originalOrderId });
        return this._call("/pos/credit_note/original_order_info", {
            original_order_id: originalOrderId,
        });
    }

    // =========================================================================
    // print_receipt_data
    // =========================================================================

    /**
     * Fetch all data needed to render the thermal credit-note receipt.
     * @param {number} orderId
     * @param {number} cardId
     * @param {number} configId
     * @returns {Promise<Object>}
     */
    async getPrintReceiptData(orderId, cardId, configId) {
        dbg("getPrintReceiptData", { orderId, cardId, configId });
        return this._call("/pos/credit_note/print_receipt_data", {
            order_id:  orderId,
            card_id:   cardId,
            config_id: configId,
        });
    }

    // =========================================================================
    // Private helper
    // =========================================================================

    /**
     * Perform a JSON-RPC call and unwrap the {ok, payload, error} envelope.
     * Throws Error on network failure or server-side ok=false.
     *
     * @param {string} route
     * @param {Object} params
     * @returns {Promise<*>}
     */
    async _call(route, params) {
        dbg("→", route, params);
        let response;
        try {
            response = await rpc(route, params);
        } catch (networkErr) {
            console.error(LOG_PREFIX, "Network error on", route, networkErr);
            throw new Error(
                "Network error calling " + route + ": " +
                (networkErr.message || String(networkErr))
            );
        }

        dbg("←", route, response);

        if (!response || !response.ok) {
            const errMsg = (response && response.error) || "Unknown server error";
            console.warn(LOG_PREFIX, "Server error on", route, errMsg);
            throw new Error(errMsg);
        }

        return response.payload;
    }
}
