/** @odoo-module */

import { dtrpLogger } from "@pos_direct_thermal_printer/app/logger";
import { dtrpBuildReceipt } from "@pos_direct_thermal_printer/app/services/receipt_builder";
import { dtrpEncodeReceipt } from "@pos_direct_thermal_printer/app/services/escpos_encoder";
import { dtrpPrintViaOdooServerWindows } from "@pos_direct_thermal_printer/app/transports/odoo_server_windows_transport";
import { dtrpPrintViaLocalBridge } from "@pos_direct_thermal_printer/app/transports/local_bridge_transport";
import { dtrpPrintViaWebSerial } from "@pos_direct_thermal_printer/app/transports/web_serial_transport";

function shouldPrint(pos) {
    const config = pos?.config || {};
    return Boolean(config.dtrp_enabled && config.dtrp_auto_print_on_validate);
}

export function dtrpPrinterEnabled(pos) {
    return Boolean(pos?.config?.dtrp_enabled);
}

function getCopies(config) {
    return Math.max(1, Number(config.dtrp_receipt_copies || 1));
}

async function printOnce(pos, order, receipt, bytes) {
    const config = pos.config || {};
    if (config.dtrp_connection_mode === "odoo_server_windows") {
        return await dtrpPrintViaOdooServerWindows({
            config,
            receipt,
            bytes,
            logger: dtrpLogger,
            pos,
            order,
        });
    }
    if (config.dtrp_connection_mode === "web_serial") {
        return await dtrpPrintViaWebSerial({
            config,
            receipt,
            bytes,
            logger: dtrpLogger,
            pos,
            order,
        });
    }
    return await dtrpPrintViaLocalBridge({
        config,
        receipt,
        bytes,
        logger: dtrpLogger,
        pos,
        order,
    });
}

export async function dtrpPrintOrder(pos, order) {
    const config = pos?.config || {};
    const marker = `dtrp_printed_${order?.uuid || order?.uid || order?.id}`;
    if (!shouldPrint(pos)) {
        dtrpLogger.debug(pos, "direct printer disabled or auto-print off", {
            enabled: config.dtrp_enabled,
            auto: config.dtrp_auto_print_on_validate,
        }, order);
        return { skipped: true, ok: false };
    }
    if (order?.[marker]) {
        dtrpLogger.warn(pos, "duplicate direct print prevented", { marker }, order);
        return { skipped: true, duplicate: true, ok: true };
    }
    const receipt = dtrpBuildReceipt(pos, order);
    return await dtrpPrintReceipt(pos, order, receipt, { markerPrefix: "dtrp_printed" });
}

export async function dtrpReprintOrder(pos, order) {
    const receipt = dtrpBuildReceipt(pos, order);
    const reprintId = `${receipt.orderUid || order?.uuid || order?.id || "order"}-reprint-${Date.now()}`;
    return await dtrpPrintReceipt(
        pos,
        order,
        { ...receipt, orderUid: reprintId },
        { markerPrefix: "dtrp_reprinted", preventDuplicate: false }
    );
}

export async function dtrpPrintReceipt(pos, order, receipt, options = {}) {
    const config = pos?.config || {};
    const markerPrefix = options.markerPrefix || "dtrp_printed";
    const marker = `${markerPrefix}_${order?.uuid || order?.uid || order?.id || receipt?.orderUid}`;
    const preventDuplicate = options.preventDuplicate !== false;
    if (!dtrpPrinterEnabled(pos)) {
        dtrpLogger.debug(pos, "direct printer disabled", {
            enabled: config.dtrp_enabled,
            markerPrefix,
        }, order);
        return { skipped: true, ok: false };
    }
    if (preventDuplicate && order?.[marker]) {
        dtrpLogger.warn(pos, "duplicate direct print prevented", { marker }, order);
        return { skipped: true, duplicate: true, ok: true };
    }
    const bytes = dtrpEncodeReceipt(receipt, config);
    const copies = getCopies(config);
    const attempts = Math.max(1, Number(config.dtrp_retry_count || 0) + 1);
    dtrpLogger.info(pos, "direct receipt print starting", {
        order: receipt.orderName,
        markerPrefix,
        preventDuplicate,
        mode: config.dtrp_connection_mode,
        paper: config.dtrp_paper_width,
        copies,
        attempts,
        byteLength: bytes.length,
    }, order);
    let lastError = null;
    for (let copy = 1; copy <= copies; copy++) {
        let printed = false;
        for (let attempt = 1; attempt <= attempts; attempt++) {
            try {
                dtrpLogger.debug(pos, "direct receipt print attempt", { copy, attempt }, order);
                await printOnce(pos, order, receipt, bytes);
                printed = true;
                break;
            } catch (error) {
                lastError = error;
                dtrpLogger.error(pos, "direct receipt print attempt failed", {
                    copy,
                    attempt,
                    message: error?.message || String(error),
                    stack: error?.stack || "",
                }, order);
            }
        }
        if (!printed) {
            throw lastError || new Error("Direct receipt print failed.");
        }
    }
    if (preventDuplicate) {
        order[marker] = true;
    }
    order.nb_print = (order.nb_print || 0) + copies;
    dtrpLogger.info(pos, "direct receipt print completed", {
        order: receipt.orderName,
        copies,
        nb_print: order.nb_print,
    }, order);
    return { ok: true, receipt, copies };
}
