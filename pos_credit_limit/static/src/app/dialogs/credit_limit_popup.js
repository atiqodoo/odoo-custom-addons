/**
 * @module pos_credit_limit/app/dialogs/credit_limit_popup
 *
 * Gate 2 blocking dialog component.
 *
 * Displays a full True Balance breakdown when the customer's credit ceiling
 * would be exceeded by the current order. The breakdown helps the cashier
 * explain to the customer exactly why the payment was blocked and by how much.
 *
 * Also used for the "Insufficient Deposit" path (Issue 1) when a customer
 * has a deposit but the order total exceeds it. In that case `depositBalance`
 * is non-empty and shown in the table.
 *
 * This component has NO business logic — it is pure UI.
 * All calculations are performed in credit_limit_validator.js and
 * true_balance_calculator.js before the dialog is shown.
 *
 * Props (all required unless marked optional):
 *   title          {string}          - Dialog header
 *   backendBalance {string}          - Pre-formatted raw total_due from server
 *   depositBalance {string}          - Pre-formatted deposit amount (optional;
 *                                      shown only when non-empty/non-zero string)
 *   unsyncedAmount {string}          - Pre-formatted unsynced credit charges
 *   trueBalance    {string}          - Pre-formatted True Balance
 *   orderTotal     {string}          - Pre-formatted current order total
 *   totalExposure  {string}          - Pre-formatted trueBalance + orderTotal
 *   creditLimit    {string}          - Pre-formatted credit ceiling
 *   close          {Function}        - Injected by dialog service
 */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class CreditLimitPopup extends Component {
    static template = "pos_credit_limit.CreditLimitPopup";
    static components = { Dialog };
    static props = {
        title:          { type: String },
        backendBalance: { type: String },
        depositBalance: { type: String, optional: true },
        unsyncedAmount: { type: String },
        trueBalance:    { type: String },
        orderTotal:     { type: String },
        totalExposure:  { type: String },
        creditLimit:    { type: String },
        close:          { type: Function },
    };
}
