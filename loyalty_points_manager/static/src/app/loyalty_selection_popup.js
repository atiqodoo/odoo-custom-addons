/** @odoo-module **/

/**
 * loyalty_selection_popup.js
 *
 * OWL dialog component rendered by the PaymentScreen loyalty patch when the
 * cashier validates an order that has no customer linked.
 *
 * ─── Integration pattern ──────────────────────────────────────────────────
 *   Designed for use with makeAwaitable() from
 *   @point_of_sale/app/store/make_awaitable_dialog.
 *
 *   Odoo 18 makeAwaitable injects TWO props:
 *     • getPayload(value) — stores the resolve value (called by onConfirm)
 *     • close()           — dismisses the dialog; onClose fires → promise resolves
 *                           with the last value passed to getPayload, or undefined
 *
 *   Confirm:  getPayload({ phone }) → close()  →  resolves with { phone }
 *   Skip / X: close() only          →           →  resolves with undefined
 *
 * ─── Auto-focus & barcode ─────────────────────────────────────────────────
 *   onMounted() focuses the input immediately so the cashier can type or scan
 *   a loyalty barcode without clicking the input first.
 *
 * ─── Keyboard shortcuts ───────────────────────────────────────────────────
 *   Enter  → confirm  (same as "Confirm" button)
 *   Escape → skip     (same as "Skip" button / Dialog X)
 */

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

const LOG_PREFIX = "[LoyaltySelectionPopup]";

export class LoyaltySelectionPopup extends Component {
    static template  = "loyalty_points_manager.LoyaltySelectionPopup";
    static components = { Dialog };
    static props = {
        /**
         * Injected by DialogWrapper (dialog service).
         * Calling this closes the dialog and triggers the onClose callback,
         * which resolves the makeAwaitable promise with whatever value was
         * last stored via getPayload().
         */
        close: { type: Function },
        /**
         * Injected by makeAwaitable.
         * Stores the resolve-value before we call close().
         * Pattern: getPayload(value) → close() → promise resolves with value.
         * If never called, close() alone resolves the promise with undefined.
         */
        getPayload: { type: Function },
        /** Optional dialog heading override. */
        title: { type: String, optional: true },
    };

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    setup() {
        this.state = useState({
            phone:    '',
            errorMsg: '',
        });

        this.inputRef = useRef("phoneInput");

        onMounted(() => {
            // Auto-focus so the cashier can immediately type / scan.
            const el = this.inputRef.el;
            if (el) {
                el.focus();
                console.log(LOG_PREFIX, "mounted — input focused.");
            } else {
                console.warn(LOG_PREFIX, "mounted — could not find phoneInput ref.");
            }
        });

        console.log(LOG_PREFIX, "setup() complete.");
    }

    // ── Computed ──────────────────────────────────────────────────────────────

    get titleText() {
        return this.props.title || _t("Link Loyalty Account");
    }

    /**
     * True when the input contains at least one non-whitespace character.
     * Used to disable/enable the Confirm button reactively.
     */
    get canConfirm() {
        return this.state.phone.trim().length > 0;
    }

    // ── Event handlers ────────────────────────────────────────────────────────

    onPhoneInput(ev) {
        this.state.phone    = ev.target.value || '';
        this.state.errorMsg = '';          // clear any previous error on new input

        console.debug(
            LOG_PREFIX, "onPhoneInput | value=", JSON.stringify(this.state.phone)
        );
    }

    onKeydown(ev) {
        if (ev.key === 'Enter') {
            console.log(LOG_PREFIX, "onKeydown: Enter → onConfirm");
            ev.preventDefault();
            this.onConfirm();
        } else if (ev.key === 'Escape') {
            console.log(LOG_PREFIX, "onKeydown: Escape → onSkip");
            ev.preventDefault();
            this.onSkip();
        }
    }

    /**
     * Confirm — validate client-side, store the payload, then close.
     *
     * makeAwaitable pattern:
     *   1. getPayload({ phone }) — stores the resolve value
     *   2. close()               — closes dialog → onClose fires → promise resolves
     */
    onConfirm() {
        const phone = this.state.phone.trim();

        if (!phone) {
            this.state.errorMsg = _t("Please enter a phone number or loyalty ID.");
            console.warn(LOG_PREFIX, "onConfirm: empty input — showing error.");
            return;
        }

        console.log(LOG_PREFIX, "onConfirm | phone=", phone);
        this.props.getPayload({ phone });   // set resolve value
        this.props.close();                 // dismiss → promise resolves with { phone }
    }

    /**
     * Skip — close without calling getPayload.
     * onClose fires with undefined → caller treats undefined as "no phone entered".
     */
    onSkip() {
        console.log(LOG_PREFIX, "onSkip — closing without partner.");
        this.props.close();   // getPayload never called → resolves with undefined
    }
}
