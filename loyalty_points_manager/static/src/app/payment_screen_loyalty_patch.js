/** @odoo-module **/

/**
 * payment_screen_loyalty_patch.js
 *
 * Patches PaymentScreen.validateOrder to show a phone-entry popup when the
 * cashier validates an order that has no customer linked.
 *
 * ─── Flow ────────────────────────────────────────────────────────────────
 *   1. Cashier presses "Validate" on a fully-paid order with no customer.
 *   2. LoyaltySelectionPopup opens — cashier types a phone or scans a card.
 *   3. Backend searches res.partner by phone/mobile.
 *      a. FOUND   → partner is loaded into POS store and set on the order.
 *      b. NOT FOUND → the standard Odoo POS "New Customer" form opens,
 *                     pre-filled with the phone number (same form as
 *                     pressing "New" in the POS customer list).
 *                     Cashier fills in name, email, etc. and saves.
 *                     The saved partner is set on the order.
 *   4. super.validateOrder() runs — order is sent to backend with partner_id
 *      so the loyalty earning pipeline (pos_loyalty) attributes points.
 *
 * ─── NOT-FOUND path detail ───────────────────────────────────────────────
 *   Uses makeActionAwaitable + "point_of_sale.res_partner_action_edit_pos"
 *   with additionalContext: { default_phone, default_mobile }.
 *   This is identical to what pos_store.editPartner() does internally, but
 *   we add phone/mobile defaults so the cashier does not retype the number.
 *
 * ─── Guard conditions (popup is SKIPPED when) ────────────────────────────
 *   • A partner is already linked to the order.
 *   • The order is a return (any line qty < 0) — avoids interrupting the
 *     credit-note / refund flow from pos_credit_note_gift_card.
 *   • The order is not fully covered by payment (get_due() > threshold).
 *     Note: get_due() < 0 means the customer overpaid (change due) — that is
 *     still fully paid and the popup is NOT skipped.
 */

import { patch }                 from "@web/core/utils/patch";
import { PaymentScreen }         from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { makeAwaitable,
         makeActionAwaitable,
         ask }                   from "@point_of_sale/app/store/make_awaitable_dialog";
import { AlertDialog }           from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t }                    from "@web/core/l10n/translation";
import { rpc }                   from "@web/core/network/rpc";
import { LoyaltySelectionPopup } from "./loyalty_selection_popup";

const LOG_PREFIX = "[PaymentScreenLoyaltyPatch]";
const DUE_EPSILON = 0.001;

console.log(LOG_PREFIX, "module loaded.");

// ── Helper: detect return/refund orders ──────────────────────────────────────
function _isReturnOrder(order) {
    const lines = order?.get_orderlines?.() || [];
    return lines.some((l) => (l.qty ?? l.get_quantity?.() ?? 0) < 0);
}

// ── Helper: resolve partner from POS store, or load from server ───────────────
async function _resolvePartner(posStore, partnerData) {
    const pid = partnerData.partner_id;

    // Strategy 1: already in client store
    const cached = posStore.models?.['res.partner']?.get?.(pid);
    if (cached) {
        console.log(LOG_PREFIX, "_resolvePartner: STORE HIT | id=", pid);
        return cached;
    }

    // Strategy 2: load via pos.data.read (populates store)
    if (typeof posStore.data?.read === 'function') {
        try {
            console.log(LOG_PREFIX, "_resolvePartner: loading via pos.data.read | id=", pid);
            await posStore.data.read('res.partner', [pid]);
            const loaded = posStore.models?.['res.partner']?.get?.(pid);
            if (loaded) {
                console.log(LOG_PREFIX, "_resolvePartner: server load OK | id=", pid);
                return loaded;
            }
        } catch (e) {
            console.warn(LOG_PREFIX, "_resolvePartner: pos.data.read failed:", e);
        }
    }

    // Strategy 3: create inline store record
    if (typeof posStore.models?.['res.partner']?.create === 'function') {
        try {
            const rec = posStore.models['res.partner'].create({
                id:            pid,
                name:          partnerData.name          || '',
                display_name:  partnerData.display_name  || partnerData.name || '',
                phone:         partnerData.phone         || '',
                mobile:        partnerData.mobile        || '',
                email:         partnerData.email         || '',
                street:        partnerData.street        || '',
                city:          partnerData.city          || '',
                zip:           partnerData.zip           || '',
                country_id:    partnerData.country_id    || [],
                state_id:      partnerData.state_id      || [],
                vat:           partnerData.vat           || '',
                barcode:       partnerData.barcode       || '',
                write_date:    partnerData.write_date    || '',
                customer_rank: partnerData.customer_rank || 1,
            });
            if (rec) {
                console.log(LOG_PREFIX, "_resolvePartner: inline store create OK | id=", pid);
                return rec;
            }
        } catch (e) {
            console.warn(LOG_PREFIX, "_resolvePartner: inline create failed:", e);
        }
    }

    // Strategy 4: plain-object proxy (last resort)
    console.warn(
        LOG_PREFIX,
        "_resolvePartner: FALLBACK plain-object proxy | id=", pid,
        "— store may be inconsistent."
    );
    return {
        id:           pid,
        name:         partnerData.name         || '',
        display_name: partnerData.display_name || partnerData.name || '',
        phone:        partnerData.phone        || '',
        mobile:       partnerData.mobile       || '',
        write_date:   partnerData.write_date   || '',
    };
}

// ── Patch ────────────────────────────────────────────────────────────────────

patch(PaymentScreen.prototype, {

    /**
     * Open the standard Odoo POS "New Customer" form with phone pre-filled.
     *
     * Mirrors pos_store.editPartner() (pos_store.js ~L1889) but adds
     * additionalContext default_phone / default_mobile so the cashier does
     * not have to retype the number they already entered.
     *
     * Returns the newly created res.partner record (loaded into POS store),
     * or null if the cashier closed the form without saving.
     *
     * @param {string} phone – normalised phone from the loyalty popup
     * @returns {Promise<Object|null>}
     */
    async _openNewPartnerForm(phone) {
        console.log(LOG_PREFIX, "_openNewPartnerForm | phone=", phone);

        try {
            // this.pos.action is the Odoo action service (set in pos_store.js line ~100)
            const record = await makeActionAwaitable(
                this.pos.action,
                "point_of_sale.res_partner_action_edit_pos",
                {
                    props: { resId: undefined },      // undefined resId → new partner form
                    additionalContext: {
                        default_phone:         phone,
                        default_mobile:        phone,
                        default_customer_rank: 1,
                    },
                }
            );

            if (!record) {
                console.log(LOG_PREFIX, "_openNewPartnerForm: form closed without saving.");
                return null;
            }

            console.log(
                LOG_PREFIX, "_openNewPartnerForm: form saved"
                + " | resIds=", JSON.stringify(record.config?.resIds)
            );

            // Load the saved partner into the POS store (same as pos_store.editPartner)
            const newPartners = await this.pos.data.read("res.partner", record.config.resIds);
            const partner = newPartners?.[0] || null;

            console.log(
                LOG_PREFIX, "_openNewPartnerForm: partner loaded"
                + " | id=", partner?.id
                + " | name=", partner?.name
            );

            return partner;

        } catch (err) {
            console.error(LOG_PREFIX, "_openNewPartnerForm error:", err);
            return null;
        }
    },

    /**
     * Override validateOrder to inject the loyalty-customer popup flow.
     *
     * @param {boolean} isForceValidate
     */
    async validateOrder(isForceValidate) {
        const order = this.currentOrder;

        console.log(
            LOG_PREFIX, "validateOrder"
            + " | isForceValidate=",  isForceValidate
            + " | has_partner=",      !!(order?.get_partner?.())
            + " | order_uid=",        order?.uid ?? '?'
        );

        // ── Guard 1: partner already set ──────────────────────────────────
        if (order?.get_partner?.()) {
            console.log(
                LOG_PREFIX, "SKIP popup — partner already set:",
                order.get_partner().name
            );
            return super.validateOrder(isForceValidate);
        }

        // ── Guard 2: return / refund order ─────────────────────────────────
        if (_isReturnOrder(order)) {
            console.log(LOG_PREFIX, "SKIP popup — return order.");
            return super.validateOrder(isForceValidate);
        }

        // ── Guard 3: order not fully paid ──────────────────────────────────
        // Only skip when due > 0 (customer still owes money).
        // due < 0 means the customer overpaid (change is owed back) — that is
        // still a fully-paid state and the popup should appear.
        const due = order?.get_due?.() ?? 0;
        if (due > DUE_EPSILON) {
            console.log(LOG_PREFIX, "SKIP popup — not fully paid | due=", due.toFixed(4));
            return super.validateOrder(isForceValidate);
        }

        // ── Phone entry + search loop (retryable) ─────────────────────────
        // Loop until: partner found, new customer created, or cashier skips.
        let partner = null;

        phoneLoop: while (true) {

            // ── Show loyalty popup ───────────────────────────────────────
            console.log(LOG_PREFIX, "Showing loyalty popup.");
            let popupResult;
            try {
                popupResult = await makeAwaitable(this.dialog, LoyaltySelectionPopup, {
                    title: _t("Link Loyalty Account"),
                });
            } catch (err) {
                console.error(LOG_PREFIX, "Popup error:", err);
                break phoneLoop;
            }

            console.log(
                LOG_PREFIX, "Popup closed | result=",
                popupResult ? JSON.stringify(popupResult) : "undefined (skipped)"
            );

            if (!popupResult?.phone) {
                console.log(LOG_PREFIX, "Popup skipped — exiting loop.");
                break phoneLoop;
            }

            const enteredPhone = popupResult.phone;

            // ── RPC: search for existing partner ────────────────────────
            let searchResult = null;
            try {
                console.log(LOG_PREFIX, "Searching backend | phone=", enteredPhone);
                searchResult = await rpc("/web/dataset/call_kw", {
                    model:  "pos.session",
                    method: "find_or_create_loyalty_customer",
                    args:   [enteredPhone],
                    kwargs: { create_if_not_found: false },
                });
                console.log(
                    LOG_PREFIX, "Backend result"
                    + " | found=",      searchResult?.found
                    + " | partner_id=", searchResult?.partner_id ?? "—"
                    + " | name=",       searchResult?.name ?? "—"
                );
            } catch (rpcErr) {
                console.error(LOG_PREFIX, "RPC error:", rpcErr);
                // On network error: offer retry or skip
                const retry = await ask(this.dialog, {
                    title:        _t("Loyalty Lookup Failed"),
                    body:         _t(
                        "Could not reach the server for '%(phone)s'.\n%(err)s",
                        { phone: enteredPhone, err: rpcErr?.message || String(rpcErr) }
                    ),
                    confirmLabel: _t("Retry"),
                    cancelLabel:  _t("Skip"),
                });
                if (retry) continue phoneLoop;
                break phoneLoop;
            }

            if (searchResult?.found) {
                // ── FOUND: resolve and exit loop ─────────────────────────
                console.log(
                    LOG_PREFIX, "Partner FOUND | partner_id=", searchResult.partner_id
                );
                partner = await _resolvePartner(this.pos, searchResult);
                break phoneLoop;

            } else {
                // ── NOT FOUND: ask cashier what to do ────────────────────
                console.log(
                    LOG_PREFIX, "Partner NOT FOUND | phone=", enteredPhone
                );
                const shouldCreate = await ask(this.dialog, {
                    title:        _t("Customer Not Found"),
                    body:         _t(
                        "No loyalty account found for '%(phone)s'.\n"
                        + "What would you like to do?",
                        { phone: enteredPhone }
                    ),
                    confirmLabel: _t("Create New Customer"),
                    cancelLabel:  _t("Try Another Number"),
                });

                if (shouldCreate) {
                    // Open standard POS new-customer form pre-filled with phone
                    console.log(
                        LOG_PREFIX,
                        "Cashier chose CREATE — opening POS new-customer form."
                    );
                    partner = await this._openNewPartnerForm(enteredPhone);
                    break phoneLoop;   // exit whether form was saved or cancelled
                } else {
                    // Cashier chose RETRY — loop back to phone popup
                    console.log(
                        LOG_PREFIX,
                        "Cashier chose RETRY — showing phone popup again."
                    );
                    continue phoneLoop;
                }
            }
        } // end phoneLoop

        if (!partner) {
            console.log(
                LOG_PREFIX,
                "No partner resolved — validating without partner."
            );
            return super.validateOrder(isForceValidate);
        }

        // ── Set partner + repopulate loyalty couponPointChanges ───────────
        const dueBefore = order.get_due?.() ?? 0;

        console.log(
            LOG_PREFIX, "Setting partner on order"
            + " | id=",         partner.id
            + " | name=",       partner.name
            + " | due_before=", dueBefore.toFixed(4)
        );

        order.set_partner(partner);

        // pos_loyalty's set_partner() override (pos_order.js) CLEARS couponPointChanges
        // for all nominative (loyalty) programs the instant the partner changes.
        // updateRewards() would eventually repopulate them, but it queues via a Mutex
        // and is never awaited before validateOrder serialises the order.
        // Result: _postProcessLoyalty reads empty couponPointChanges →
        //         confirm_coupon_programs is never called → zero points saved to DB.
        //
        // Fix: call orderUpdateLoyaltyPrograms() directly and AWAIT it.
        // This is the same async function that updateRewards() calls internally:
        //   checkMissingCoupons() → cleans stale entries
        //   updatePrograms()      → fetchLoyaltyCard for the partner (creates a local
        //                           card with a negative ID if new customer),
        //                           recalculates earned points via pointsForPrograms(),
        //                           repopulates couponPointChanges[coupon_id] = {points, ...}
        // After this await, couponPointChanges is populated and the full chain works:
        //   pos_loyalty validateOrder → validate_coupon_programs (balance check)
        //   → syncAllOrders → postSyncAllOrders → _postProcessLoyalty
        //   → confirm_coupon_programs → loyalty.card.points updated in DB ✓
        if (typeof this.pos.orderUpdateLoyaltyPrograms === 'function') {
            console.log(
                LOG_PREFIX, "Awaiting orderUpdateLoyaltyPrograms"
                + " to repopulate couponPointChanges for new partner..."
            );
            try {
                await this.pos.orderUpdateLoyaltyPrograms();
                const changeCount = Object.keys(order.uiState.couponPointChanges || {}).length;
                console.log(
                    LOG_PREFIX, "orderUpdateLoyaltyPrograms complete"
                    + " | couponPointChanges entries:", changeCount
                );
                if (changeCount === 0) {
                    console.warn(
                        LOG_PREFIX,
                        "couponPointChanges is still empty after orderUpdateLoyaltyPrograms."
                        + " Possible reasons: no active loyalty program, partner has no"
                        + " applicable program, or loyalty card fetch failed."
                    );
                } else {
                    console.log(
                        LOG_PREFIX, "couponPointChanges populated:",
                        JSON.stringify(
                            Object.values(order.uiState.couponPointChanges).map((pe) => ({
                                coupon_id:  pe.coupon_id,
                                program_id: pe.program_id,
                                points:     pe.points,
                            }))
                        )
                    );
                }
            } catch (loyaltyErr) {
                console.error(
                    LOG_PREFIX,
                    "orderUpdateLoyaltyPrograms threw an error — points may not save:",
                    loyaltyErr
                );
            }
        } else {
            console.warn(
                LOG_PREFIX,
                "this.pos.orderUpdateLoyaltyPrograms not available"
                + " — loyalty points will NOT be saved. (pos_loyalty not installed?)"
            );
        }

        // ── Due-change safety check ────────────────────────────────────────
        const dueAfter = order.get_due?.() ?? 0;
        if (Math.abs(dueAfter - dueBefore) > DUE_EPSILON) {
            console.warn(
                LOG_PREFIX,
                "Order due changed after set_partner + updateLoyaltyPrograms"
                + " | before=", dueBefore.toFixed(4)
                + " | after=",  dueAfter.toFixed(4)
                + " | likely: auto-applied loyalty reward changed order total."
            );
        }

        // ── Force invoice toggle ON ────────────────────────────────────────
        // Customer was assigned via the loyalty popup — always generate an
        // invoice regardless of the allow_pdf_download POS config setting.
        // PDF download is still controlled separately by shouldDownloadInvoice().
        if (!order.is_to_invoice()) {
            order.set_to_invoice(true);
            console.log(LOG_PREFIX, "Invoice toggle forced ON for loyalty-linked customer.");
        }

        // ── Cashier notification ───────────────────────────────────────────
        this.notification?.add(
            _t("Loyalty account linked: %(name)s. Invoice enabled.", { name: partner.name }),
            { type: "success" }
        );

        console.log(LOG_PREFIX, "Calling super.validateOrder.");
        return super.validateOrder(isForceValidate);
    },
});
