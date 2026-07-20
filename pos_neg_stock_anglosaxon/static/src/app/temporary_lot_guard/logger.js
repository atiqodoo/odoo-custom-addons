/** @odoo-module **/

import { TEMPORARY_LOT_GUARD_LOG_PREFIX } from "./constants";

function emit(level, event, details = {}) {
    const method = console[level] || console.log;
    method.call(console, `${TEMPORARY_LOT_GUARD_LOG_PREFIX} ${event}`, {
        event,
        timestamp: new Date().toISOString(),
        ...details,
    });
}

export const temporaryLotGuardLogger = Object.freeze({
    debug(event, details) {
        emit("debug", event, details);
    },
    info(event, details) {
        emit("info", event, details);
    },
    warn(event, details) {
        emit("warn", event, details);
    },
    error(event, details) {
        emit("error", event, details);
    },
});

