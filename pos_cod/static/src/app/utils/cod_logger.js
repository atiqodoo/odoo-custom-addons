/**
 * @module pos_cod/app/utils/cod_logger
 *
 * COD module logging utility.
 *
 * All output is prefixed with [COD] so it can be isolated in Chrome DevTools:
 *   Filter box → type: [COD]
 *
 * Log levels:
 *   codLog   — debug/trace (only when COD_DEBUG = true)
 *   codWarn  — always-on info/state changes (mirrors _logger.warning in Python)
 *   codError — always-on errors
 *   codTable — tabular data dump (debug only)
 *   codGroup — grouped trace block (debug only)
 *
 * Usage:
 *   import { codLog, codWarn, codError } from "@pos_cod/app/utils/cod_logger";
 *   codWarn("CodService", "fetchOrders", "Loaded 3 pending orders", { count: 3 });
 */

/** Set to false to suppress debug-level output in production. */
export const COD_DEBUG = true;

const PREFIX = "[COD]";

/**
 * Debug-level log — collapsed group, only when COD_DEBUG is true.
 * @param {string} component  Class or module name
 * @param {string} method     Method or event name
 * @param {...*}   args       Any additional values to log
 */
export function codLog(component, method, ...args) {
    if (!COD_DEBUG) return;
    console.groupCollapsed(`${PREFIX}[${component}::${method}]`);
    for (const a of args) {
        if (typeof a === "object" && a !== null) {
            console.dir(a);
        } else {
            console.log(a);
        }
    }
    console.groupEnd();
}

/**
 * Always-on warning — important state changes and RPC results.
 * Matches the _logger.warning level used in the Python backend.
 * @param {string} component
 * @param {string} method
 * @param {...*}   args
 */
export function codWarn(component, method, ...args) {
    console.warn(`${PREFIX}[${component}::${method}]`, ...args);
}

/**
 * Always-on error — unexpected failures, validation errors.
 * @param {string} component
 * @param {string} method
 * @param {...*}   args
 */
export function codError(component, method, ...args) {
    console.error(`${PREFIX}[${component}::${method}]`, ...args);
}

/**
 * Debug-level table dump — useful for inspecting order lists.
 * @param {string}   component
 * @param {string}   method
 * @param {Object[]} rows
 */
export function codTable(component, method, rows) {
    if (!COD_DEBUG) return;
    console.warn(`${PREFIX}[${component}::${method}] table:`);
    console.table(rows);
}

/**
 * Debug-level grouped block — use for multi-value trace dumps.
 * @param {string}   label    Label for the collapsed group
 * @param {Function} fn       Function that executes the inner console calls
 */
export function codGroup(label, fn) {
    if (!COD_DEBUG) return;
    console.groupCollapsed(`${PREFIX} ${label}`);
    try { fn(); } finally { console.groupEnd(); }
}
