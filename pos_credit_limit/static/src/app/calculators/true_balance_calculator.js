/**
 * @module pos_credit_limit/app/calculators/true_balance_calculator
 *
 * Pure financial calculation functions. No OWL, no Odoo services, no side effects.
 * Each function can be unit-tested without a running POS instance.
 *
 * ─── The True Balance Problem ────────────────────────────────────────────────
 *
 * The POS operates as an offline-capable SPA. Orders are created locally in the
 * browser and pushed to the Odoo backend asynchronously. Between the moment a
 * Customer Account payment is recorded locally and the moment that order is
 * synced to the server, the backend's `credit` field on res.partner has NOT yet
 * been updated. The server does not know about the in-progress sale.
 *
 * Additionally, when a customer SETTLES their balance at POS (pays cash toward
 * their outstanding account), that payment is NOT posted to accounting until the
 * POS session closes. The backend `credit` field therefore over-reports their
 * exposure during the same session.
 *
 * True Balance Formula (full):
 *   trueBalance = backendTotalDue + unsyncedCreditCharges - sessionIncomingPayments
 *
 * Where:
 *   backendTotalDue          — partner.credit from server (Gate 3 live RPC).
 *                              Positive = customer OWES us. Negative = they have a deposit.
 *   unsyncedCreditCharges    — Customer Account payment lines in local POS orders
 *                              NOT yet pushed to backend. These INCREASE exposure.
 *   sessionIncomingPayments  — Cash/card payments received from customer in this
 *                              session to settle existing balance, NOT yet posted.
 *                              These DECREASE exposure. Returned by Gate 3 Python RPC.
 *
 * Issue 3 (double-counting) guard:
 *   calculateUnsyncedAmount skips orders that:
 *   - Have server_id set (already on the backend → backend balance includes them)
 *   - Are in a terminal state ('done','invoiced','posted') even without server_id
 *
 * Issue 1 (deposits):
 *   When backendTotalDue < 0 (credit < 0), the customer has a prepaid deposit.
 *   depositBalance = max(0, -backendTotalDue)
 *   If creditLimit ≤ 0 but depositBalance > 0, the customer may buy up to
 *   depositBalance on account (no credit limit consumed).
 *
 * Credit Gate 2 check:
 *   trueBalance + newOrderAmount ≤ creditLimit  →  ALLOW
 *   trueBalance + newOrderAmount >  creditLimit  →  BLOCK (or PARTIAL if some headroom)
 *
 * ─── Accounting Safety ───────────────────────────────────────────────────────
 * These are read-only calculations on data already in the POS frontend store.
 * No accounting model is touched.
 */

// Set true during development/support sessions for verbose output.
// Must be false before production deployment.
const DEBUG = false;

/** Prefix for all console output — filter in devtools by typing [PCL-Calc] */
const LOG_PREFIX = "[PCL-Calc]";

/**
 * Terminal order states — orders in these states have been fully processed.
 * Even if server_id is not yet set (rare race condition), these orders are
 * considered synced/closing and must NOT be double-counted as unsynced exposure.
 * 'paid' is intentionally excluded: a locally-paid but unsynced order IS
 * still unaccounted for on the backend.
 */
const TERMINAL_STATES = new Set(["done", "invoiced", "posted"]);

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Round a number to 2 decimal places to guard against IEEE 754 drift
 * in financial comparisons. e.g. 0.1 + 0.2 = 0.30000000000000004 → 0.30
 *
 * @param {number} value
 * @returns {number}
 */
function round2(value) {
    return Math.round(value * 100) / 100;
}

// ─── Exported Functions ───────────────────────────────────────────────────────

/**
 * Sum all Customer Account (credit) payment lines across every local POS order
 * that has NOT yet been pushed to the backend server for the given partner.
 *
 * "Unsynced" = the order lives only in the browser's in-memory store AND the
 * backend has not yet created a receivable entry for it.
 *
 * Issue 3 fix: orders in terminal states ('done','invoiced','posted') are skipped
 * even when server_id is missing, preventing double-counting in edge cases where
 * server_id assignment lags behind the backend credit update.
 *
 * @param {Object[]} allOrders      - All order objects from pos.models["pos.order"].getAll()
 * @param {number}   partnerId      - res.partner ID of the customer being checked
 * @param {number}   creditMethodId - ID of the pcl_is_credit_method payment method
 * @returns {number} Total unsynced Customer Account exposure for this partner (≥ 0)
 */
export function calculateUnsyncedAmount(allOrders, partnerId, creditMethodId) {

    let unsyncedTotal = 0.0;
    let scannedCount   = 0;
    let skippedSynced  = 0;
    let skippedTerminal = 0;
    let skippedPartner = 0;
    let countedOrders  = [];

    for (const order of allOrders) {
        const orderId = order.id ?? order.server_id ?? "?";

        // ── Guard 1: order already on the server ─────────────────────────────
        // server_id is set after a successful push. Once set, the backend has
        // created the journal entry and updated credit accordingly.
        if (order.server_id) {
            skippedSynced++;
            if (DEBUG) {
                console.log(
                    `${LOG_PREFIX}   Order ${orderId}: SKIP server_id=${order.server_id}` +
                    ` state=${order.state}`
                );
            }
            continue;
        }

        // ── Guard 2: terminal state (Issue 3 double-count fix) ────────────────
        // Orders in 'done','invoiced','posted' are fully closed.
        // Their credit amounts are reflected in the backend credit field.
        // Counting them again here causes double-counting.
        if (order.state && TERMINAL_STATES.has(order.state)) {
            skippedTerminal++;
            if (DEBUG) {
                console.log(
                    `${LOG_PREFIX}   Order ${orderId}: SKIP terminal state=${order.state}`
                );
            }
            continue;
        }

        // ── Guard 3: different customer ───────────────────────────────────────
        const orderPartnerId = order.partner_id?.id ?? order.partner_id;
        if (orderPartnerId !== partnerId) {
            skippedPartner++;
            continue;
        }

        // ── Accumulate credit payment lines ───────────────────────────────────
        const paymentLines = order.payment_ids || [];
        let orderCreditAmount = 0.0;

        for (const line of paymentLines) {
            const method   = line.payment_method_id;
            const methodId = method?.id ?? method;
            if (methodId === creditMethodId) {
                orderCreditAmount += line.amount || 0;
            }
        }

        if (orderCreditAmount !== 0) {
            unsyncedTotal += orderCreditAmount;
            countedOrders.push({ id: orderId, state: order.state, amount: round2(orderCreditAmount) });
        }

        scannedCount++;
    }

    const result = Math.max(0, round2(unsyncedTotal));

    // Always-on diagnostic — shows every scan result in the browser console
    console.warn(
        `${LOG_PREFIX} Unsynced scan | total orders: ${allOrders.length}` +
        ` | scanned (partner match): ${scannedCount}` +
        ` | skipped synced: ${skippedSynced}` +
        ` | skipped terminal: ${skippedTerminal}` +
        ` | skipped other partner: ${skippedPartner}` +
        ` | UNSYNCED CHARGE: ${result}`
    );

    if (countedOrders.length > 0) {
        console.warn(`${LOG_PREFIX} Counted orders:`, JSON.stringify(countedOrders));
    }

    if (DEBUG) {
        console.group(`${LOG_PREFIX} calculateUnsyncedAmount detail`);
        console.log("Partner:", partnerId, "| Method:", creditMethodId);
        console.log("Counted:", countedOrders);
        console.groupEnd();
    }

    return result;
}

/**
 * Compute the True Balance: the customer's real outstanding credit exposure,
 * accounting for unsynced sales AND for session payments not yet posted.
 *
 * Formula:
 *   trueBalance = backendTotalDue + unsyncedCharges - sessionIncomingPayments
 *
 * A negative True Balance means the customer has a net deposit / overpayment.
 *
 * @param {number} backendTotalDue          - `credit` fetched live from server (Gate 3 RPC).
 *                                            Negative = customer has a deposit.
 * @param {number} unsyncedCharges          - result of calculateUnsyncedAmount()
 * @param {number} [sessionIncomingPayments=0] - Cash/card settlements received from customer
 *                                            in this session, not yet posted to accounting.
 *                                            Returned by the Gate 3 Python RPC as
 *                                            `session_incoming_payments`.
 * @returns {number} True Balance (can be negative)
 */
export function calculateTrueBalance(backendTotalDue, unsyncedCharges, sessionIncomingPayments = 0) {
    const trueBalance = round2(backendTotalDue + unsyncedCharges - sessionIncomingPayments);

    // Always-on — shows full True Balance build-up on every gate attempt
    console.warn(
        `${LOG_PREFIX} True Balance = ${backendTotalDue} (backend)` +
        ` + ${unsyncedCharges} (unsynced charges)` +
        ` - ${sessionIncomingPayments} (session payments received)` +
        ` = ${trueBalance}`
    );

    return trueBalance;
}

/**
 * Calculate available credit headroom: how much the customer can still spend
 * on account before hitting their credit ceiling.
 *
 * @param {number} creditLimit  - customer's credit_limit (0 = no credit facility)
 * @param {number} trueBalance  - result of calculateTrueBalance()
 * @returns {number} Available credit (0 if no credit or already at limit)
 */
export function calculateAvailableCredit(creditLimit, trueBalance) {
    if (creditLimit <= 0) return 0;
    return Math.max(0, round2(creditLimit - trueBalance));
}

/**
 * Determine whether placing the current amount on Customer Account would
 * exceed the customer's credit ceiling.
 *
 * @param {number} trueBalance  - result of calculateTrueBalance()
 * @param {number} amount       - amount to charge on account (full order or partial)
 * @param {number} creditLimit  - customer's configured credit_limit (0 = no credit)
 * @returns {boolean} true → WITHIN limit (ALLOW) | false → OVER limit (BLOCK)
 */
export function isWithinCreditLimit(trueBalance, amount, creditLimit) {
    if (creditLimit <= 0) {
        console.warn(`${LOG_PREFIX} credit_limit ≤ 0 (${creditLimit}) — credit blocked unconditionally`);
        return false;
    }

    const totalExposure = round2(trueBalance + amount);
    const allowed       = totalExposure <= creditLimit;

    console.warn(
        `${LOG_PREFIX} isWithinCreditLimit: ${trueBalance} (true) + ${amount} (amount)` +
        ` = ${totalExposure} vs limit ${creditLimit} → ${allowed ? "ALLOW ✓" : "BLOCK ✗"}`
    );

    return allowed;
}

/**
 * Format a monetary amount as a string for popup display.
 * Keeps formatting local to this module so the rest of the code
 * works with raw numbers.
 *
 * @param {number} amount
 * @param {string} [symbol=""] - Currency symbol prefix (e.g. "KES ", "KSh ")
 * @returns {string}
 */
export function formatMoney(amount, symbol = "") {
    return `${symbol}${round2(amount).toFixed(2)}`;
}
