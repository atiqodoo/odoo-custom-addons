/** @odoo-module **/

/**
 * Temporary lots identify stock already delivered through the POS oversell
 * workflow.  They are replenishment obligations, not lots that may be selected
 * for a second customer sale.
 */
export const TEMPORARY_POS_LOT_PREFIX = "POS-";
export const TEMPORARY_LOT_GUARD_LOG_PREFIX = "[NegStock][POS_TEMP_LOT_GUARD]";
