/** @odoo-module */

import { dtrpLogger } from "@pos_direct_thermal_printer/app/logger";
import {
    dtrpPrintReceipt,
    dtrpPrinterEnabled,
} from "@pos_direct_thermal_printer/app/services/direct_printer_service";
import { dtrpBuildCodDispatchReceipt } from "@pos_direct_thermal_printer/app/services/cod_dispatch_receipt_builder";

export async function dtrpPrintCodDispatchOrder({
    pos,
    order,
    serialized = {},
    backendResult = null,
    codPayload = {},
} = {}) {
    if (!pos || !order) {
        console.warn("[DTRP][COD][printer] missing POS or order; COD receipt print skipped", {
            hasPos: Boolean(pos),
            hasOrder: Boolean(order),
        });
        return { skipped: true, ok: false };
    }
    if (!dtrpPrinterEnabled(pos)) {
        console.log("[DTRP][COD][printer] COD dispatch receipt print skipped: direct printer disabled", {
            enabled: pos.config?.dtrp_enabled,
            order: order.name || order.uid || order.uuid,
        });
        dtrpLogger.debug(pos, "COD dispatch receipt print skipped: direct printer disabled", {
            enabled: pos.config?.dtrp_enabled,
            order: order.name || order.uid || order.uuid,
        }, order);
        return { skipped: true, ok: false };
    }

    console.log("[DTRP][COD][printer] preparing COD dispatch receipt print", {
        order: order.name || order.pos_reference || order.uid || order.uuid,
        backendResult,
        serialized: {
            name: serialized.name,
            amount_total: serialized.amount_total,
            partner_id: serialized.partner_id,
            is_cod: serialized.is_cod,
            cod_state: serialized.cod_state,
            payment_count: serialized.statement_ids?.length || serialized.payment_ids?.length || 0,
        },
        codPayload,
    });

    const receipt = dtrpBuildCodDispatchReceipt(pos, order, codPayload, serialized);
    dtrpLogger.info(pos, "COD dispatch receipt print starting", {
        order: receipt.orderName,
        orderUid: receipt.orderUid,
        lineCount: receipt.lines.length,
        paymentLineCount: receipt.paymentLines.length,
        paymentDisplayLineCount: receipt.paymentDisplayLines.length,
        total: receipt.total,
        backendResult,
    }, order);

    try {
        const result = await dtrpPrintReceipt(pos, order, receipt, {
            markerPrefix: "dtrp_cod_dispatch_printed",
        });
        dtrpLogger.info(pos, "COD dispatch receipt print completed", {
            order: receipt.orderName,
            copies: result.copies,
            skipped: result.skipped,
        }, order);
        console.log("[DTRP][COD][printer] COD dispatch receipt print completed", result);
        return result;
    } catch (error) {
        dtrpLogger.error(pos, "COD dispatch receipt print failed", {
            order: receipt.orderName,
            message: error?.message || String(error),
            stack: error?.stack || "",
        }, order);
        console.error("[DTRP][COD][printer] COD dispatch receipt print failed", error);
        throw error;
    }
}
