/**
 * MpesaValidationService
 * All RPC calls to the backend POS controller are centralised here.
 * OWL components never call fetch/rpc directly — they use this service.
 * This makes it trivial to mock in tests and swap endpoints.
 */

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

export class MpesaValidationService {
    constructor(env) {
        this.rpc = rpc;
        this.notification = env.services.notification;
    }

    /**
     * Search for M-Pesa transactions matching a phone number and order amount.
     * @param {string} phone         - Raw phone as typed by cashier
     * @param {number} orderAmount   - Current order total in Ksh
     * @param {number} posSessionId  - Active POS session ID
     * @returns {Promise<{status:string, transactions:Array}>}
     */
    async validate(phone, orderAmount, posSessionId) {
        try {
            return await this.rpc("/pos/mpesa/validate", {
                phone,
                order_amount: orderAmount,
                pos_session_id: posSessionId,
            });
        } catch (err) {
            console.error("[MpesaValidationService] validate error:", err);
            this.notification.add("M-Pesa lookup failed — check network.", { type: "danger" });
            return { status: "error", transactions: [] };
        }
    }

    /**
     * Reserve a specific transaction for this POS session.
     * @returns {Promise<{success:boolean, lock_token:string, expires_in:number}>}
     */
    async lock(transactionId, posSessionId) {
        try {
            return await this.rpc("/pos/mpesa/lock", {
                transaction_id: transactionId,
                pos_session_id: posSessionId,
            });
        } catch (err) {
            console.error("[MpesaValidationService] lock error:", err);
            return { success: false, error: "Network error during lock" };
        }
    }

    /**
     * Validate the held transaction for a POS payment line.
     * @returns {Promise<{success:boolean, mpesa_ref:string}>}
     */
    async confirm(transactionId, lockToken, posOrderId, appliedAmount, orderUuid = "") {
        try {
            const route = orderUuid
                ? "/pos/mpesa/reservation/confirm"
                : "/pos/mpesa/confirm";
            return await this.rpc(route, {
                transaction_id: transactionId,
                lock_token: lockToken,
                pos_order_id: posOrderId,
                applied_amount: appliedAmount,
                order_uuid: orderUuid || undefined,
            });
        } catch (err) {
            console.error("[MpesaValidationService] confirm error:", err);
            return { success: false, error: "Network error during confirm" };
        }
    }

    /**
     * Release lock when cashier cancels the M-Pesa screen.
     */
    async release(transactionId, posSessionId, mpesaRef = "") {
        try {
            await this.rpc("/pos/mpesa/release", {
                transaction_id: transactionId || 0,
                pos_session_id: posSessionId,
                mpesa_ref: mpesaRef,
            });
        } catch (err) {
            console.warn("[MpesaValidationService] release error (non-critical):", err);
        }
    }
}

registry.category("services").add("mpesa_validation", {
    dependencies: ["notification"],
    start(env) {
        return new MpesaValidationService(env);
    },
});
