/**
 * @module pos_credit_limit/app/validators/credit_limit_validator
 *
 * Gate 2: Credit Limit Check.
 *
 * Handles four distinct credit scenarios after Gate 1 passes:
 *
 *   A. Deposit path (Issue 1):
 *      Customer has no credit line (creditLimit ≤ 0) but a prepaid deposit
 *      (backendTotalDue < 0). Allow up to the deposit balance.
 *      Shows DepositPopup to inform cashier.
 *
 *   B. Full block:
 *      True Balance + order total > creditLimit AND no available credit headroom.
 *      Shows CreditLimitPopup with full breakdown.
 *
 *   C. Partial payment (Issue 2):
 *      True Balance + full order > creditLimit, BUT some credit headroom remains.
 *      Shows PartialCreditPopup; cashier can confirm a reduced charge on account.
 *      Returns { allowed: true, partialAmount } so caller can preset the line amount.
 *
 *   D. Full approval:
 *      True Balance + order total ≤ creditLimit.
 *      Returns { allowed: true } immediately.
 *
 * Issue 3 (double-counting) is handled inside calculateUnsyncedAmount
 * via terminal-state filtering — see true_balance_calculator.js.
 *
 * Issue 4 (session incoming payments) is handled via the sessionIncomingPayments
 * parameter, fetched by the Gate 3 Python RPC and passed through here.
 *
 * Return type:
 *   { allowed: false }                          — caller must NOT add payment line
 *   { allowed: true }                           — proceed normally
 *   { allowed: true, partialAmount: number }    — proceed; preset line to partialAmount
 *
 * Accounting safety: READ-ONLY. No model writes.
 */

import { CreditLimitPopup }   from "@pos_credit_limit/app/dialogs/credit_limit_popup";
import { DepositPopup, DepositPartialPopup } from "@pos_credit_limit/app/dialogs/deposit_popup";
import { PartialCreditPopup } from "@pos_credit_limit/app/dialogs/partial_credit_popup";
import {
    calculateUnsyncedAmount,
    calculateTrueBalance,
    calculateAvailableCredit,
    isWithinCreditLimit,
    formatMoney,
} from "@pos_credit_limit/app/calculators/true_balance_calculator";

/** Filter devtools output: type [PCL-Gate2] in the console filter box */
const LOG_PREFIX = "[PCL-Gate2]";
const DEBUG = false;

/**
 * Run Gate 2: credit limit check using the True Balance formula.
 *
 * @param {Object} params
 * @param {number}   params.backendTotalDue         - Live `credit` from Gate 3 RPC.
 *                                                    Negative = customer has a deposit.
 * @param {number}   params.creditLimit             - Customer's credit_limit
 * @param {number}   params.depositBalance          - max(0, -backendTotalDue); from Gate 3 RPC
 * @param {number}   params.orderTotal              - Current order total (with tax)
 * @param {Object[]} params.allOrders               - All orders from pos.models["pos.order"].getAll()
 * @param {number}   params.partnerId               - Customer's res.partner ID
 * @param {number}   params.creditMethodId          - ID of the pcl_is_credit_method payment method
 * @param {number}   [params.sessionIncomingPayments=0] - Unposted session cash/card receipts
 *                                                    from this customer. Reduces True Balance.
 * @param {Object}   params.dialogService           - Odoo dialog service (this.dialog)
 * @param {string}   [params.currencySymbol=""]     - Currency symbol for popup display
 * @returns {Promise<{allowed: boolean, partialAmount?: number}>}
 */
export async function validateCreditLimit({
    backendTotalDue,
    creditLimit,
    depositBalance,
    orderTotal,
    allOrders,
    partnerId,
    creditMethodId,
    sessionIncomingPayments = 0,
    dialogService,
    currencySymbol = "",
}) {
    // Always-on trace — Gate 2 full input set in browser console
    console.warn(
        `${LOG_PREFIX} ── Gate 2 inputs ──────────────────────────────────────\n` +
        `  backendTotalDue:         ${backendTotalDue}\n` +
        `  depositBalance:          ${depositBalance}\n` +
        `  creditLimit:             ${creditLimit}\n` +
        `  orderTotal:              ${orderTotal}\n` +
        `  sessionIncomingPayments: ${sessionIncomingPayments}\n` +
        `  partnerId:               ${partnerId}\n` +
        `  creditMethodId:          ${creditMethodId}`
    );

    // ── Step 1: Unsynced local credit exposure ────────────────────────────────
    // Sum Customer Account payment lines in locally-held, unsynced orders.
    // Issue 3: terminal-state filter inside calculateUnsyncedAmount prevents
    //          counting orders the backend already knows about.
    const unsyncedAmount = calculateUnsyncedAmount(allOrders, partnerId, creditMethodId);

    // ── Step 2: True Balance ──────────────────────────────────────────────────
    // Formula: backendTotalDue + unsyncedCharges - sessionIncomingPayments
    // Issue 4: sessionIncomingPayments subtracts cash/card payments received
    //          from this customer in the current session (not yet posted).
    const trueBalance = calculateTrueBalance(backendTotalDue, unsyncedAmount, sessionIncomingPayments);

    // ── SCENARIO A: Deposit path ──────────────────────────────────────────────
    // Customer has NO credit line (creditLimit ≤ 0) but has usable funds.
    //
    // effectiveDepositBalance = max(0, -trueBalance) covers two sources:
    //   1. Accounting deposit: partner.credit < 0 (already posted).
    //   2. Same-session deposit: customer paid into their account earlier in
    //      THIS session via a no-product POS order (not yet posted to accounting).
    //      partner.credit has not been updated yet — but session_incoming_payments
    //      is already subtracted inside trueBalance, so -trueBalance captures it.
    //
    // Using effectiveDepositBalance here fixes Issue 1 (same-session deposits).
    const effectiveDepositBalance = Math.max(0, round2(-trueBalance));

    if (creditLimit <= 0 && effectiveDepositBalance > 0) {
        console.warn(
            `${LOG_PREFIX} Deposit path — creditLimit=${creditLimit}` +
            ` depositBalance(backend)=${depositBalance}` +
            ` effectiveDepositBalance=${effectiveDepositBalance}` +
            ` orderTotal=${orderTotal}`
        );

        if (orderTotal <= effectiveDepositBalance) {
            // Order fits within deposit → ALLOW after informing cashier
            console.warn(
                `${LOG_PREFIX} ALLOWED via deposit — orderTotal ${orderTotal}` +
                ` ≤ effectiveDeposit ${effectiveDepositBalance}`
            );

            await new Promise((resolve) => {
                dialogService.add(
                    DepositPopup,
                    {
                        title:          "Customer Deposit — Payment Approved",
                        depositBalance: formatMoney(effectiveDepositBalance, currencySymbol),
                        orderTotal:     formatMoney(orderTotal,              currencySymbol),
                    },
                    { onClose: resolve }
                );
            });

            return { allowed: true };
        }

        // ── SCENARIO A2: Partial deposit (Issue 2) ────────────────────────────
        // Order exceeds the deposit. Offer to charge the deposit amount on account
        // and let the cashier collect the remainder by cash or card.
        const remainingAmount = round2(orderTotal - effectiveDepositBalance);

        console.warn(
            `${LOG_PREFIX} Partial deposit path — charge ${effectiveDepositBalance} on account,` +
            ` collect ${remainingAmount} by other method`
        );

        let confirmed = false;

        await new Promise((resolve) => {
            dialogService.add(
                DepositPartialPopup,
                {
                    title:          "Partial Deposit Payment",
                    depositBalance: formatMoney(effectiveDepositBalance, currencySymbol),
                    orderTotal:     formatMoney(orderTotal,              currencySymbol),
                    remainingAmount: formatMoney(remainingAmount,        currencySymbol),
                    onConfirm: () => { confirmed = true; },
                },
                { onClose: resolve }
            );
        });

        if (confirmed) {
            console.warn(
                `${LOG_PREFIX} Partial deposit CONFIRMED — partialAmount: ${effectiveDepositBalance}`
            );
            return { allowed: true, partialAmount: effectiveDepositBalance };
        }

        console.warn(`${LOG_PREFIX} Partial deposit CANCELLED by cashier.`);
        return { allowed: false };
    }

    // ── Step 3: Standard credit ceiling check ────────────────────────────────
    const fullyAllowed = isWithinCreditLimit(trueBalance, orderTotal, creditLimit);

    if (fullyAllowed) {
        if (DEBUG) console.log(`${LOG_PREFIX} PASSED — full order within credit limit.`);
        return { allowed: true };
    }

    // ── SCENARIO C: Partial payment (Issue 2) ────────────────────────────────
    // Full order is blocked, but the customer still has SOME credit headroom.
    // Let the cashier charge the available portion on account and pay the rest
    // by another method.
    const availableCredit = calculateAvailableCredit(creditLimit, trueBalance);

    console.warn(
        `${LOG_PREFIX} Full order blocked — availableCredit=${availableCredit} orderTotal=${orderTotal}`
    );

    if (availableCredit > 0) {
        const remainingAmount = round2(orderTotal - availableCredit);

        console.warn(
            `${LOG_PREFIX} Partial path — showing PartialCreditPopup` +
            ` (charge ${availableCredit} on account, pay ${remainingAmount} by other method)`
        );

        let confirmed = false;

        await new Promise((resolve) => {
            dialogService.add(
                PartialCreditPopup,
                {
                    title:           "Partial Credit Available",
                    trueBalance:     formatMoney(trueBalance,     currencySymbol),
                    creditLimit:     formatMoney(creditLimit,     currencySymbol),
                    availableCredit: formatMoney(availableCredit, currencySymbol),
                    orderTotal:      formatMoney(orderTotal,      currencySymbol),
                    remainingAmount: formatMoney(remainingAmount, currencySymbol),
                    onConfirm: () => { confirmed = true; },
                },
                { onClose: resolve }
            );
        });

        if (confirmed) {
            console.warn(`${LOG_PREFIX} Partial payment CONFIRMED — partialAmount: ${availableCredit}`);
            return { allowed: true, partialAmount: availableCredit };
        }

        console.warn(`${LOG_PREFIX} Partial payment CANCELLED by cashier.`);
        return { allowed: false };
    }

    // ── SCENARIO B: Full block ────────────────────────────────────────────────
    const totalExposure = round2(trueBalance + orderTotal);

    console.warn(
        `${LOG_PREFIX} BLOCKED — exposure ${totalExposure} > limit ${creditLimit}` +
        ` (true: ${trueBalance} + order: ${orderTotal})`
    );

    await new Promise((resolve) => {
        dialogService.add(
            CreditLimitPopup,
            {
                title:          "Credit Limit Exceeded",
                backendBalance: formatMoney(backendTotalDue,  currencySymbol),
                depositBalance: formatMoney(depositBalance,   currencySymbol),
                unsyncedAmount: formatMoney(unsyncedAmount,   currencySymbol),
                trueBalance:    formatMoney(trueBalance,      currencySymbol),
                orderTotal:     formatMoney(orderTotal,       currencySymbol),
                totalExposure:  formatMoney(totalExposure,    currencySymbol),
                creditLimit:    formatMoney(creditLimit,      currencySymbol),
            },
            { onClose: resolve }
        );
    });

    return { allowed: false };
}

// ─── Internal helper (not exported) ──────────────────────────────────────────
function round2(value) {
    return Math.round(value * 100) / 100;
}
