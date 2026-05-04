/**
 * @module pos_credit_limit/app/dialogs/return_blocked_popup
 *
 * Issue 5 — Return on Account blocked dialog.
 *
 * Shown when the cashier tries to process a product return on Customer
 * Account but the original POS order either:
 *   (a) Had no customer assigned, OR
 *   (b) Was assigned to a DIFFERENT customer than the one currently
 *       on the return order.
 *
 * Either scenario would fraudulently credit the wrong account.
 *
 * Props injected by payment_screen_patch.js:
 *   title  {string}   - Dialog header
 *   body   {string}   - Explanation message (includes partner name and reason)
 *   close  {Function} - Injected by dialog service; resolves awaited Promise
 */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class ReturnBlockedPopup extends Component {
    static template = "pos_credit_limit.ReturnBlockedPopup";
    static components = { Dialog };
    static props = {
        title: { type: String },
        body:  { type: String },
        close: { type: Function },
    };
}
