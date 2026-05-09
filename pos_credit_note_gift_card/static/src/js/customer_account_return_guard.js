/** @odoo-module **/
/**
 * Blocks credit-note generation for returns whose original POS order was paid
 * using Customer Account / credit. Logs are always visible in Chrome DevTools
 * with prefix [CNCustomerAccountReturnGuard].
 */

import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { rpc } from "@web/core/network/rpc";

const LOG_PREFIX = "[CNCustomerAccountReturnGuard]";

function log(...args) {
    console.warn(LOG_PREFIX, ...args);
}

function debug(...args) {
    if (window.CN_DEBUG) {
        console.debug(LOG_PREFIX, ...args);
    }
}

function paymentMethodIsCustomerAccount(paymentMethod) {
    return Boolean(
        paymentMethod &&
        (paymentMethod.type === "pay_later" || paymentMethod.pcl_is_credit_method)
    );
}

function orderPaidWithCustomerAccount(order) {
    const payments = order?.payment_ids || [];
    const creditPayments = payments.filter((payment) =>
        paymentMethodIsCustomerAccount(payment.payment_method_id)
    );
    debug("orderPaidWithCustomerAccount", {
        order: order?.name,
        orderId: order?.id,
        serverId: order?.server_id,
        payments: payments.map((payment) => ({
            amount: payment.amount,
            methodId: payment.payment_method_id?.id,
            methodName: payment.payment_method_id?.name,
            methodType: payment.payment_method_id?.type,
            pclIsCredit: payment.payment_method_id?.pcl_is_credit_method,
        })),
        creditCount: creditPayments.length,
    });
    return creditPayments.length > 0;
}

function getOriginalOrdersFromRefundOrder(refundOrder) {
    const seen = new Set();
    const orders = [];
    for (const line of refundOrder?.lines || []) {
        const refLine = line.refunded_orderline_id;
        const originalOrder = refLine && typeof refLine === "object"
            ? refLine.order_id
            : null;
        const originalId = originalOrder && typeof originalOrder === "object"
            ? (originalOrder.id ?? originalOrder.server_id)
            : originalOrder;
        if (originalOrder && typeof originalOrder === "object" && !seen.has(originalId)) {
            seen.add(originalId);
            orders.push(originalOrder);
        }
    }
    return orders;
}

function getOriginalOrderIdsFromRefundOrder(refundOrder) {
    const seen = new Set();
    const ids = [];

    const returnRef = refundOrder?.return_pos_order_id;
    const returnRefId = returnRef && typeof returnRef === "object"
        ? (returnRef.server_id ?? returnRef.id)
        : returnRef;
    if (typeof returnRefId === "number") {
        seen.add(returnRefId);
        ids.push(returnRefId);
    }

    for (const line of refundOrder?.lines || []) {
        const refLine = line.refunded_orderline_id;
        const originalOrder = refLine && typeof refLine === "object"
            ? refLine.order_id
            : null;
        const rawId = originalOrder && typeof originalOrder === "object"
            ? (originalOrder.server_id ?? originalOrder.id)
            : originalOrder;
        if (typeof rawId === "number" && !seen.has(rawId)) {
            seen.add(rawId);
            ids.push(rawId);
        }
    }
    return ids;
}

function getSelectedTicketOriginalOrder(screen) {
    const order = screen.getSelectedOrder?.();
    const selectedId = screen.getSelectedOrderlineId?.();
    const selectedLine = selectedId
        ? order?.lines?.find((line) => line.id == selectedId)
        : null;
    const lineOrder = selectedLine?.order_id;
    if (lineOrder && typeof lineOrder === "object") {
        return lineOrder;
    }
    return order || null;
}

function blockMessage(orderName = "") {
    return _t(
        "Credit note generation is blocked for this return because the original POS order %(order)s was paid by Customer Account.\n\nUse Customer Account to complete the return.",
        { order: orderName || "" }
    );
}

async function callServerGuard(originalOrderIds) {
    if (!originalOrderIds.length) {
        log("Server guard skipped: no original order ids found.");
        return { blocked: false, message: "", orders: [] };
    }
    log("Calling server guard for originalOrderIds=", originalOrderIds);
    const response = await rpc("/pos/credit_note/customer_account_return_guard", {
        original_order_ids: originalOrderIds,
    });
    if (!response?.ok) {
        throw new Error(response?.error || "Customer Account return guard failed.");
    }
    log("Server guard response=", response.payload);
    return response.payload || { blocked: false, message: "", orders: [] };
}

async function getCustomerAccountBlock(refundOrder) {
    const localOriginalOrders = getOriginalOrdersFromRefundOrder(refundOrder);
    const localBlocked = localOriginalOrders.filter(orderPaidWithCustomerAccount);
    if (localBlocked.length) {
        const names = localBlocked.map((order) => order.name || order.pos_reference || order.id);
        log("LOCAL BLOCK: original order paid with Customer Account:", names);
        return {
            blocked: true,
            message: blockMessage(names.join(", ")),
            orders: localBlocked,
            source: "local",
        };
    }

    const originalOrderIds = getOriginalOrderIdsFromRefundOrder(refundOrder);
    try {
        const serverGuard = await callServerGuard(originalOrderIds);
        if (serverGuard.blocked) {
            return { ...serverGuard, source: "server" };
        }
    } catch (err) {
        console.error(LOG_PREFIX, "Server guard error:", err);
        throw err;
    }

    log("ALLOW: no Customer Account payment found on original order.", {
        refundOrder: refundOrder?.name,
        originalOrderIds,
    });
    return { blocked: false, message: "", orders: [], source: "none" };
}

patch(TicketScreen.prototype, {
    setup() {
        super.setup(...arguments);
        if (!this.dialog) {
            this.dialog = useService("dialog");
        }
        log("TicketScreen guard active.");
    },

    async _onDoRefund() {
        const originalOrder = getSelectedTicketOriginalOrder(this);
        if (originalOrder && orderPaidWithCustomerAccount(originalOrder)) {
            log("BLOCK at TicketScreen _onDoRefund", {
                originalOrder: originalOrder.name,
                originalOrderId: originalOrder.id,
            });
            this.dialog.add(AlertDialog, {
                title: _t("Use Customer Account for Return"),
                body: blockMessage(originalOrder.name || originalOrder.id),
            });
            return;
        }
        return super._onDoRefund?.(...arguments);
    },
});

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        log("PaymentScreen guard active.");
    },

    async _runCreditNoteCore(order, orderId, configId) {
        const guard = await getCustomerAccountBlock(order);
        if (guard.blocked) {
            log("BLOCK before credit-note core", {
                source: guard.source,
                orderId,
                configId,
                guard,
            });
            this.dialog.add(AlertDialog, {
                title: _t("Use Customer Account for Return"),
                body: guard.message || blockMessage(),
            });
            return null;
        }
        return super._runCreditNoteCore(...arguments);
    },
});
