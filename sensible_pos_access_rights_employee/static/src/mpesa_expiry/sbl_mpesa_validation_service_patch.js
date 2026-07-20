/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { MpesaValidationService } from "@mpesa_c2b_pos/services/MpesaValidationService";

const LOG = "[SBL M-Pesa Expiry][service]";

patch(MpesaValidationService.prototype, {
    async confirm(transactionId, lockToken, posOrderId, appliedAmount, expiryAuthorization = false) {
        try {
            console.debug(LOG, "confirm with expiry authorization payload", {
                transactionId,
                posOrderId,
                appliedAmount,
                hasAuthorization: Boolean(expiryAuthorization?.token),
            });
            return await this.rpc("/pos/mpesa/confirm", {
                transaction_id: transactionId,
                lock_token: lockToken,
                pos_order_id: posOrderId,
                applied_amount: appliedAmount,
                expiry_authorization: expiryAuthorization || false,
            });
        } catch (err) {
            console.error(LOG, "confirm error", err);
            return { success: false, error: "Network error during confirm" };
        }
    },
});
