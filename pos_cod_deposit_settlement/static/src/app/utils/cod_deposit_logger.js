/** @odoo-module **/

const PREFIX = "[COD-DEPOSIT-UI]";

export function cddsWarn(pos, stage, message, details = {}) {
    if (pos?.config?.cdds_debug_logging !== false) {
        console.warn(`${PREFIX}[${stage}] ${message}`, details);
    }
}

export function cddsError(stage, message, details = {}) {
    console.error(`${PREFIX}[${stage}] ${message}`, details);
}
