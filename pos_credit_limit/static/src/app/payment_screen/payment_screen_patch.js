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
        if (!this._pclIsCustomerAccountMethod(paymentMethod)) {
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
        const isReturn = !!returnOrderRef || this._pclHasRefundLines(this.currentOrder);

        if (isReturn) {
            console.warn(`${LOG_PREFIX} Return order detected — return_pos_order_id: ${JSON.stringify(returnOrderRef?.id ?? returnOrderRef)}`);
            return await this._pclHandleReturn(paymentMethod, partner, returnOrderRef);
        }

        // ── 4. Gate 3: Real-Time Sync ─────────────────────────────────────────
        if (this._pclIsAccountSettlementOrDepositOrder(this.currentOrder)) {
            console.warn(
                `${LOG_PREFIX} Account settlement/deposit detected — empty order with Customer Account. ` +
                `Skipping payment terms, overdue invoice, and credit limit gates.`
            );
            const added = await super.addNewPaymentLine(paymentMethod);
            if (added) {
                this._pclStampCustomerAccountLine(this.currentOrder.get_selected_paymentline(), partner);
            }
            return added;
        }

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
                    this._pclStampCustomerAccountLine(newLine, partner);
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
                    this._pclStampCustomerAccountLine(newLine, partner);
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
        const added = await super.addNewPaymentLine(paymentMethod);
        if (added) {
            this._pclStampCustomerAccountLine(this.currentOrder.get_selected_paymentline(), partner);
        }
        return added;
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
        const originalOrder = this._pclResolveOriginalReturnOrder(returnOrderRef);

        const origPartner   = originalOrder?.partner_id;
        const origPartnerId = origPartner?.id ?? origPartner ?? null;
        const originalPaidByCustomerAccount =
            this._pclOrderPaidByCustomerAccount(originalOrder);

        console.warn(
            `${LOG_PREFIX} Return check | origPartnerId=${origPartnerId}` +
            ` | currentPartnerId=${partner.id}` +
            ` | originalPaidByCustomerAccount=${originalPaidByCustomerAccount}`
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

        if (!originalPaidByCustomerAccount) {
            const msg =
                `The original POS order was not paid by Customer Account. ` +
                `Use the original refund method for this return.`;

            console.warn(`${LOG_PREFIX} BLOCKED — return original payment is not Customer Account: ${msg}`);

            await new Promise((resolve) => {
                this.dialog.add(
                    ReturnBlockedPopup,
                    { title: "Return on Account Blocked", body: msg },
                    { onClose: resolve }
                );
            });

            return; // BLOCKED
        }

        // Case C: same customer + original Customer Account payment — allow
        // without payment-terms, overdue-invoice, or credit-limit validation.
        console.warn(
            `${LOG_PREFIX} Return on account ALLOWED — original was Customer Account ` +
            `and customer matches (id: ${partner.id}); skipping Gate 1 / Gate 1.5 / Gate 2.`
        );
        const added = await super.addNewPaymentLine(paymentMethod);
        if (added) {
            this._pclStampCustomerAccountLine(this.currentOrder.get_selected_paymentline(), partner);
        }
        return added;
    },

    async _isOrderValid(isForceValidate) {
        const accountGuardOk = await this._pclValidateCustomerAccountLinesBeforeOrderValidation();
        if (!accountGuardOk) {
            return false;
        }
        return await super._isOrderValid(...arguments);
    },

    _pclIsCustomerAccountMethod(paymentMethod) {
        return Boolean(
            paymentMethod &&
            (paymentMethod.type === "pay_later" || paymentMethod.pcl_is_credit_method)
        );
    },

    _pclHasRefundLines(order) {
        return Boolean(
            (order?.lines || []).some((line) => line.refunded_orderline_id)
        );
    },

    _pclIsAccountSettlementOrDepositOrder(order) {
        if (!order) {
            return false;
        }
        const rawLines = order.get_orderlines?.() || order.lines || [];
        const saleLines = rawLines.filter((line) => {
            const qty = Math.abs(line.qty ?? line.get_quantity?.() ?? 0);
            return !line.is_reward_line && qty > 0;
        });
        const isEmptyAccountOrder = saleLines.length === 0;
        console.warn(
            `${LOG_PREFIX} Settlement/deposit check | order=${order.name || order.id}` +
            ` | rawLineCount=${rawLines.length}` +
            ` | saleLineCount=${saleLines.length}` +
            ` | paymentLineCount=${(order.payment_ids || []).length}` +
            ` | isEmptyAccountOrder=${isEmptyAccountOrder}`
        );
        return isEmptyAccountOrder;
    },

    _pclResolveOriginalReturnOrder(returnOrderRef) {
        const allOrders = this.pos.models?.["pos.order"]?.getAll?.() || [];

        if (returnOrderRef && typeof returnOrderRef === "object") {
            return returnOrderRef;
        }
        if (typeof returnOrderRef === "number") {
            const found = allOrders.find(
                (order) => order.id === returnOrderRef || order.server_id === returnOrderRef
            );
            if (found) return found;
        }

        for (const line of this.currentOrder?.lines || []) {
            const refLine = line.refunded_orderline_id;
            const refOrder = refLine && typeof refLine === "object"
                ? refLine.order_id
                : null;
            if (refOrder && typeof refOrder === "object") {
                console.warn(
                    `${LOG_PREFIX} Original return order resolved from refunded_orderline_id: ` +
                    `${refOrder.name || refOrder.id}`
                );
                return refOrder;
            }
        }

        console.warn(
            `${LOG_PREFIX} Could not resolve original return order from return_pos_order_id ` +
            `or refunded_orderline_id.`
        );
        return null;
    },

    _pclOrderPaidByCustomerAccount(order) {
        const payments = order?.payment_ids || [];
        const customerAccountPayments = payments.filter((payment) =>
            this._pclIsCustomerAccountMethod(payment.payment_method_id)
        );

        console.warn(
            `${LOG_PREFIX} Original payment scan | order=${order?.name || order?.id || "unknown"} | ` +
            `paymentCount=${payments.length} | customerAccountCount=${customerAccountPayments.length}`,
            payments.map((payment) => ({
                amount: payment.amount,
                methodId: payment.payment_method_id?.id,
                methodName: payment.payment_method_id?.name,
                methodType: payment.payment_method_id?.type,
                pclIsCredit: payment.payment_method_id?.pcl_is_credit_method,
            }))
        );

        return customerAccountPayments.length > 0;
    },

    _pclGetCustomerAccountPaymentLines(order = this.currentOrder) {
        return (order?.payment_ids || []).filter((line) =>
            this._pclIsCustomerAccountMethod(line.payment_method_id)
        );
    },

    _pclStampCustomerAccountLine(paymentLine, partner) {
        if (!paymentLine || !partner || !this._pclIsCustomerAccountMethod(paymentLine.payment_method_id)) {
            return;
        }
        paymentLine.pcl_approved_partner_id = partner.id;
        paymentLine.pcl_approved_partner_name = partner.name || "";
        console.warn(
            `${LOG_PREFIX} Customer Account line stamped | line=${paymentLine.id || paymentLine.uuid}` +
            ` | approvedPartner=${paymentLine.pcl_approved_partner_name} (${partner.id})`
        );
    },

    async _pclValidateCustomerAccountLinesBeforeOrderValidation() {
        const order = this.currentOrder;
        const partner = order?.partner_id;
        const accountLines = this._pclGetCustomerAccountPaymentLines(order);

        if (!accountLines.length) {
            return true;
        }

        if (this._pclIsAccountSettlementOrDepositOrder(order)) {
            console.warn(
                `${LOG_PREFIX} Final guard ALLOW — account settlement/deposit order; ` +
                `skipping payment terms, overdue invoice, and credit limit gates.`
            );
            return true;
        }

        console.warn(
            `${LOG_PREFIX} Final Customer Account guard | accountLineCount=${accountLines.length}` +
            ` | currentPartner=${partner?.name || "none"} (${partner?.id || "none"})`
        );

        if (!partner) {
            await this._pclShowReturnBlocked(
                "Customer Required",
                "Customer Account payment cannot be validated without a customer. Remove the Customer Account payment line or select the approved customer again."
            );
            return false;
        }

        for (const line of accountLines) {
            if (!line.pcl_approved_partner_id) {
                await this._pclShowReturnBlocked(
                    "Recheck Customer Account",
                    "This Customer Account payment line was not stamped with an approved customer. Remove it and add Customer Account again so payment terms, overdue invoices, and credit limit are checked."
                );
                return false;
            }

            if (Number(line.pcl_approved_partner_id) !== Number(partner.id)) {
                console.warn(
                    `${LOG_PREFIX} BLOCKED final validation — partner changed after Customer Account approval` +
                    ` | approved=${line.pcl_approved_partner_name} (${line.pcl_approved_partner_id})` +
                    ` | current=${partner.name} (${partner.id})`
                );
                await this._pclShowReturnBlocked(
                    "Customer Changed After Approval",
                    `Customer Account was approved for "${line.pcl_approved_partner_name}". ` +
                    `The current customer is "${partner.name}". Remove the Customer Account payment line and add it again for the current customer.`
                );
                return false;
            }
        }

        const isReturn = !!order?.return_pos_order_id || this._pclHasRefundLines(order);
        if (isReturn) {
            const originalOrder = this._pclResolveOriginalReturnOrder(order.return_pos_order_id);
            const origPartnerId = originalOrder?.partner_id?.id ?? originalOrder?.partner_id ?? null;
            if (
                originalOrder &&
                Number(origPartnerId) === Number(partner.id) &&
                this._pclOrderPaidByCustomerAccount(originalOrder)
            ) {
                console.warn(`${LOG_PREFIX} Final guard ALLOW — Customer Account return for same original customer.`);
                return true;
            }
        }

        if (this._pclIsAccountSettlementOrDepositOrder(this.currentOrder)) {
            console.warn(
                `${LOG_PREFIX} Account settlement/deposit detected — empty order with Customer Account. ` +
                `Skipping payment terms, overdue invoice, and credit limit gates.`
            );
            const added = await super.addNewPaymentLine(paymentMethod);
            if (added) {
                this._pclStampCustomerAccountLine(this.currentOrder.get_selected_paymentline(), partner);
            }
            return added;
        }

        const liveCredit = await this.pos.fetchPartnerCreditInfo(partner);
        if (!liveCredit) {
            await this._pclShowReturnBlocked(
                "Customer Account Recheck Failed",
                `Cannot recheck live credit information for "${partner.name}". Remove the Customer Account payment line or try again online.`
            );
            return false;
        }

        if (liveCredit.has_overdue) {
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
            return false;
        }

        const gate1Passed = await validatePaymentTerms(
            partner,
            liveCredit.payment_term_id,
            liveCredit.payment_term_name,
            this.dialog
        );
        if (!gate1Passed) {
            return false;
        }

        const accountAmount = accountLines.reduce(
            (sum, line) => sum + Math.abs(line.get_amount?.() ?? line.amount ?? 0),
            0
        );
        const gate2Result = await validateCreditLimit({
            backendTotalDue:          liveCredit.total_due,
            creditLimit:              liveCredit.credit_limit,
            depositBalance:           liveCredit.deposit_balance || 0,
            orderTotal:               accountAmount,
            allOrders:                (this.pos.models?.["pos.order"]?.getAll?.() || []).filter(
                (candidate) => candidate !== order
            ),
            partnerId:                partner.id,
            creditMethodId:           accountLines[0].payment_method_id.id,
            sessionIncomingPayments:  liveCredit.session_incoming_payments || 0,
            dialogService:            this.dialog,
            currencySymbol:           this.pos.currency?.symbol || "",
        });

        if (!gate2Result.allowed) {
            return false;
        }

        console.warn(`${LOG_PREFIX} Final Customer Account guard PASSED for "${partner.name}".`);
        return true;
    },

    async _pclShowReturnBlocked(title, body) {
        await new Promise((resolve) => {
            this.dialog.add(
                ReturnBlockedPopup,
                { title, body },
                { onClose: resolve }
            );
        });
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
