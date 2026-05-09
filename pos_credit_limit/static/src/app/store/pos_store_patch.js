/**
 * @module pos_credit_limit/app/store/pos_store_patch
 *
 * Gate 3: Real-Time Sync — PosStore extension.
 *
 * Adds fetchPartnerCreditInfo() to the PosStore so it can be called
 * from the PaymentScreen patch as `this.pos.fetchPartnerCreditInfo(partner)`.
 *
 * Why in the store and not directly in the PaymentScreen patch?
 *   In Odoo 18 POS, server communication goes through `this.data.call()`
 *   which is a method on the PosStore (not available directly on components).
 *   Placing RPC calls in the store is the established Odoo 18 pattern.
 *
 * What this method returns (from Python get_credit_info):
 *   total_due                — live partner.credit (positive = owes us)
 *   credit_limit             — configured credit ceiling
 *   deposit_balance          — max(0, -total_due); non-zero when customer has prepaid funds
 *   session_incoming_payments— sum of cash/card account-settlement payments received from
 *                              this customer in open sessions, not yet posted to accounting
 *   partner_name             — display name
 *   payment_term_id          — live term ID (Gate 1 uses this, not session snapshot)
 *   payment_term_name        — term name for logging
 *
 * Accounting safety:
 *   get_credit_info on the Python side is READ-ONLY (see res_partner_credit.py).
 *   This method creates no records, modifies no records, and does not interact
 *   with account.move or any transactional accounting model.
 */

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

/** Filter devtools output: type [PCL-Gate3] in the console filter box */
const LOG_PREFIX = "[PCL-Gate3]";
const DEBUG = false;

patch(PosStore.prototype, {

    /**
     * Fetch the latest credit figures for a partner from the Odoo backend.
     *
     * Called by payment_screen_patch.js immediately when the cashier taps the
     * Customer Account button — before Gate 1 or Gate 2 are evaluated.
     *
     * Fail-closed policy on network error:
     *   Returns null on any failure. The PaymentScreen patch interprets null
     *   as a hard block — cashier cannot grant credit we cannot verify.
     *
     * @param {Object} partner - res.partner object from the POS store
     * @returns {Promise<{
     *   total_due: number,
     *   credit_limit: number,
     *   deposit_balance: number,
     *   session_incoming_payments: number,
     *   partner_name: string,
     *   payment_term_id: number|false,
     *   payment_term_name: string
     * } | null>}
     */
    async fetchPartnerCreditInfo(partner) {
        if (!partner) {
            console.warn(`${LOG_PREFIX} fetchPartnerCreditInfo called with no partner.`);
            return null;
        }

        // Follow commercial-partner convention: balances tracked on the top-level entity.
        const commercialPartner = partner.parent_id || partner;

        console.warn(
            `${LOG_PREFIX} ── Gate 3 RPC ─────────────────────────────────────────\n` +
            `  Partner:            "${partner.name}" (id: ${partner.id})\n` +
            `  Commercial partner: "${commercialPartner.name}" (id: ${commercialPartner.id})`
        );

        try {
            // Pass POS company_id for correct company_dependent field context.
            // property_payment_term_id is company_dependent (ir.property) — without
            // explicit company context it returns the current user's active company value,
            // which may differ from the POS company in multi-company setups.
            const posCompanyId = this.config?.company_id?.id || false;

            if (DEBUG) {
                console.log(`${LOG_PREFIX} POS company_id: ${posCompanyId}`);
            }

            const result = await this.data.call(
                "res.partner",
                "get_credit_info",
                [commercialPartner.id, posCompanyId],
            );

            if (result.error) {
                console.warn(
                    `${LOG_PREFIX} Backend returned error for partner id ${commercialPartner.id}.`
                );
                return null;
            }

            // Refresh partner's credit in the local store so subsequent reads
            // (e.g. second payment attempt in the same order) use updated figures.
            commercialPartner.update({ credit: result.total_due });

            // Always-on trace — full Gate 3 result visible in browser console
            console.warn(
                `${LOG_PREFIX} ── Gate 3 result ──────────────────────────────────────\n` +
                `  total_due:                ${result.total_due}\n` +
                `  deposit_balance:          ${result.deposit_balance}\n` +
                `  credit_limit:             ${result.credit_limit}\n` +
                `  session_incoming_payments:${result.session_incoming_payments}\n` +
                `  payment_term_id:          ${result.payment_term_id}\n` +
                `  payment_term_name:        "${result.payment_term_name}"\n` +
                `  has_overdue:              ${result.has_overdue}\n` +
                `  overdue_amount:           ${result.overdue_amount}\n` +
                `  overdue_invoice_count:    ${result.overdue_invoice_count}\n` +
                `  oldest_overdue_date:      "${result.oldest_overdue_date}"\n` +
                `  partner_name:             "${result.partner_name}"`
            );

            return {
                total_due:                result.total_due,
                credit_limit:             result.credit_limit,
                deposit_balance:          result.deposit_balance,
                session_incoming_payments: result.session_incoming_payments,
                partner_name:             result.partner_name,
                payment_term_id:          result.payment_term_id,
                payment_term_name:        result.payment_term_name,
                has_overdue:              result.has_overdue,
                overdue_amount:           result.overdue_amount,
                overdue_invoice_count:    result.overdue_invoice_count,
                oldest_overdue_date:      result.oldest_overdue_date,
            };

        } catch (err) {
            // Warn, not error — offline is a valid expected POS state.
            console.warn(
                `${LOG_PREFIX} RPC FAILED — POS may be offline. Partner: "${commercialPartner.name}".`,
                err?.message || err
            );
            return null; // Caller interprets null as fail-closed (block payment)
        }
    },

    async selectPartner() {
        const currentOrder = this.get_order();
        const currentPartner = currentOrder?.get_partner?.();
        const accountLines = (currentOrder?.payment_ids || []).filter((line) => {
            const method = line.payment_method_id;
            return method && (method.type === "pay_later" || method.pcl_is_credit_method);
        });

        if (accountLines.length) {
            console.warn(
                `${LOG_PREFIX} BLOCKED partner change — Customer Account payment line exists` +
                ` | currentPartner=${currentPartner?.name || "none"} (${currentPartner?.id || "none"})` +
                ` | accountLineCount=${accountLines.length}`,
                accountLines.map((line) => ({
                    amount: line.get_amount?.() ?? line.amount,
                    method: line.payment_method_id?.name,
                    approvedPartnerId: line.pcl_approved_partner_id,
                    approvedPartnerName: line.pcl_approved_partner_name,
                }))
            );
            this.dialog.add(AlertDialog, {
                title: _t("Remove Customer Account Payment First"),
                body: _t(
                    "This order already has a Customer Account payment line. Remove that payment line before changing the customer, then add Customer Account again so payment terms, overdue invoices, and credit limit are checked for the selected customer."
                ),
            });
            return currentPartner;
        }

        return await super.selectPartner(...arguments);
    },

});
