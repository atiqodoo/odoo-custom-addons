/**
 * @module pos_credit_limit/app/dialogs/no_payment_terms_popup
 *
 * Gate 1 blocking dialog component.
 *
 * Displayed when a customer has no property_payment_term_id configured,
 * preventing the Customer Account payment from being added.
 *
 * This component has NO business logic — it is pure UI.
 * All decisions are made in payment_terms_validator.js before this dialog
 * is ever shown.
 *
 * Props (all required, injected by payment_terms_validator.js):
 *   title {string}    - Dialog header text
 *   body  {string}    - Explanation message including the customer name
 *   close {Function}  - Injected automatically by the Odoo dialog service;
 *                       resolves the awaited Promise in the validator
 */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class NoPaymentTermsPopup extends Component {
    static template = "pos_credit_limit.NoPaymentTermsPopup";
    static components = { Dialog };
    static props = {
        title: { type: String },
        body:  { type: String },
        close: { type: Function },
    };
}
