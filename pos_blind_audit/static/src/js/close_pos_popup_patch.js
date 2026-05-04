/** @odoo-module **/

// ── MODULE LOAD DIAGNOSTIC ────────────────────────────────────────────────────
// This runs immediately when the JS module is loaded by the browser.
// If you do NOT see this line in the browser console, the file is not in the
// asset bundle: upgrade the module and clear the Odoo asset cache.
// eslint-disable-next-line no-console
console.log("[pos_blind_audit] close_pos_popup_patch.js LOADED ✓", new Date().toISOString());

/**
 * @fileoverview pos_blind_audit – ClosePosPopup OWL component patch.
 *
 * Purpose
 * -------
 * Patches {@link ClosePosPopup} to support the blind-audit closing workflow.
 * When ``pos.config.limit_variance`` is ``true`` for the active session:
 *
 *  1. ``isBlindAudit`` (getter)   → returns ``true``.
 *  2. ``confirm()``               → bypasses ALL frontend difference dialogs
 *                                   and calls ``closeSession()`` directly.
 *                                   Also guards on ``isCashOutValid()``.
 *  3. ``hasUserAuthority()``      → always returns ``true`` (defence-in-depth).
 *  4. ``setup()``                 → adds ``blindAuditState`` reactive object
 *                                   containing ``blindCashOut`` string.
 *  5. ``cashBalance`` (getter)    → counted − cash out (real-time, reactive).
 *  6. ``isCashOutValid()``        → validates cashOut ≥ 0 and ≤ counted.
 *  7. ``closeSession()``          → calls ``save_blind_cash_out`` RPC first,
 *                                   then delegates to original closeSession().
 *
 * The companion XML template (Patch 6) renders:
 *  - A mandatory "Cash Out" text input bound to ``blindAuditState.blindCashOut``.
 *  - A "Cash Balance (Next Opening)" read-only display of ``cashBalance``.
 *
 * Close sequence (blind audit, cash_control ON)
 * ----------------------------------------------
 * confirm()
 *   └─ isCashOutValid()  ← guard; early return if invalid
 *   └─ closeSession()
 *         ├─ save_blind_cash_out RPC   ← persists cashOut on pos.session
 *         ├─ post_closing_cash_details RPC
 *         ├─ update_closing_control_state_session RPC
 *         └─ close_session_from_ui RPC
 *               └─ _blind_audit_check() (Python) → variance gate
 *               └─ [on success] writes blind_cash_balance → pos.config
 *
 * @module pos_blind_audit/app/close_pos_popup_patch
 */

import { useState, useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { parseFloat as parseLocaleFloat } from "@web/views/fields/parsers";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

// ---------------------------------------------------------------------------
// Capture originals BEFORE patching.
// ---------------------------------------------------------------------------

console.log("[pos_blind_audit] ClosePosPopup imported:", typeof ClosePosPopup);

/** @type {Function} Original ClosePosPopup.prototype.setup */
const _originalSetup = ClosePosPopup.prototype.setup;

/** @type {Function} Original ClosePosPopup.prototype.confirm */
const _originalConfirm = ClosePosPopup.prototype.confirm;

/** @type {Function} Original ClosePosPopup.prototype.hasUserAuthority */
const _originalHasUserAuthority = ClosePosPopup.prototype.hasUserAuthority;

/** @type {Function} Original ClosePosPopup.prototype.closeSession */
const _originalCloseSession = ClosePosPopup.prototype.closeSession;

// ---------------------------------------------------------------------------
// Patch
// ---------------------------------------------------------------------------

console.log("[pos_blind_audit] Applying patch to ClosePosPopup.prototype…");

patch(ClosePosPopup.prototype, {

    // -----------------------------------------------------------------------
    // setup() override – adds reactive blindAuditState
    // -----------------------------------------------------------------------

    /**
     * Extends the component's setup to create a separate reactive state object
     * for the blind-audit Cash Out input.
     *
     * A separate ``useState`` (``this.blindAuditState``) is used rather than
     * modifying the existing ``this.state`` object, because OWL reactive
     * proxies do not reliably track property additions after initial creation.
     *
     * ``blindCashOut`` is initialised as the string ``"0"`` to match the
     * format used by the existing ``payments`` state entries (string counts,
     * not raw numbers).
     */
    setup() {
        if (_originalSetup) {
            _originalSetup.call(this);
        }
        this.blindAuditState = useState({ blindCashOut: "", failedAttempts: 0 });
        console.debug(
            "[pos_blind_audit] setup() | blindAuditState initialised.",
        );

        // ── Auto-compute Cash Out from Default Cash Balance (Next Opening) ──
        // Fires whenever the cash count input changes.
        // Formula: Cash Out = Cash Count − default_next_opening_cash
        // Clamped to [0, ∞) so we never suggest a negative withdrawal.
        // Only runs when:
        //   1. Blind audit is active (limit_variance = true)
        //   2. default_next_opening_cash > 0 (manager has configured a target)
        //   3. Cash Count field is non-empty (user has started entering)
        // The cashier can freely edit Cash Out after auto-compute fires.
        // If Cash Count is changed again, auto-compute re-runs (overrides edits).
        useEffect(
            () => {
                if (!this.isBlindAudit) {
                    return;
                }

                const defaultBalance =
                    this.pos?.config?.default_next_opening_cash ?? 0;

                if (defaultBalance <= 0) {
                    console.debug(
                        "[pos_blind_audit] setup() useEffect | "
                        + "default_next_opening_cash=%.2f ≤ 0 — skipping auto-compute.",
                        defaultBalance,
                    );
                    return;
                }

                const cashId = this.props.default_cash_details?.id;
                const countedStr =
                    this.state?.payments?.[cashId]?.counted ?? "";

                if (!countedStr.toString().trim()) {
                    console.debug(
                        "[pos_blind_audit] setup() useEffect | "
                        + "Cash Count empty — skipping auto-compute.",
                    );
                    return;
                }

                let counted = 0;
                try {
                    counted = parseLocaleFloat(countedStr) || 0;
                } catch {
                    counted = 0;
                }

                const suggestedOut = Math.max(0, counted - defaultBalance);
                const suggestedStr = suggestedOut.toFixed(2);

                console.info(
                    "[pos_blind_audit] setup() useEffect | "
                    + "auto-computing Cash Out: counted=%.2f − defaultBalance=%.2f "
                    + "= suggestedOut=%.2f → blindCashOut='%s'",
                    counted,
                    defaultBalance,
                    suggestedOut,
                    suggestedStr,
                );

                this.blindAuditState.blindCashOut = suggestedStr;
            },
            () => [
                // Re-run whenever Cash Count changes.
                this.state?.payments?.[this.props.default_cash_details?.id]?.counted,
            ],
        );
    },

    // -----------------------------------------------------------------------
    // isBlindAudit (getter)
    // -----------------------------------------------------------------------

    /**
     * Returns whether blind-audit mode is active for the current POS config.
     *
     * @returns {boolean} ``true`` when ``pos.config.limit_variance`` is truthy.
     */
    get isBlindAudit() {
        const active = Boolean(this.pos?.config?.limit_variance);
        console.debug(
            "[pos_blind_audit] isBlindAudit=%s | config='%s' | "
            + "limit_variance=%s | variance_amount=%s",
            active,
            this.pos.config.name,
            this.pos.config.limit_variance,
            this.pos.config.variance_amount,
        );
        return active;
    },

    // -----------------------------------------------------------------------
    // cashBalance (getter)
    // -----------------------------------------------------------------------

    /**
     * Real-time computed cash balance = counted − cash out.
     *
     * Both values are parsed with the locale-aware ``parseLocaleFloat`` to
     * correctly handle decimal separators (comma vs period) in any locale.
     * Parsing failures return 0 so the display is always a valid number.
     *
     * Reads:
     *  - ``this.state.payments[default_cash_details.id].counted``
     *  - ``this.blindAuditState.blindCashOut``
     *
     * @returns {number} Cash balance ≥ 0 (or 0 on parse error).
     */
    get cashBalance() {
        const id = this.props.default_cash_details?.id;
        const countedStr = this.state?.payments?.[id]?.counted ?? "0";
        const cashOutStr = this.blindAuditState?.blindCashOut ?? "0";

        let counted = 0;
        let cashOut = 0;

        try { counted = parseLocaleFloat(countedStr) || 0; } catch { counted = 0; }
        try { cashOut = parseLocaleFloat(cashOutStr) || 0; } catch { cashOut = 0; }

        const balance = counted - cashOut;

        console.debug(
            "[pos_blind_audit] cashBalance | counted=%.2f cashOut=%.2f balance=%.2f",
            counted, cashOut, isNaN(balance) ? 0 : balance,
        );

        return isNaN(balance) ? 0 : balance;
    },

    // -----------------------------------------------------------------------
    // isCashOutValid()
    // -----------------------------------------------------------------------

    /**
     * Validates the Cash Out field before allowing the session to close.
     *
     * Rules:
     *  1. ``blindCashOut`` must be a non-empty, parseable number.
     *  2. The parsed value must be ≥ 0.
     *  3. The parsed value must be ≤ the counted cash (when counted is valid).
     *
     * Rule 3 uses a lenient fallback: if the counted string cannot be parsed,
     * the cashOut is considered valid so long as rules 1–2 pass.  The server
     * will perform its own validation on close.
     *
     * @returns {boolean}
     */
    isCashOutValid() {
        const cashOutStr = this.blindAuditState?.blindCashOut ?? "";

        if (!cashOutStr.trim()) {
            return false;
        }

        let cashOut;
        try {
            cashOut = parseLocaleFloat(cashOutStr);
        } catch {
            return false;
        }

        if (isNaN(cashOut) || cashOut < 0) {
            return false;
        }

        const id = this.props.default_cash_details?.id;
        const countedStr = this.state?.payments?.[id]?.counted ?? "";

        if (!countedStr.trim()) {
            return true; // counted not yet entered; server will validate
        }

        let counted;
        try {
            counted = parseLocaleFloat(countedStr);
        } catch {
            return true; // counted unparseable; defer to server
        }

        return !isNaN(counted) ? cashOut <= counted : true;
    },

    // -----------------------------------------------------------------------
    // confirm() override
    // -----------------------------------------------------------------------

    /**
     * Override ``confirm()`` to skip all frontend difference dialogs when
     * blind audit is active, and to guard on ``isCashOutValid()``.
     *
     * Blind audit flow
     * ~~~~~~~~~~~~~~~~
     * ``confirm()``
     *   → isCashOutValid() check (early return if invalid)
     *   → ``closeSession()``  (direct, no dialogs)
     *
     * @returns {Promise<void>}
     */
    async confirm() {
        if (this.isBlindAudit) {
            if (this.pos?.config?.cash_control) {
                // Guard 1: Cash Out must be explicitly entered (even 0 is valid).
                if (!this.isCashOutValid()) {
                    console.warn(
                        "[pos_blind_audit] confirm() BLOCKED — Cash Out not entered or invalid. "
                        + "cashOut='%s'",
                        this.blindAuditState?.blindCashOut,
                    );
                    return; // template error message already visible
                }

                // Guard 2: Discrepancy must be within variance_amount.
                // The Python _blind_audit_check is the authoritative server gate;
                // this is a JS pre-check for immediate UX feedback.
                const maxDiff = this.getMaxDifference();
                const limit = this.pos.config.variance_amount ?? 0;
                if (Number.isFinite(maxDiff) && maxDiff > limit) {
                    // Increment attempt counter (resets on component unmount)
                    this.blindAuditState.failedAttempts++;
                    const attempt = this.blindAuditState.failedAttempts;
                    // Override fires on the 4th failed attempt (3 blocks → 4th succeeds).
                    const isOverride = attempt >= 4;

                    // Capture counted + cashOut for the server audit log
                    const cashId = this.props.default_cash_details?.id;
                    let counted = 0;
                    try {
                        counted = parseLocaleFloat(
                            this.state?.payments?.[cashId]?.counted ?? "0"
                        ) || 0;
                    } catch { counted = 0; }

                    let cashOutVal = 0;
                    try {
                        cashOutVal = parseLocaleFloat(
                            this.blindAuditState.blindCashOut ?? "0"
                        ) || 0;
                    } catch { cashOutVal = 0; }

                    console.warn(
                        "[pos_blind_audit] confirm() BLOCKED — attempt %d | "
                        + "discrepancy %.2f > limit %.2f | override=%s",
                        attempt, maxDiff, limit, isOverride,
                    );

                    if (isOverride) {
                        // 4th attempt: AWAIT the RPC so the server sets
                        // blind_audit_override=True BEFORE closeSession() runs.
                        // Without await, the DB flag might not be committed yet
                        // when close_session_from_ui checks it.
                        console.warn(
                            "[pos_blind_audit] 3 failed attempts — auto-override on attempt 4. "
                            + "Awaiting log RPC to set server-side override flag…",
                        );
                        try {
                            await this.pos.data.call(
                                "pos.session",
                                "log_blind_audit_attempt",
                                [this.pos.session.id],
                                {
                                    attempt_number: attempt,
                                    counted_amount: counted,
                                    cash_out: cashOutVal,
                                    discrepancy: maxDiff,
                                    outcome: "override",
                                },
                            );
                        } catch (err) {
                            console.error("[pos_blind_audit] log_blind_audit_attempt (override) FAILED:", err);
                        }
                        await this.closeSession();
                        return;
                    }

                    // Attempts 1-3: fire-and-forget log, then show generic error.
                    // Do NOT reveal the difference or allowed limit (blind audit).
                    this.pos.data.call(
                        "pos.session",
                        "log_blind_audit_attempt",
                        [this.pos.session.id],
                        {
                            attempt_number: attempt,
                            counted_amount: counted,
                            cash_out: cashOutVal,
                            discrepancy: maxDiff,
                            outcome: "blocked",
                        },
                    ).catch((err) => {
                        console.error("[pos_blind_audit] log_blind_audit_attempt FAILED:", err);
                    });

                    this.dialog.add(AlertDialog, {
                        title: _t("Cash Count Error"),
                        body: _t(
                            "The cash discrepancy is too high.\n\n"
                            + "Please recount the cash and re-enter the amount.",
                        ),
                    });
                    return;
                }
            }

            console.info(
                "[pos_blind_audit] confirm() | Blind audit ACTIVE for config='%s'. "
                + "All guards passed. Calling closeSession() directly.",
                this.pos.config.name,
            );
            await this.closeSession();
            return;
        }

        console.debug(
            "[pos_blind_audit] confirm() | Blind audit INACTIVE for config='%s'. "
            + "Delegating to original confirm().",
            this.pos.config.name,
        );
        return _originalConfirm.call(this);
    },

    // -----------------------------------------------------------------------
    // hasUserAuthority() override
    // -----------------------------------------------------------------------

    /**
     * Override ``hasUserAuthority()`` to prevent frontend authority checks
     * from independently blocking the cashier in blind-audit mode.
     *
     * @returns {boolean} ``true`` unconditionally when blind audit is active;
     *   otherwise delegates to the original implementation.
     */
    hasUserAuthority() {
        if (this.isBlindAudit) {
            console.debug(
                "[pos_blind_audit] hasUserAuthority() | Blind audit active — "
                + "returning true to prevent frontend authority block.",
            );
            return true;
        }

        console.debug(
            "[pos_blind_audit] hasUserAuthority() | Blind audit inactive — "
            + "delegating to original hasUserAuthority().",
        );
        return _originalHasUserAuthority.call(this);
    },

    // -----------------------------------------------------------------------
    // closeSession() override
    // -----------------------------------------------------------------------

    /**
     * Override ``closeSession()`` to persist the Cash Out amount on the
     * server BEFORE the standard closing RPC sequence.
     *
     * Sequence (blind audit + cash_control ON):
     *  1. Parse ``blindAuditState.blindCashOut`` → ``cashOut`` (clamped ≥ 0).
     *  2. Call ``pos.session.save_blind_cash_out(session_id, cashOut)`` RPC.
     *     This writes ``blind_cash_out`` on the pos.session record so that:
     *       - ``blind_cash_balance`` (computed) is correct when
     *         ``close_session_from_ui`` reads it.
     *       - The value is available for the accounting summary view.
     *  3. Delegate to original ``closeSession()`` for the remaining 3 RPCs:
     *       - ``post_closing_cash_details``
     *       - ``update_closing_control_state_session``
     *       - ``close_session_from_ui``  ← writes balance to pos.config on success
     *
     * RPC failures in step 2 are logged but do NOT abort the close — the
     * server-side default of 0.0 is used if the RPC fails.
     *
     * @returns {Promise<*>} Result of the original closeSession().
     */
    async closeSession() {
        if (this.isBlindAudit && this.pos?.config?.cash_control) {
            let cashOut = 0;
            try {
                cashOut = parseLocaleFloat(this.blindAuditState?.blindCashOut ?? "0") || 0;
            } catch {
                cashOut = 0;
            }
            cashOut = Math.max(0, cashOut);

            console.info(
                "[pos_blind_audit] closeSession() | Calling save_blind_cash_out "
                + "| session_id=%s | cashOut=%.2f",
                this.pos.session.id,
                cashOut,
            );

            try {
                await this.pos.data.call(
                    "pos.session",
                    "save_blind_cash_out",
                    [this.pos.session.id, cashOut],
                );
                console.info(
                    "[pos_blind_audit] closeSession() | save_blind_cash_out RPC ✓",
                );
            } catch (err) {
                console.error(
                    "[pos_blind_audit] closeSession() | save_blind_cash_out FAILED — "
                    + "proceeding with default 0.0 on server:",
                    err,
                );
            }
        }

        return _originalCloseSession.call(this);
    },

});

console.log("[pos_blind_audit] Patch applied ✓ — isBlindAudit, cashBalance, isCashOutValid, closeSession registered.");
