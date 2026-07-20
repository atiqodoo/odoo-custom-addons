/** @odoo-module **/

const PREFIX = "[Vendor Product Priority]";

export function vendorPriorityLog(event, payload = {}) {
    console.info(`${PREFIX} ${event}`, {
        timestamp: new Date().toISOString(),
        ...payload,
    });
}

export function vendorPriorityDebug(event, payload = {}) {
    console.debug(`${PREFIX} ${event}`, {
        timestamp: new Date().toISOString(),
        ...payload,
    });
}

