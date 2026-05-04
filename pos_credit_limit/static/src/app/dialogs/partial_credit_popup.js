/**
 * @module pos_credit_limit/app/dialogs/partial_credit_popup
 *
 * Issue 2 — Partial Credit path.
 *
 * Shown when the order total exceeds the credit limit, but the customer
 * still has SOME available credit. Allows the cashier to charge the
 * available amount on account and pay the rest by another method.
 *
 * Two outcomes:
 *   props.onConfirm() — cashier clicks "Charge on Account" → payment line is added
 *                        with amount preset to availableCredit
 *   props.close()     — cashier clicks "Cancel" → payment line is NOT added
 *
 * Props injected by credit_limit_validator.js:
 *   title           {string}   - Dialog header
 *   trueBalance     {string}   - Pre-formatted existing balance
 *   creditLimit     {string}   - Pre-formatted credit ceiling
 *   availableCredit {string}   - Pre-formatted headroom (creditLimit - trueBalance)
 *   orderTotal      {string}   - Pre-formatted current order total
 *   remainingAmount {string}   - Pre-formatted amount to pay by another method
 *   onConfirm       {Function} - Called when cashier confirms partial charge
 *   close           {Function} - Injected by dialog service; resolves awaited Promise
 */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class PartialCreditPopup extends Component {
    static template = "pos_credit_limit.PartialCreditPopup";
    static components = { Dialog };
    static props = {
        title:           { type: String },
        trueBalance:     { type: String },
        creditLimit:     { type: String },
        availableCredit: { type: String },
        orderTotal:      { type: String },
        remainingAmount: { type: String },
        onConfirm:       { type: Function },
        close:           { type: Function },
    };
}
