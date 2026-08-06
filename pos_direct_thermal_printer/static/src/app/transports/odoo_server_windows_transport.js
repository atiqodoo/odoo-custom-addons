/** @odoo-module */

import { rpc } from "@web/core/network/rpc";

function bytesToBase64(bytes) {
    let binary = "";
    const chunkSize = 0x8000;
    for (let index = 0; index < bytes.length; index += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
    }
    return btoa(binary);
}

export async function dtrpPrintViaOdooServerWindows({ config, receipt, bytes, logger, pos, order }) {
    if (!config.dtrp_printer_identifier) {
        throw new Error("Printer Identifier is required for Odoo Server Windows RAW mode.");
    }
    const payload = {
        config_id: config.id,
        printer: config.dtrp_printer_identifier,
        job_id: `${receipt.orderUid || Date.now()}`,
        payload_base64: bytesToBase64(bytes),
        receipt_summary: {
            order: receipt.orderName,
            cashier: receipt.cashier,
            line_count: receipt.lines.length,
            payment_count: receipt.paymentLines.length,
            amount_total: receipt.raw.amountTotal,
        },
    };
    logger.debug(pos, "sending print job to Odoo Windows RAW controller", {
        printer: payload.printer,
        job_id: payload.job_id,
        byteLength: bytes.length,
    }, order);
    const response = await rpc("/pos_direct_thermal_printer/windows_raw_print", payload);
    if (!response?.ok) {
        throw new Error(response?.message || "Odoo Windows RAW print failed.");
    }
    logger.info(pos, "Odoo Windows RAW controller accepted print job", response, order);
    return response;
}
