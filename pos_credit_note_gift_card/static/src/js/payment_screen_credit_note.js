/** @odoo-module **/
/**
 * payment_screen_credit_note.js
 * ==============================
 * Patches the POS PaymentScreen to add the "Credit Note (Gift Card)" button.
 *
 * Key design rules for Odoo 18
 * -----------------------------
 * 1. Import ONLY from valid JS/OWL modules — never from .xml files.
 * 2. The OWL Component class that the printer renders (CreditNoteReceiptComponent)
 *    must be declared BEFORE the patch() call so the closure inside
 *    _printCreditNoteReceipt can reference it at call-time.
 * 3. useService() / useState() / onMounted() / onWillUnmount() are valid inside
 *    the patched setup() because setup() runs inside the component's OWL hook
 *    context — super.setup() establishes that context first.
 * 4. this.printer and this.notification are already set by super.setup() — we
 *    do NOT call useService() for them again.
 *
 * Logging
 * -------
 * Set window.CN_DEBUG = true in the browser console for verbose output.
 */

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { useState, onMounted, onWillUnmount, Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ask } from "@point_of_sale/app/store/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

import { CreditNoteService } from "./credit_note_service";
import { ReturnOrderValidator } from "./return_order_validator";

const LOG_PREFIX = "[PaymentScreenCreditNote]";

function dbg(...args) {
    if (window.CN_DEBUG) {
        console.debug(LOG_PREFIX, ...args);
    }
}

// ============================================================================
// OWL Component for the thermal credit-note receipt.
// MUST be declared before patch() so the closure in _printCreditNoteReceipt
// resolves correctly at call-time.
// Template is defined in static/src/xml/credit_note_receipt.xml.
// ============================================================================
export class CreditNoteReceiptComponent extends Component {
    static template = "pos_credit_note_gift_card.CreditNoteReceipt";
    static props = {
        data: { type: Object },
    };
}

// ============================================================================
// PaymentScreen patch
// ============================================================================
patch(PaymentScreen.prototype, {

    // -------------------------------------------------------------------------
    // setup — called during OWL component initialisation (hook context active)
    // -------------------------------------------------------------------------

    setup() {
        super.setup(...arguments);

        // CreditNoteService: plain class, no OWL service registration needed.
        this.creditNoteService = new CreditNoteService(this.env);

        // Track the order whose credit note has already been issued so the
        // button is disabled for the rest of that return transaction.
        this._cnTrackedOrderId = null;

        // Reactive state for the Credit Note UI section.
        // All properties read by the XML template must be declared here.
        this.cnState = useState({
            isRefund:             false,
            hasCreditNoteProgram: false,
            isProcessing:         false,
            returnReason:         "",
            computedAmount:       0,
            computedCurrency:     "",
            breakdown:            [],
            lastCardCode:         "",
            requireReason:        false,
        });

        onMounted(() => {
            this._refreshCnState();
            // Lightweight poll — re-evaluates button state as lines change.
            this._cnPollId = setInterval(() => this._refreshCnState(), 2000);
            dbg("mounted.");
        });

        onWillUnmount(() => {
            if (this._cnPollId) {
                clearInterval(this._cnPollId);
                this._cnPollId = null;
            }
        });
    },

    // -------------------------------------------------------------------------
    // State refresh (called on mount + every 2 s)
    // -------------------------------------------------------------------------

    _refreshCnState() {
        const order  = this.currentOrder;
        const config = this.pos.config;
        const cfg    = ReturnOrderValidator.readConfig(config);

        // When the active order changes, clear the already-issued guard so the
        // button enables again for the new return transaction.
        const orderId = order?.id ?? null;
        if (orderId !== this._cnTrackedOrderId) {
            this._cnTrackedOrderId    = orderId;
            this.cnState.lastCardCode = "";
        }

        this.cnState.isRefund             = ReturnOrderValidator.isRefundOrder(order);
        this.cnState.hasCreditNoteProgram = Boolean(cfg.programId);
        this.cnState.requireReason        = cfg.requireReason;

        dbg("state →", {
            isRefund:             this.cnState.isRefund,
            hasCreditNoteProgram: this.cnState.hasCreditNoteProgram,
        });
    },

    // -------------------------------------------------------------------------
    // Template getters
    // -------------------------------------------------------------------------

    get showCreditNoteButton() {
        return this.cnState.isRefund && this.cnState.hasCreditNoteProgram;
    },

    get creditNoteButtonEnabled() {
        if (this.cnState.isProcessing) return false;
        // Prevent issuing a second gift card for the same return transaction.
        if (this.cnState.lastCardCode) return false;
        const order = this.currentOrder;
        if (!order) return false;

        const lines = (order.lines || []).filter(
            (l) => !l.is_reward_line &&
                   Math.abs(l.qty || l.get_quantity?.() || 0) > 0
        );
        if (!lines.length) return false;

        if (ReturnOrderValidator.hasNonReturnableLines(order).length > 0) return false;

        if (this.cnState.requireReason && !this.cnState.returnReason.trim()) return false;

        return true;
    },

    // -------------------------------------------------------------------------
    // Return reason input handler (bound in XML template)
    // -------------------------------------------------------------------------

    onReturnReasonInput(event) {
        this.cnState.returnReason = event.target.value || "";
    },

    // -------------------------------------------------------------------------
    // Intercept payment method button — automated path
    // -------------------------------------------------------------------------

    /**
     * Override Odoo's addNewPaymentLine so that when the cashier clicks the
     * configured "Credit Note Gift Card" payment method on a return order, the
     * full credit note flow runs automatically instead of just adding a line.
     *
     * For any other payment method (or non-return orders) the call falls
     * through to the original Odoo implementation unchanged.
     */
    async addNewPaymentLine(paymentMethod) {
        // Extract the raw Many2one value — Odoo ORM can return an integer, an
        // object with .id, or false/null when not set.
        const rawCNPM = this.pos.config.credit_note_payment_method_id;
        const configuredPMId =
            (rawCNPM && typeof rawCNPM === "object" ? rawCNPM.id : rawCNPM) || null;

        // Always-on trace — shows ALL intercept conditions so you can diagnose
        // failures in devtools without enabling CN_DEBUG.
        const orderLines = (this.currentOrder?.lines || []).map((l) => ({
            n:   l.product_id?.name || "?",
            qty: l.qty ?? l.get_quantity?.() ?? "?",
            rew: l.is_reward_line,
        }));
        console.log(
            LOG_PREFIX, "[addNewPaymentLine]",
            "| pm.id=", paymentMethod.id, "(", typeof paymentMethod.id, ")",
            "| rawCNPM=", rawCNPM,
            "| configuredPMId=", configuredPMId, "(", typeof configuredPMId, ")",
            "| isRefund=", ReturnOrderValidator.isRefundOrder(this.currentOrder),
            "| lineQtys=", JSON.stringify(orderLines),
            "| lastCardCode=", this.cnState.lastCardCode,
            "| match_strict=", paymentMethod.id === configuredPMId,
            "| match_coerced=", configuredPMId !== null && Number(paymentMethod.id) === Number(configuredPMId),
        );

        // Guard: the credit-note PM is reserved for return orders only.
        // If a cashier clicks it on a normal sale, block it immediately.
        if (
            configuredPMId !== null &&
            Number(paymentMethod.id) === Number(configuredPMId) &&
            !ReturnOrderValidator.isRefundOrder(this.currentOrder)
        ) {
            this.dialog.add(AlertDialog, {
                title: _t("Payment Method Not Available"),
                body:  _t(
                    "This payment method is reserved for credit note returns only " +
                    "and cannot be used on a regular sale."
                ),
            });
            return;
        }

        if (
            configuredPMId !== null &&
            Number(paymentMethod.id) === Number(configuredPMId) &&
            ReturnOrderValidator.isRefundOrder(this.currentOrder) &&
            !this.cnState.lastCardCode     // card not already issued
        ) {
            dbg("addNewPaymentLine: intercepting credit note PM →", paymentMethod.name);
            const order    = this.currentOrder;
            const configId = this.pos.config.id;
            const orderId  = order.id;

            this.cnState.isProcessing = true;
            try {
                // Run steps 1-4 (validate → compute → confirm → issue).
                // Returns the issued cardData, or null if the cashier cancelled.
                const result = await this._runCreditNoteCore(order, orderId, configId);
                if (!result) return;  // cancelled — do NOT add a payment line

                const { cardData, currency } = result;

                // Print receipt before validateOrder() navigates away.
                await this._printCreditNoteReceipt(order, cardData, currency);

                // Add the payment line via the original Odoo logic (amount = get_due()).
                // super here refers to the unpatched PaymentScreen.addNewPaymentLine.
                await super.addNewPaymentLine(paymentMethod);
                dbg("Payment line added via super; due now:", order.get_due?.());

                // Validate the return order — completes inventory + accounting.
                await this.validateOrder(false);

            } catch (err) {
                console.error(LOG_PREFIX, "PM-intercept flow error:", err);
                this.dialog.add(AlertDialog, {
                    title: _t("Credit Note Error"),
                    body:  err.message || String(err),
                });
            } finally {
                this.cnState.isProcessing = false;
            }
            return;  // do NOT fall through to super again
        }

        // Normal payment method — pass straight through.
        return super.addNewPaymentLine(paymentMethod);
    },

    // -------------------------------------------------------------------------
    // Credit Note button click handler (manual / fallback path)
    // -------------------------------------------------------------------------

    async onClickCreditNote() {
        if (!this.creditNoteButtonEnabled) return;

        const order    = this.currentOrder;
        const configId = this.pos.config.id;
        const orderId  = order.id;

        dbg("onClickCreditNote", { orderId, configId });

        this.cnState.isProcessing = true;
        try {
            await this._runCreditNoteFlow(order, orderId, configId);
        } catch (err) {
            console.error(LOG_PREFIX, err);
            this.dialog.add(AlertDialog, {
                title: _t("Credit Note Error"),
                body:  err.message || String(err),
            });
        } finally {
            this.cnState.isProcessing = false;
        }
    },

    // -------------------------------------------------------------------------
    // Core steps 1-4: validate → compute → confirm → issue gift card
    // Shared by both the PM-intercept path and the manual button path.
    // Returns { cardData, netAmount, currency } on success, null if cancelled.
    // -------------------------------------------------------------------------

    async _runCreditNoteCore(order, orderId, configId) {
        // Step 1: client-side validation
        dbg("Step 1: validateReturn (client-side)");
        const validation = ReturnOrderValidator.validateReturn(order, this.pos.config);
        if (!validation.ok) {
            this.dialog.add(AlertDialog, {
                title: _t("Cannot Issue Credit Note"),
                body:  validation.errors.join("\n"),
            });
            return null;
        }
        if (validation.warnings?.length) {
            this.notification.add(validation.warnings.join(" | "), { type: "warning" });
        }

        // Step 2: client-side amount computation
        // Fetch commission data from server for original sale lines first so
        // the deduction is correct (return lines always have these fields zeroed).
        dbg("Step 2: computeAmount (client-side)");
        const cfg          = ReturnOrderValidator.readConfig(this.pos.config);
        const commissionMap = await this._fetchLineCommission(order, cfg);
        const amountData   = ReturnOrderValidator.computeNetAmount(order, this.pos.config, commissionMap);
        const netAmount  = amountData.total || 0;
        const currency   = amountData.currency || "";
        const breakdown  = ReturnOrderValidator.getAdjustedAmountBreakdown(
            amountData.breakdown, currency
        );

        this.cnState.computedAmount   = netAmount;
        this.cnState.computedCurrency = currency;
        this.cnState.breakdown        = breakdown;

        if (netAmount <= 0) {
            this.dialog.add(AlertDialog, {
                title: _t("Zero Credit Note"),
                body:  _t("The net refund amount after adjustments is 0. No gift card will be issued."),
            });
            return null;
        }

        // Step 3: confirm popup
        dbg("Step 3: confirm");
        const confirmed = await this._showConfirmPopup(netAmount, currency, breakdown);
        if (!confirmed) return null;

        // Step 4: issue gift card on the server.
        // orderId is a local string ('pos.order_194') until the order is synced;
        // pass false in that case — the card is still created without the link.
        dbg("Step 4: issue");
        const partner       = order.partner_id;
        const partnerId     = partner ? (partner.id || partner) : false;
        const serverOrderId = (typeof orderId === "number") ? orderId : false;

        const cardData = await this.creditNoteService.issueCreditNote(
            configId, netAmount,
            partnerId, this.cnState.returnReason,
            serverOrderId
        );

        this.cnState.lastCardCode = cardData.code || "";
        dbg("Card issued:", cardData);

        return { cardData, netAmount, currency };
    },

    // -------------------------------------------------------------------------
    // Manual button full flow (uses _runCreditNoteCore + _completeReturnOrder)
    // -------------------------------------------------------------------------

    async _runCreditNoteFlow(order, orderId, configId) {
        const result = await this._runCreditNoteCore(order, orderId, configId);
        if (!result) return;

        const { cardData, netAmount, currency } = result;

        // Print receipt before validateOrder() navigates away.
        dbg("Step 5: print");
        await this._printCreditNoteReceipt(order, cardData, currency);

        // Add configured payment method line + validate the return order.
        dbg("Step 6: complete return order");
        await this._completeReturnOrder(cardData, netAmount, currency);
    },

    // -------------------------------------------------------------------------
    // Confirmation popup
    // -------------------------------------------------------------------------

    async _showConfirmPopup(amount, currency, breakdown) {
        const sym = currency;
        const lines = breakdown.map((b) => {
            let desc = b.product + ": " + b.grossFmt + " → " + b.netFmt;
            if (b.discountAdj > 0) {
                desc += " (disc -" + ReturnOrderValidator.formatCurrency(b.discountAdj, sym) + ")";
            }
            if (b.commissionAdj > 0) {
                desc += " (comm -" + ReturnOrderValidator.formatCurrency(b.commissionAdj, sym) + ")";
            }
            return desc;
        });

        const body = [
            _t("Issue a gift card credit note for:"),
            "",
            ...lines,
            "",
            _t("TOTAL: ") + amount.toFixed(2) + " " + currency,
            "",
            _t("Confirm?"),
        ].join("\n");

        return ask(this.dialog, {
            title: _t("Confirm Credit Note"),
            body:  body,
        });
    },

    // -------------------------------------------------------------------------
    // Fetch commission data for original sale lines (server RPC)
    // -------------------------------------------------------------------------

    /**
     * Collect the IDs of the ORIGINAL (forward-sale) order lines referenced
     * by the current return order's lines, then call the server RPC to get
     * their commission values (total_extra_amount, total_base_profit, qty).
     *
     * Return lines always have those fields zeroed by
     * pos_extra_amount_manager_extended, so we must read the originals.
     *
     * Returns {} when commission mode is 'none' or no original IDs are found.
     *
     * @param {Object} order — POS return order
     * @param {Object} cfg   — result of ReturnOrderValidator.readConfig()
     * @returns {Promise<Object>}  { "id": {total_extra_amount, total_base_profit, qty} }
     */
    async _fetchLineCommission(order, cfg) {
        if (cfg.commissionMode === "none") {
            dbg("_fetchLineCommission: commissionMode=none — skipping RPC");
            return {};
        }

        const lines = (order.lines || []).filter((l) => !l.is_reward_line);
        const refIds = lines.map((l) => {
            const ref = l.refunded_orderline_id;
            if (!ref) return null;
            // ref can be an object (resolved in JS model) or an integer
            const id = typeof ref === "object" ? ref.id : (typeof ref === "number" ? ref : null);
            return (id && typeof id === "number") ? id : null;
        }).filter((id) => id !== null);

        console.log(
            LOG_PREFIX, "[_fetchLineCommission]",
            "| commissionMode=", cfg.commissionMode,
            "| refIds=", refIds,
        );

        if (refIds.length === 0) {
            dbg("_fetchLineCommission: no original line IDs found — returning {}");
            return {};
        }

        try {
            const map = await this.creditNoteService.getLineCommission(refIds);
            console.log(LOG_PREFIX, "[_fetchLineCommission] server map:", JSON.stringify(map));
            return map || {};
        } catch (err) {
            console.warn(LOG_PREFIX, "[_fetchLineCommission] RPC error (falling back to 0):", err);
            return {};
        }
    },

    // -------------------------------------------------------------------------
    // Add gift card payment line and validate the return order
    // -------------------------------------------------------------------------

    /**
     * Find the loyalty payment method linked to the configured gift card
     * program, add it as a payment line on the current return order, then
     * call validateOrder() to finalise the return (inventory + accounting).
     *
     * The gift card payment method must be enabled on this POS terminal
     * (pos.config → Payment Methods).  If it is not found we fall back to
     * a sticky notification so the cashier can complete the payment manually.
     *
     * @param {Object} cardData  — {code, amount, program} from issue endpoint
     * @param {number} netAmount
     * @param {string} currency
     */
    async _completeReturnOrder(cardData, netAmount, currency) {
        const order = this.currentOrder;

        // ------------------------------------------------------------------
        // Find the explicitly configured "Credit Note" payment method.
        // In Odoo 18, gift cards are loyalty reward lines — there is NO
        // auto-created payment method for gift card programs.  The user must
        // create a dedicated Miscellaneous-journal payment method and select
        // it in POS Settings → Credit Note → Payment Method.
        // ------------------------------------------------------------------
        const rawCNPM2 = this.pos.config.credit_note_payment_method_id;
        const configuredPMId =
            (rawCNPM2 && typeof rawCNPM2 === "object" ? rawCNPM2.id : rawCNPM2) || null;

        let giftCardPM = null;
        if (configuredPMId !== null) {
            // In Odoo 18 PaymentScreen, payment methods are in payment_methods_from_config
            // (set in setup() from this.pos.config.payment_method_ids).
            const pms = this.payment_methods_from_config || [];
            giftCardPM = pms.find((pm) => Number(pm.id) === Number(configuredPMId));
            console.log(LOG_PREFIX, "_completeReturnOrder — configuredId:", configuredPMId,
                "| found:", giftCardPM?.name ?? "none",
                "| available PMs:", pms.map((p) => ({ id: p.id, name: p.name })));
        }

        if (giftCardPM) {
            // addPaymentline auto-sets amount to order.get_due() which is
            // negative for a return order (e.g. -500), making get_due() → 0
            // so validateOrder() can proceed cleanly.
            order.addPaymentline(giftCardPM);
            dbg("Payment line added:", giftCardPM.name, "| due now:", order.get_due?.());

            // Validate the return — this syncs to server, decrements inventory,
            // posts accounting entries, then navigates to the receipt screen.
            await this.validateOrder(false);
            // If we reach here the navigation hasn't happened yet; that's fine.
        } else {
            // Gift card PM not in this terminal's payment methods.
            // Inform the cashier; they must complete the payment manually.
            console.warn(
                LOG_PREFIX,
                "Credit note payment method not configured (configuredPMId:", configuredPMId, ")",
                "— cashier must complete the return manually.",
            );
            this.dialog.add(AlertDialog, {
                title: _t("Complete the Return Manually"),
                body: _t(
                    "Gift card issued: %(code)s  (%(amount)s %(currency)s)\n\n" +
                    "No credit-note payment method is configured for this terminal.\n\n" +
                    "To fix: \n" +
                    "1. Accounting → Journals → New → Type: Miscellaneous → Name: 'Credit Note Gift Card'\n" +
                    "2. POS → Configuration → Payment Methods → New → link to that journal\n" +
                    "3. Add the new payment method to this POS terminal (Payment tab)\n" +
                    "4. Select it in POS Settings → Credit Note → Payment Method\n\n" +
                    "For now, add the gift card amount as a payment line manually and validate.",
                    { code: cardData.code, amount: netAmount.toFixed(2), currency }
                ),
            });
        }
    },

    // -------------------------------------------------------------------------
    // Thermal receipt printing
    // -------------------------------------------------------------------------

    /**
     * Build receipt data from client-side order/card objects and render via
     * the POS printer service.  No server round-trip is needed here because
     * all required data is already in the POS session.
     *
     * @param {Object} order    — current POS order (refund)
     * @param {Object} cardData — {code, amount, program} from issue endpoint
     * @param {string} currency — currency name string
     */
    async _printCreditNoteReceipt(order, cardData, currency) {
        const config  = this.pos.config;
        const company = this.pos.company;
        const session = this.pos.session;

        const lines = (order.lines || [])
            .filter((l) => !l.is_reward_line)
            .map((l) => ({
                product:    l.product_id?.display_name || l.product_id?.name || "?",
                qty:        Math.abs(l.qty || l.get_quantity?.() || 0),
                unit_price: l.price_unit || 0,
                discount:   l.discount  || 0,
                subtotal:   Math.abs(l.price_subtotal_incl || 0),
            }));

        const addressParts = [
            company.street, company.city,
            company.state_id?.name, company.country_id?.name,
        ].filter(Boolean);

        const receiptData = {
            company_name:      company.name || "",
            company_address:   addressParts.join(", "),
            company_phone:     company.phone || "",
            pos_name:          config.name || "",
            order_name:        order.name || "",
            date:              order.date_order
                                   ? new Date(order.date_order).toLocaleString()
                                   : new Date().toLocaleString(),
            cashier:           session?.user_id?.name || "",
            lines:             lines,
            amount_total:      Math.abs(order.amount_total || 0),
            currency_symbol:   currency,
            gift_card_code:    cardData.code    || "",
            gift_card_amount:  cardData.amount  || 0,
            gift_card_program: cardData.program || "",
        };

        dbg("Receipt data (client-side):", receiptData);

        try {
            await this.printer.print(
                CreditNoteReceiptComponent,
                { data: receiptData },
                { webPrintFallback: true }
            );
            dbg("Receipt printed.");
        } catch (printErr) {
            console.warn(LOG_PREFIX, "Print error:", printErr);
            this.notification.add(
                _t("Receipt could not be sent to printer: ") +
                (printErr?.body || printErr?.title || String(printErr)),
                { type: "warning" }
            );
        }
    },
});
