/**
 * @module pos_credit_limit/app/payment_screen/payment_screen_patch
 *
 * Main entry point for the POS Credit Limit Control module.
 *
 * Patches PaymentScreen.prototype.addNewPaymentLine to intercept Customer Account
 * payment method selections and run credit validation gates.
 *
 * ─── Full Decision Tree ──────────────────────────────────────────────────────
 *
 *   1. Not a credit method?          → pass through immediately (fast path)
 *   2. No partner on order?          → BLOCK (must select customer first; prevents bypass)
 *   3. Return order?
 *      a. Original had no customer   → BLOCK (ReturnBlockedPopup)
 *      b. Customer mismatch          → BLOCK (ReturnBlockedPopup)
 *      c. Customer matches           → ALLOW (skip Gates 1–2, returns reduce balance)
 *   4. Gate 3: fetchPartnerCreditInfo
 *      - RPC failure (offline)       → BLOCK (fail-closed)
 *   5. Deposit fast-path (Issue 1):
 *      - creditLimit ≤ 0 AND deposit > 0 → Go direct to Gate 2 (skip Gate 1)
 *   6. Gate 1:   validatePaymentTerms → BLOCK if no live payment term
 *   6.5 Gate 1.5: overdue invoices  → BLOCK if any invoice past payment terms due date
 *   7. Gate 2: validateCreditLimit
 *      - { allowed: false }          → BLOCK
 *      - { allowed: true, partialAmount } → add line, preset amount to partialAmount
 *      - { allowed: true }           → add line normally
 *
 * ─── Accounting Safety ───────────────────────────────────────────────────────
 *   This patch ONLY decides whether to call or skip the original
 *   addNewPaymentLine. It does NOT touch account.move, account.move.line,
 *   or any journal entry.
 */

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { validatePaymentTerms } from "@pos_credit_limit/app/validators/payment_terms_validator";
import { validateCreditLimit }  from "@pos_credit_limit/app/validators/credit_limit_validator";
import { ReturnBlockedPopup }   from "@pos_credit_limit/app/dialogs/return_blocked_popup";
import { NoPaymentTermsPopup }     from "@pos_credit_limit/app/dialogs/no_payment_terms_popup";
import { OverdueInvoicesPopup }    from "@pos_credit_limit/app/dialogs/overdue_invoices_popup";
import { formatMoney }             from "@pos_credit_limit/app/calculators/true_balance_calculator";

/** Filter devtools output: type [PCL-Screen] in the console filter box */
const LOG_PREFIX = "[PCL-Screen]";
const DEBUG = false;

patch(PaymentScreen.prototype, {

    /**
     * Intercept Customer Account payment method selection for credit validation.
     *
     * @param {Object} paymentMethod - pos.payment.method record from the POS store
     * @returns {Promise<void>}
     */
    async addNewPaymentLine(paymentMethod) {

        // ── 1. Fast path: non-credit method ──────────────────────────────────
        if (!paymentMethod.pcl_is_credit_method) {
            if (DEBUG) {
                console.log(`${LOG_PREFIX} "${paymentMethod.name}" — not credit, bypassing all gates.`);
            }
            return await super.addNewPaymentLine(...arguments);
        }

        console.warn(
            `${LOG_PREFIX} ══ Customer Account clicked ══════════════════════════\n` +
            `  Method: "${paymentMethod.name}" (id: ${paymentMethod.id})`
        );

        // ── 2. Resolve partner ────────────────────────────────────────────────
        const partner = this.currentOrder?.partner_id;

        if (!partner) {
            // BLOCK — do NOT call super.
            // Calling super without a partner would let the base POS add the
            // Customer Account line unchecked. The cashier could then assign any
            // customer (including one that is overdue or over-limit) and the credit
            // gates would never run against that customer.
            console.warn(`${LOG_PREFIX} BLOCKED — Customer Account clicked with no customer on order.`);

            await new Promise((resolve) => {
                this.dialog.add(
                    NoPaymentTermsPopup,
                    {
                        title: "Select a Customer First",
                        body:  "You must select a customer before adding a Customer Account payment. " +
                               "Credit checks cannot run without a customer assigned to this order.",
                    },
                    { onClose: resolve }
                );
            });
            return;
        }

        console.warn(`${LOG_PREFIX} Partner: "${partner.name}" (id: ${partner.id})`);

        // ── 3. Return order check (Issue 5) ───────────────────────────────────
        // currentOrder.return_pos_order_id is set when this order is a product return.
        const returnOrderRef = this.currentOrder?.return_pos_order_id;
        const isReturn = !!returnOrderRef;

        if (isReturn) {
            console.warn(`${LOG_PREFIX} Return order detected — return_pos_order_id: ${JSON.stringify(returnOrderRef?.id ?? returnOrderRef)}`);
            return await this._pclHandleReturn(paymentMethod, partner, returnOrderRef);
        }

        // ── 4. Gate 3: Real-Time Sync ─────────────────────────────────────────
        const liveCredit = await this.pos.fetchPartnerCreditInfo(partner);

        if (!liveCredit) {
            console.warn(
                `${LOG_PREFIX} BLOCKED — Gate 3 RPC failed. Cannot confirm balance for "${partner.name}".`
            );
            return;
        }

        const orderTotal  = this.currentOrder.get_total_with_tax();
        const allOrders   = this.pos.models?.["pos.order"]?.getAll?.() || [];
        const creditLimit = liveCredit.credit_limit;

        console.warn(
            `${LOG_PREFIX} Gate 3 OK — orderTotal: ${orderTotal} | currency: ${this.pos.currency?.symbol}`
        );

        // ── 4.5. Gate 1.5 pre-check for deposit path ─────────────────────────
        // Overdue check applies even when the customer is spending their own deposit.
        // A customer with overdue invoices must settle them first regardless of
        // whether they are drawing from a credit line or a prepaid deposit.
        if (liveCredit.has_overdue) {
            console.warn(
                `${LOG_PREFIX} BLOCKED (pre-deposit) — Gate 1.5 overdue invoices` +
                ` | count=${liveCredit.overdue_invoice_count}` +
                ` | amount=${liveCredit.overdue_amount}` +
                ` | oldest=${liveCredit.oldest_overdue_date}`
            );

            await new Promise((resolve) => {
                this.dialog.add(
                    OverdueInvoicesPopup,
                    {
                        title:             "Overdue Invoices — Credit Blocked",
                        partnerName:       liveCredit.partner_name || partner.name,
                        overdueCount:      liveCredit.overdue_invoice_count,
                        overdueAmount:     formatMoney(liveCredit.overdue_amount, this.pos.currency?.symbol || ""),
                        oldestOverdueDate: liveCredit.oldest_overdue_date,
                    },
                    { onClose: resolve }
                );
            });
            return;
        }

        // ── 5. Deposit fast-path (Issue 1) ────────────────────────────────────
        // When creditLimit ≤ 0 AND deposit_balance > 0, the customer has no credit
        // line but has prepaid funds. Allow WITHOUT requiring payment terms (Gate 1).
        // session_incoming_payments may represent a deposit made earlier in THIS
        // session — partner.credit has not yet been updated (posted only on close).
        const depositBalance          = liveCredit.deposit_balance          || 0;
        const sessionIncomingPayments = liveCredit.session_incoming_payments || 0;

        if (creditLimit <= 0 && (depositBalance > 0 || sessionIncomingPayments > 0)) {
            console.warn(
                `${LOG_PREFIX} Deposit fast-path — creditLimit=${creditLimit}` +
                ` deposit=${depositBalance} sessionIncoming=${sessionIncomingPayments}` +
                ` — skipping Gate 1 (no payment terms required for own deposit)`
            );

            const gate2Result = await validateCreditLimit({
                backendTotalDue:          liveCredit.total_due,
                creditLimit,
                depositBalance,
                orderTotal,
                allOrders,
                partnerId:                partner.id,
                creditMethodId:           paymentMethod.id,
                sessionIncomingPayments:  liveCredit.session_incoming_payments || 0,
                dialogService:            this.dialog,
                currencySymbol:           this.pos.currency?.symbol || "",
            });

            if (!gate2Result.allowed) return;

            // Direct add — bypass super here because calling super.addNewPaymentLine
            // after an awaited dialog (DepositPopup) can cause OWL to discard the
            // reactive update during reconciliation of the dialog teardown cycle.
            // We replicate exactly what the base addNewPaymentLine does for pay_later:
            //   1. add_paymentline creates the line and selects it
            //   2. numberBuffer.reset() clears the keypad
            // The pay_later notification in the base is non-essential; we skip it here.
            const lineCountBefore = (this.currentOrder.payment_ids || []).length;
            console.warn(`${LOG_PREFIX} Deposit path — adding payment line directly (lines before: ${lineCountBefore})`);

            try {
                const newLine = this.currentOrder.add_paymentline(paymentMethod);
                if (newLine) {
                    console.warn(`${LOG_PREFIX} Payment line added — id: ${newLine.id}, amount: ${newLine.amount}`);
                    this.numberBuffer.reset();
                    if (gate2Result.partialAmount !== undefined && gate2Result.partialAmount !== null) {
                        newLine.set_amount(gate2Result.partialAmount);
                        console.warn(`${LOG_PREFIX} Partial amount set to ${gate2Result.partialAmount}`);
                    }
                } else {
                    console.warn(`${LOG_PREFIX} add_paymentline returned false — electronic payment in progress`);
                }
            } catch (err) {
                console.error(`${LOG_PREFIX} ERROR adding payment line in deposit path:`, err?.message || err);
            }
            return;
        }

        // ── 6. Gate 1: Payment Terms ──────────────────────────────────────────
        const gate1Passed = await validatePaymentTerms(
            partner,
            liveCredit.payment_term_id,
            liveCredit.payment_term_name,
            this.dialog
        );
        if (!gate1Passed) return;

        // ── 7. Gate 2: Credit Limit ───────────────────────────────────────────
        const gate2Result = await validateCreditLimit({
            backendTotalDue:          liveCredit.total_due,
            creditLimit,
            depositBalance,
            orderTotal,
            allOrders,
            partnerId:                partner.id,
            creditMethodId:           paymentMethod.id,
            sessionIncomingPayments:  liveCredit.session_incoming_payments || 0,
            dialogService:            this.dialog,
            currencySymbol:           this.pos.currency?.symbol || "",
        });

        if (!gate2Result.allowed) return;

        // ── All Gates Passed ──────────────────────────────────────────────────
        console.warn(`${LOG_PREFIX} All gates PASSED — proceeding with Customer Account payment.`);

        if (gate2Result.partialAmount !== undefined && gate2Result.partialAmount !== null) {
            // Partial path: Gate 2 showed PartialCreditPopup (an awaited dialog).
            // Same OWL-reconciliation risk as the deposit path — add the line directly
            // rather than calling super after a resolved dialog.
            console.warn(`${LOG_PREFIX} Partial path — adding line directly (partialAmount: ${gate2Result.partialAmount})`);
            try {
                const newLine = this.currentOrder.add_paymentline(paymentMethod);
                if (newLine) {
                    this.numberBuffer.reset();
                    newLine.set_amount(gate2Result.partialAmount);
                    console.warn(`${LOG_PREFIX} Partial line added — amount preset to ${gate2Result.partialAmount}`);
                } else {
                    console.warn(`${LOG_PREFIX} add_paymentline returned false in partial path`);
                }
            } catch (err) {
                console.error(`${LOG_PREFIX} ERROR adding line in partial path:`, err?.message || err);
            }
            return;
        }

        // Full approval (no dialog shown in Gate 2) — safe to call super normally.
        return await super.addNewPaymentLine(paymentMethod);
    },

    // ─── Private helpers ─────────────────────────────────────────────────────

    /**
     * Issue 5: Handle Customer Account selection on a return order.
     *
     * Allow only if the original order was for the SAME customer.
     * Block if the original had no customer or a different one.
     *
     * Returns: credit is allowed (ALLOW) / blocked (no payment line added).
     *
     * @param {Object}        paymentMethod  - the Customer Account method
     * @param {Object}        partner        - current order's partner
     * @param {Object|number} returnOrderRef - return_pos_order_id value
     */
    async _pclHandleReturn(paymentMethod, partner, returnOrderRef) {
        // Resolve original order from the store if possible
        const allOrders = this.pos.models?.["pos.order"]?.getAll?.() || [];

        let originalOrder = null;
        if (returnOrderRef && typeof returnOrderRef === "object") {
            originalOrder = returnOrderRef;
        } else if (typeof returnOrderRef === "number") {
            originalOrder = allOrders.find(
                o => o.id === returnOrderRef || o.server_id === returnOrderRef
            ) || null;
        }

        const origPartner   = originalOrder?.partner_id;
        const origPartnerId = origPartner?.id ?? origPartner ?? null;

        console.warn(
            `${LOG_PREFIX} Return check | origPartnerId=${origPartnerId}` +
            ` | currentPartnerId=${partner.id}`
        );

        if (!origPartnerId) {
            // Case A: original order had NO customer — block
            const msg = originalOrder
                ? `The original POS order had no customer assigned. Cannot route this return to "${partner.name || "Unknown"}"'s Customer Account.`
                : `The original POS order (ref: ${returnOrderRef}) is not available in this session.` +
                  ` Cannot verify it was assigned to "${partner.name || "Unknown"}". Use cash or card for this return.`;

            console.warn(`${LOG_PREFIX} BLOCKED — return: ${msg}`);

            await new Promise((resolve) => {
                this.dialog.add(
                    ReturnBlockedPopup,
                    { title: "Return on Account Blocked", body: msg },
                    { onClose: resolve }
                );
            });

            return; // BLOCKED
        }

        if (origPartnerId !== partner.id) {
            // Case B: customer mismatch — block
            const msg =
                `This return belongs to a different customer (original partner id: ${origPartnerId}). ` +
                `Cannot process it on "${partner.name || "Unknown"}"'s account.`;

            console.warn(`${LOG_PREFIX} BLOCKED — return customer mismatch: ${msg}`);

            await new Promise((resolve) => {
                this.dialog.add(
                    ReturnBlockedPopup,
                    { title: "Customer Mismatch on Return", body: msg },
                    { onClose: resolve }
                );
            });

            return; // BLOCKED
        }

        // Case C: same customer — allow without credit limit check
        // (the return reduces the customer's balance; no limit is consumed)
        console.warn(
            `${LOG_PREFIX} Return on account ALLOWED — customer matches original (id: ${partner.id})`
        );
        return await super.addNewPaymentLine(paymentMethod);
    },

    /**
     * Issue 2: After adding the Customer Account payment line, if Gate 2 determined
     * a partial amount, preset the line to that amount so the cashier sees it.
     *
     * The cashier can reduce it further but should not need to increase it.
     *
     * @param {number|undefined} partialAmount - availableCredit from Gate 2, or undefined
     * @param {number}           creditMethodId
     */
    _pclSetPartialAmount(partialAmount, creditMethodId) {
        if (partialAmount === undefined || partialAmount === null) return;

        // The newly added line is selected after addNewPaymentLine().
        const selectedLine = this.currentOrder?.selected_paymentline;

        if (selectedLine) {
            const lineMethodId = selectedLine.payment_method_id?.id ?? selectedLine.payment_method_id;
            if (lineMethodId === creditMethodId) {
                selectedLine.amount = partialAmount;
                console.warn(
                    `${LOG_PREFIX} Partial amount preset to ${partialAmount} on new credit line.`
                );
                return;
            }
        }

        // Fallback: find the last credit line if selected_paymentline is not the one we added
        const paymentLines = this.currentOrder?.payment_ids || [];
        for (let i = paymentLines.length - 1; i >= 0; i--) {
            const line = paymentLines[i];
            const lineMethodId = line.payment_method_id?.id ?? line.payment_method_id;
            if (lineMethodId === creditMethodId) {
                line.amount = partialAmount;
                console.warn(
                    `${LOG_PREFIX} Partial amount preset (fallback) to ${partialAmount} on credit line[${i}].`
                );
                return;
            }
        }

        console.warn(`${LOG_PREFIX} Could not find newly added credit line to preset partial amount.`);
    },

});
