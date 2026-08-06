/** @odoo-module */

import { dtrpLogger } from "@pos_direct_thermal_printer/app/logger";
import { dtrpPrintCodDispatchOrder } from "@pos_direct_thermal_printer/app/services/cod_dispatch_printer_service";

const COD_DISPATCH_PRINT_EVENT = "pos-cod:dispatch-print";

function registerCodDispatchPrintListener() {
    if (window.__dtrpCodDispatchPrintListenerRegistered) {
        console.debug("[DTRP][COD][listener] listener already registered");
        return;
    }
    window.__dtrpCodDispatchPrintListenerRegistered = true;

    window.addEventListener(COD_DISPATCH_PRINT_EVENT, (event) => {
        const detail = event.detail || {};
        const { pos, order, serialized, backendResult, codPayload } = detail;
        console.log("[DTRP][COD][listener] received COD dispatch print event", {
            order: order?.name || order?.pos_reference || order?.uid || order?.uuid,
            hasPromiseBucket: Array.isArray(detail.promises),
            printerEnabled: Boolean(pos?.config?.dtrp_enabled),
            connectionMode: pos?.config?.dtrp_connection_mode,
        });
        dtrpLogger.info(pos, "COD dispatch print listener received event", {
            order: order?.name || order?.pos_reference || order?.uid || order?.uuid,
            printerEnabled: Boolean(pos?.config?.dtrp_enabled),
            connectionMode: pos?.config?.dtrp_connection_mode,
        }, order);

        const printPromise = dtrpPrintCodDispatchOrder({
            pos,
            order,
            serialized,
            backendResult,
            codPayload,
        });

        if (Array.isArray(detail.promises)) {
            detail.promises.push(printPromise);
        }
    });

    console.log("[DTRP][COD][listener] registered COD dispatch print listener");
}

registerCodDispatchPrintListener();
