/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import {
    clientAudit,
    heartbeatOrderReservations,
    ordersWithReservations,
    recoverLegacyOrderPayments,
    recoverLocalReservations,
} from "@mpesa_c2b_pos/services/mpesa_reservation_recovery_service";

patch(PosStore.prototype, {
    async setup(...args) {
        await super.setup(...args);
        await recoverLegacyOrderPayments(this);
        void recoverLocalReservations(this);
        this.mpesaReservationHeartbeatTimer = setInterval(() => {
            for (const order of ordersWithReservations(this)) {
                void heartbeatOrderReservations(order);
            }
        }, 180000);
    },

    async preSyncAllOrders(orders) {
        const result = await super.preSyncAllOrders(...arguments);
        await recoverLegacyOrderPayments(this, orders);
        for (const order of ordersWithReservations(this, orders)) {
            await heartbeatOrderReservations(order);
            await clientAudit("sync_attempt", order.uuid, {
                name: order.name,
                paymentCount: (order.payment_ids || []).length,
            });
        }
        return result;
    },

    async postSyncAllOrders(orders) {
        const result = await super.postSyncAllOrders(...arguments);
        for (const order of orders || []) {
            await clientAudit("sync_success", order.uuid, {
                serverId: order.id,
                name: order.name,
            });
        }
        return result;
    },
});
