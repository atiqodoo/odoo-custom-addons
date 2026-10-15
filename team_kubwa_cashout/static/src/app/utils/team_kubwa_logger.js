/** @odoo-module **/
const PREFIX = "[TEAM_KUBWA_POS]";
export function tkLog(area, message, payload = undefined) {
    payload === undefined ? console.log(PREFIX, area, message) : console.log(PREFIX, area, message, payload);
}
export function tkWarn(area, message, payload = undefined) {
    payload === undefined ? console.warn(PREFIX, area, message) : console.warn(PREFIX, area, message, payload);
}
export function tkError(area, message, payload = undefined) {
    payload === undefined ? console.error(PREFIX, area, message) : console.error(PREFIX, area, message, payload);
}

