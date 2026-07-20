/** @odoo-module */

import { rpc } from "@web/core/network/rpc";
import { DTRP_LOG_PREFIX } from "@pos_direct_thermal_printer/app/constants";

function enabled(pos) {
    return Boolean(pos?.config?.dtrp_debug_logging);
}

function orderId(order) {
    return order?.uuid || order?.uid || order?.id || order?.name || order?.pos_reference || null;
}

async function backendLog(pos, level, message, data = {}, order = null) {
    if (!enabled(pos) && level !== "error") {
        return;
    }
    try {
        await rpc("/pos_direct_thermal_printer/log", {
            level,
            message,
            data,
            config_id: pos?.config?.id || null,
            order_uid: orderId(order),
        });
    } catch (error) {
        console.warn(DTRP_LOG_PREFIX, "backend diagnostic log failed", error);
    }
}

export const dtrpLogger = {
    debug(pos, message, data = {}, order = null) {
        if (enabled(pos)) {
            console.debug(DTRP_LOG_PREFIX, message, data);
            void backendLog(pos, "debug", message, data, order);
        }
    },
    info(pos, message, data = {}, order = null) {
        if (enabled(pos)) {
            console.info(DTRP_LOG_PREFIX, message, data);
            void backendLog(pos, "info", message, data, order);
        }
    },
    warn(pos, message, data = {}, order = null) {
        if (enabled(pos)) {
            console.warn(DTRP_LOG_PREFIX, message, data);
            void backendLog(pos, "warning", message, data, order);
        }
    },
    error(pos, message, data = {}, order = null) {
        console.error(DTRP_LOG_PREFIX, message, data);
        void backendLog(pos, "error", message, data, order);
    },
};
