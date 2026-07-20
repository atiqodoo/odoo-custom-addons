/** @odoo-module */

import { rpc } from "@web/core/network/rpc";

const PREFIX = "[M-Pesa Reservation Recovery]";

function reservationPayments(order) {
    return (order?.payment_ids || []).filter(
        (line) => line.mpesa_ref && line.mpesa_reservation_token
    );
}

function legacyPayments(order) {
    return (order?.payment_ids || []).filter(
        (line) => line.mpesa_ref && !line.mpesa_reservation_token
    );
}

export function ordersWithReservations(pos, orders = null) {
    const source = orders || pos?.models?.["pos.order"] || [];
    return Array.from(source).filter((order) => reservationPayments(order).length);
}

export async function clientAudit(event, orderUuid, detail = {}) {
    console.info(PREFIX, event, { orderUuid, ...detail });
    try {
        await rpc("/pos/mpesa/reservation/client-log", {
            event,
            order_uuid: orderUuid || "",
            detail,
        });
    } catch (error) {
        console.debug(PREFIX, "server audit unavailable", error?.message || error);
    }
}

export async function heartbeatOrderReservations(order) {
    for (const payment of reservationPayments(order)) {
        try {
            const result = await rpc("/pos/mpesa/reservation/heartbeat", {
                token: payment.mpesa_reservation_token,
                order_uuid: order.uuid,
            });
            payment.mpesa_reservation_state = result.state || result.reservation_state || "unknown";
            await clientAudit("heartbeat_result", order.uuid, {
                mpesaRef: payment.mpesa_ref,
                state: payment.mpesa_reservation_state,
            });
        } catch (error) {
            console.warn(PREFIX, "heartbeat failed; local order preserved", {
                orderUuid: order.uuid,
                mpesaRef: payment.mpesa_ref,
                message: error?.message || String(error),
            });
        }
    }
}

export async function recoverLocalReservations(pos) {
    const orders = ordersWithReservations(pos);
    if (!orders.length) {
        return;
    }
    const orderUuids = orders.map((order) => order.uuid);
    await clientAudit("startup_scan", "", { orderCount: orders.length, orderUuids });
    try {
        const statuses = await rpc("/pos/mpesa/reservation/status", {
            order_uuids: orderUuids,
        });
        for (const order of orders) {
            const orderStatuses = statuses[order.uuid] || [];
            if (!orderStatuses.length) {
                await clientAudit("reservation_missing", order.uuid, {
                    action: "preserve_local_order_for_manual_recovery",
                });
                continue;
            }
            for (const payment of [...reservationPayments(order)]) {
                const status = orderStatuses.find(
                    (item) =>
                        item.reservation_token === payment.mpesa_reservation_token ||
                        item.mpesa_ref === payment.mpesa_ref
                );
                if (!status) {
                    await clientAudit("payment_reservation_missing", order.uuid, {
                        mpesaRef: payment.mpesa_ref,
                    });
                    continue;
                }
                payment.mpesa_reservation_state = status.reservation_state || "unknown";
                await clientAudit("startup_status", order.uuid, {
                    state: status.reservation_state,
                    linkedOrderId: status.linked_order_id || false,
                    mpesaRef: status.mpesa_ref,
                });
                if (status.reservation_state === "released" || status.reservation_state === "expired") {
                    // Roll back only the invalid payment. Odoo's relational data service
                    // persists this local change to IndexedDB; product/customer lines remain.
                    order.remove_paymentline(payment);
                    await clientAudit("expired_payment_removed", order.uuid, {
                        mpesaRef: status.mpesa_ref,
                        action: "basket_preserved_payment_requires_revalidation",
                    });
                    pos.notification?.add(
                        `M-Pesa payment ${status.mpesa_ref} expired and was removed; the basket was preserved.`,
                        { type: "warning", sticky: true }
                    );
                }
            }
        }
    } catch (error) {
        console.warn(PREFIX, "startup recovery deferred; IndexedDB orders preserved", error);
    }
}

export async function recoverLegacyOrderPayments(pos, suppliedOrders = null) {
    const source = suppliedOrders || pos?.models?.["pos.order"] || [];
    const orders = Array.from(source).filter((order) => legacyPayments(order).length);
    if (!orders.length) {
        return;
    }
    const requestOrders = orders.map((order) => ({
        order_uuid: order.uuid,
        payments: legacyPayments(order).map((payment) => ({
            mpesa_ref: payment.mpesa_ref,
            amount: Number(payment.amount || 0),
        })),
    }));
    await clientAudit("legacy_startup_scan", "", {
        orderCount: requestOrders.length,
        orderUuids: requestOrders.map((item) => item.order_uuid),
    });
    try {
        const classifications = await rpc("/pos/mpesa/reservation/legacy-status", {
            orders: requestOrders,
        });
        for (const order of orders) {
            const statuses = classifications[order.uuid] || [];
            for (const payment of [...legacyPayments(order)]) {
                const status = statuses.find((item) => item.mpesa_ref === payment.mpesa_ref);
                if (!status) {
                    continue;
                }
                await clientAudit("legacy_payment_classified", order.uuid, status);
                if (status.disposition === "revalidate") {
                    if (order.finalized && !status.server_order_id) {
                        order.update({ state: "draft" });
                        await clientAudit("legacy_order_reopened", order.uuid, {
                            previousState: "paid",
                            reason: status.reason,
                        });
                    }
                    order.remove_paymentline(payment);
                    await clientAudit("legacy_invalid_payment_removed", order.uuid, {
                        mpesaRef: payment.mpesa_ref,
                        reason: status.reason,
                        action: "basket_preserved_payment_requires_revalidation",
                    });
                    pos.notification?.add(
                        `Stale M-Pesa payment ${payment.mpesa_ref} was removed; the basket was preserved.`,
                        { type: "warning", sticky: true }
                    );
                } else if (status.disposition === "conflict") {
                    pos.notification?.add(
                        `Order ${order.name} needs supervisor review before M-Pesa synchronization.`,
                        { type: "warning", sticky: true }
                    );
                }
            }
        }
    } catch (error) {
        console.warn(PREFIX, "legacy recovery deferred; local orders preserved", error);
    }
}
