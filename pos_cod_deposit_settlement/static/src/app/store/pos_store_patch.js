/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { cddsWarn, cddsError } from "@pos_cod_deposit_settlement/app/utils/cod_deposit_logger";

patch(PosStore.prototype, {
    async fetchPartnerCreditInfo(partner) {
        const result = await super.fetchPartnerCreditInfo(...arguments);
        cddsWarn(this, "CREDIT-OVERLAY", "normal POS received reservation-adjusted credit data", {
            partnerId: partner?.id,
            partnerName: partner?.name,
            totalDue: result?.total_due,
            postedDeposit: result?.deposit_balance,
            usableSessionIncomingAfterReservations: result?.session_incoming_payments,
            hasOverdue: result?.has_overdue,
        });
        return result;
    },

    async cod_fetch_pending_orders() {
        const result = await super.cod_fetch_pending_orders(...arguments);
        const ids = (this.cod_pending_orders || []).map((order) => order.server_id || order.id).filter(Boolean);
        if (ids.length) {
            try {
                const statuses = await this.data.call(
                    "pos.order", "cod_deposit_reservation_status", [ids]
                );
                this.cod_pending_orders = (this.cod_pending_orders || []).map((order) => ({
                    ...order,
                    ...(statuses[order.server_id || order.id] || {}),
                }));
                cddsWarn(this, "STATUS", "reservation statuses refreshed", { ids, statuses });
            } catch (error) {
                cddsError("STATUS", "reservation status refresh failed", {
                    ids, error: error?.message || error,
                });
            }
        }
        return result;
    },

    async cddsGetCodDepositQuote(orderId) {
        const sessionId = this.session?.id || false;
        cddsWarn(this, "QUOTE", "request", { orderId, sessionId });
        try {
            const result = await this.data.call("pos.order", "cod_deposit_quote", [orderId, sessionId]);
            cddsWarn(this, "QUOTE", "response", result);
            return result;
        } catch (error) {
            cddsError("QUOTE", "failed", { orderId, sessionId, error: error?.message || error });
            throw error;
        }
    },

    async cddsApplyCodDeposit(orderId, amount, operationUuid) {
        const sessionId = this.session?.id || false;
        const payload = { orderId, amount, sessionId, operationUuid };
        cddsWarn(this, "APPLY", "request", payload);
        try {
            const result = await this.data.call(
                "pos.order",
                "cod_apply_deposit",
                [orderId, amount, sessionId, operationUuid]
            );
            cddsWarn(this, "APPLY", "response", result);
            if (result.success) {
                await this.cod_fetch_pending_orders();
            }
            return result;
        } catch (error) {
            cddsError("APPLY", "failed", { ...payload, error: error?.message || error });
            throw error;
        }
    },
});
