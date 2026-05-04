/**
 * @module pos_credit_limit/app/dialogs/overdue_invoices_popup
 *
 * Gate 1.5 — Overdue Invoices block popup.
 *
 * Shown when the customer has at least one posted, unpaid invoice whose
 * invoice_date_due is in the past (payment terms have elapsed).
 *
 * This is an INFORMATIONAL/BLOCK dialog — the cashier cannot proceed with
 * Customer Account payment until the customer settles their overdue balance.
 *
 * Props injected by payment_screen_patch.js:
 *   title              {string}  - Dialog header
 *   partnerName        {string}  - Customer name
 *   overdueCount       {number}  - Number of overdue invoices
 *   overdueAmount      {string}  - Pre-formatted total overdue amount
 *   oldestOverdueDate  {string}  - Oldest invoice_date_due (YYYY-MM-DD)
 *   close              {Function}- Injected by dialog service
 */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class OverdueInvoicesPopup extends Component {
    static template = "pos_credit_limit.OverdueInvoicesPopup";
    static components = { Dialog };
    static props = {
        title:             { type: String },
        partnerName:       { type: String },
        overdueCount:      { type: Number },
        overdueAmount:     { type: String },
        oldestOverdueDate: { type: String },
        close:             { type: Function },
    };
}
