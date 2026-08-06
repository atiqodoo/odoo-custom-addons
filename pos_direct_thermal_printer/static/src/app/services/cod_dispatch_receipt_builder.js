/** @odoo-module */

import { dtrpBuildReceipt } from "@pos_direct_thermal_printer/app/services/receipt_builder";

function clean(value) {
    if (value === undefined || value === null || value === false) {
        return "";
    }
    return String(value).replace(/\s+/g, " ").trim();
}

function employeeName(pos, employeeId) {
    if (!employeeId) {
        return "";
    }
    const employee = pos.models?.["hr.employee"]?.get?.(employeeId);
    return clean(employee?.name || employee?.display_name);
}

export function dtrpBuildCodDispatchReceipt(pos, order, codPayload = {}, serialized = {}) {
    const receipt = dtrpBuildReceipt(pos, order);
    const deliveryEmployee = employeeName(pos, codPayload.employee_id || serialized.delivery_employee_id);
    const deliveryAddress = clean(codPayload.delivery_address || serialized.delivery_address);
    const deliveryNotes = clean(codPayload.delivery_notes || serialized.delivery_notes);

    const codLines = [
        "COD DISPATCH",
        deliveryEmployee ? `Delivery: ${deliveryEmployee}` : "",
        deliveryAddress ? `Address: ${deliveryAddress}` : "",
        deliveryNotes ? `Notes: ${deliveryNotes}` : "",
    ].filter(Boolean);

    const header = [receipt.header, ...codLines].filter(Boolean).join("\n");
    const codReceipt = {
        ...receipt,
        orderUid: `cod_${receipt.orderUid}`,
        header,
        paymentLines: [],
        paymentDisplayLines: receipt.adjustmentLines || [],
        showChange: false,
        change: "",
        raw: {
            ...receipt.raw,
            totalPaid: 0,
            change: 0,
            codDispatch: true,
        },
    };

    console.log("[DTRP][COD][receipt_builder] built COD dispatch receipt without payment data", {
        order: codReceipt.orderName,
        orderUid: codReceipt.orderUid,
        lineCount: codReceipt.lines.length,
        paymentLineCount: codReceipt.paymentLines.length,
        paymentDisplayLineCount: codReceipt.paymentDisplayLines.length,
        adjustmentLineCount: codReceipt.adjustmentLines.length,
        deliveryEmployee,
        hasDeliveryAddress: Boolean(deliveryAddress),
        hasDeliveryNotes: Boolean(deliveryNotes),
    });

    return codReceipt;
}
