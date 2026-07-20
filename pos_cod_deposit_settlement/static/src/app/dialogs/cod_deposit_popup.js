/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { cddsWarn } from "@pos_cod_deposit_settlement/app/utils/cod_deposit_logger";

export class CodDepositPopup extends Component {
    static template = "pos_cod_deposit_settlement.CodDepositPopup";
    static components = { Dialog };
    static props = {
        title: { type: String },
        quote: { type: Object },
        onConfirm: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.state = useState({ amount: Number(this.props.quote.maximum_amount || 0).toFixed(2), error: "" });
        cddsWarn(null, "POPUP", "opened", this.props.quote);
    }

    money(value) {
        return `${this.props.quote.currency_symbol || ""}${Number(value || 0).toFixed(2)}`;
    }

    onAmount(ev) {
        this.state.amount = ev.target.value;
        this.state.error = "";
    }

    confirm() {
        const amount = Number(this.state.amount || 0);
        const maximum = Number(this.props.quote.maximum_amount || 0);
        if (!amount || amount <= 0) {
            this.state.error = "Enter an amount greater than zero.";
            return;
        }
        if (amount > maximum + 0.001) {
            this.state.error = `Maximum available is ${this.money(maximum)}.`;
            return;
        }
        this.props.onConfirm(amount);
        this.props.close();
    }
}
