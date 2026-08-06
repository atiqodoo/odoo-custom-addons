/** @odoo-module */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class UnclearedPaymentNoticePopup extends Component {
    static template = "pos_uncleared_payment_guard.UnclearedPaymentNoticePopup";
    static components = { Dialog };
    static props = {
        title: { type: String },
        body: { type: String },
        methodName: { type: String },
        amountText: { type: String, optional: true },
        close: { type: Function },
    };
}
