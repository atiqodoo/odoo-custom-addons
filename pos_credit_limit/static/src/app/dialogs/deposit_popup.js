/**
 * @module pos_credit_limit/app/dialogs/deposit_popup
 *
 * Issue 1 — Customer Deposit path.
 *
 * Shown when the customer has a prepaid deposit (partner.credit < 0)
 * and their order total is within the deposit balance.
 *
 * This is an INFORMATIONAL dialog — it confirms the cashier that the
 * payment will draw from the customer's deposit, not a credit line.
 * No credit limit is consumed.
 *
 * Props injected by credit_limit_validator.js:
 *   title          {string}  - Dialog header
 *   depositBalance {string}  - Pre-formatted deposit amount (e.g. "KES 500.00")
 *   orderTotal     {string}  - Pre-formatted current order total
 *   close          {Function}- Injected by dialog service; resolves awaited Promise
 */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class DepositPopup extends Component {
    static template = "pos_credit_limit.DepositPopup";
    static components = { Dialog };
    static props = {
        title:          { type: String },
        depositBalance: { type: String },
        orderTotal:     { type: String },
        close:          { type: Function },
    };
}

/**
 * Scenario A2 — Partial deposit path (Issue 2).
 *
 * Shown when the order total exceeds the customer's deposit balance.
 * Allows the cashier to charge the deposit amount on Customer Account
 * and collect the remainder by cash, card, or another method.
 *
 * Two outcomes:
 *   props.onConfirm() — cashier confirms → payment line added with amount = depositBalance
 *   props.close()     — cashier cancels  → payment line NOT added
 *
 * Props injected by credit_limit_validator.js:
 *   title           {string}   - Dialog header
 *   depositBalance  {string}   - Pre-formatted effective deposit available
 *   orderTotal      {string}   - Pre-formatted current order total
 *   remainingAmount {string}   - Pre-formatted amount to pay by another method
 *   onConfirm       {Function} - Called when cashier confirms partial deposit charge
 *   close           {Function} - Injected by dialog service; resolves awaited Promise
 */
export class DepositPartialPopup extends Component {
    static template = "pos_credit_limit.DepositPartialPopup";
    static components = { Dialog };
    static props = {
        title:           { type: String },
        depositBalance:  { type: String },
        orderTotal:      { type: String },
        remainingAmount: { type: String },
        onConfirm:       { type: Function },
        close:           { type: Function },
    };
}
