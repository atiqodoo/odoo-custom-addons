/**
 * @module pos_credit_limit/app/validators/payment_terms_validator
 *
 * Gate 1: Payment Terms Check.
 *
 * Before any Customer Account payment is added, the selected customer must
 * have a payment term (property_payment_term_id) configured on their partner
 * record.
 *
 * Data source (LIVE — not session snapshot):
 *   payment_term_id is taken from the Gate 3 RPC result (get_credit_info),
 *   NOT from the session-start partner store.
 *
 * ─── Dialog Promise pattern ───────────────────────────────────────────────────
 * The Odoo 18 dialog service ALWAYS overwrites the `close` prop it receives with
 * its own close function:  markRaw({ ...props, close })
 * Do NOT pass `close: resolve` in props — it gets silently ignored.
 * Instead use the third argument `{ onClose: resolve }`, which fires after the
 * dialog service finishes removing the dialog from the overlay.
 *
 * Accounting safety: READ-ONLY. No model writes.
 */

import { NoPaymentTermsPopup } from "@pos_credit_limit/app/dialogs/no_payment_terms_popup";

/** Filter devtools output: type [PCL-Gate1] in the console filter box */
const LOG_PREFIX = "[PCL-Gate1]";
const DEBUG = false;

/**
 * Run Gate 1: verify the customer has a payment term assigned.
 *
 * @param {Object}        partner           - res.partner object (for name in popup only)
 * @param {number|false}  livePaymentTermId - payment_term_id from Gate 3 RPC result
 * @param {string|false}  livePaymentTermName - term name from Gate 3 RPC (for logging)
 * @param {Object}        dialogService     - Odoo dialog service (this.dialog)
 * @returns {Promise<boolean>} true = ALLOWED, false = BLOCKED
 */
export async function validatePaymentTerms(partner, livePaymentTermId, livePaymentTermName, dialogService) {

    console.warn(
        `${LOG_PREFIX} ── Gate 1 inputs ──────────────────────────────────────\n` +
        `  partner:              ${partner?.name || "Unknown"} (id: ${partner?.id})\n` +
        `  live payment_term_id: ${livePaymentTermId}\n` +
        `  live term name:       ${livePaymentTermName || "(none)"}`
    );

    const hasPaymentTerm = !!livePaymentTermId && livePaymentTermId > 0;

    if (!hasPaymentTerm) {
        console.warn(
            `${LOG_PREFIX} BLOCKED — "${partner?.name || "Unknown"}" has no payment term.` +
            ` live_id=${livePaymentTermId}`
        );

        // IMPORTANT: use { onClose: resolve } in the third argument.
        // The dialog service overwrites props.close with its own function;
        // onClose fires reliably when the dialog overlay is removed.
        await new Promise((resolve) => {
            dialogService.add(
                NoPaymentTermsPopup,
                {
                    title: "No Payment Terms Assigned",
                    body:  `"${partner?.name || "This customer"}" does not have a Payment Term configured. ` +
                           `Customer Account payment requires an agreed payment schedule.`,
                },
                { onClose: resolve }
            );
        });

        if (DEBUG) console.log(`${LOG_PREFIX} Gate 1: dialog dismissed — remaining BLOCKED.`);
        return false; // BLOCKED
    }

    console.warn(`${LOG_PREFIX} PASSED — term="${livePaymentTermName || livePaymentTermId}"`);
    return true; // ALLOWED
}
