/** @odoo-module */

import { UPG_LOG_PREFIX } from "@pos_uncleared_payment_guard/app/constants";

function enabled(pos) {
    return Boolean(pos?.config?.upg_debug_logging);
}

export const upgLogger = {
    debug(pos, ...args) {
        if (enabled(pos)) {
            console.debug(UPG_LOG_PREFIX, ...args);
        }
    },
    info(pos, ...args) {
        if (enabled(pos)) {
            console.info(UPG_LOG_PREFIX, ...args);
        }
    },
    warn(pos, ...args) {
        if (enabled(pos)) {
            console.warn(UPG_LOG_PREFIX, ...args);
        }
    },
    error(...args) {
        console.error(UPG_LOG_PREFIX, ...args);
    },
    table(pos, label, rows) {
        if (!enabled(pos)) {
            return;
        }
        console.groupCollapsed(`${UPG_LOG_PREFIX} ${label}`);
        console.table(rows);
        console.groupEnd();
    },
};
