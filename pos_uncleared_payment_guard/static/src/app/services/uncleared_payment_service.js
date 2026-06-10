/** @odoo-module */

export function upgRecordId(record) {
    return record?.id ?? record;
}

export function upgConfiguredMethodIds(pos) {
    const mapped = pos?.config?.upg_uncleared_payment_method_ids || [];
    if (!Array.isArray(mapped)) {
        return [];
    }
    return mapped.map(upgRecordId).filter(Boolean);
}

export function upgIsGuardedPaymentMethod(pos, paymentMethod) {
    const methodId = upgRecordId(paymentMethod);
    if (!methodId) {
        return false;
    }
    return Boolean(
        paymentMethod?.upg_is_uncleared_guard_method ||
        upgConfiguredMethodIds(pos).includes(methodId)
    );
}

export function upgIsDepositOrSettleOrder(order) {
    if (!order) {
        return false;
    }
    const rawLines = order.get_orderlines?.() || order.lines || [];
    const saleLines = rawLines.filter((line) => {
        const qty = Math.abs(line.qty ?? line.get_quantity?.() ?? 0);
        return !line.is_reward_line && qty > 0;
    });
    return saleLines.length === 0 && Boolean(order.partner_id || order.get_partner?.());
}

export function upgGuardedPaymentLines(pos, order) {
    return (order?.payment_ids || []).filter((line) =>
        upgIsGuardedPaymentMethod(pos, line.payment_method_id)
    );
}
