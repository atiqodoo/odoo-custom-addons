/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class UnclearedPaymentCapturePopup extends Component {
    static template = "pos_uncleared_payment_guard.UnclearedPaymentCapturePopup";
    static components = { Dialog };
    static props = {
        title: { type: String },
        methodName: { type: String },
        amountText: { type: String, optional: true },
        bankJournals: { type: Array },
        onConfirm: { type: Function },
        close: { type: Function },
    };

    setup() {
        const today = new Date().toISOString().slice(0, 10);
        this.state = useState({
            depositBankJournalId: this.props.bankJournals[0]?.id || "",
            chequeBank: "",
            chequeAccountNumber: "",
            chequeNumber: "",
            chequeDate: today,
            error: "",
        });
        console.warn("[UPG][CapturePopup] opened", {
            methodName: this.props.methodName,
            amountText: this.props.amountText,
            bankJournals: this.props.bankJournals,
        });
    }

    get selectedJournal() {
        const id = Number(this.state.depositBankJournalId || 0);
        return this.props.bankJournals.find((journal) => journal.id === id);
    }

    onInput(field, ev) {
        this.state[field] = ev.target.value;
        this.state.error = "";
    }

    confirm() {
        const payload = {
            depositBankJournal: this.selectedJournal,
            chequeBank: this.state.chequeBank,
            chequeAccountNumber: this.state.chequeAccountNumber,
            chequeNumber: this.state.chequeNumber,
            chequeDate: this.state.chequeDate,
        };
        const missing = [];
        if (!payload.depositBankJournal) missing.push("deposit bank");
        if (!payload.chequeBank?.trim()) missing.push("cheque bank");
        if (!payload.chequeAccountNumber?.trim()) missing.push("cheque account number");
        if (!payload.chequeNumber?.trim()) missing.push("cheque number");
        if (!payload.chequeDate) missing.push("cheque date");
        if (missing.length) {
            this.state.error = `Please enter ${missing.join(", ")}.`;
            console.warn("[UPG][CapturePopup] validation failed", { missing, payload });
            return;
        }
        console.warn("[UPG][CapturePopup] confirmed", payload);
        this.props.onConfirm(payload);
        this.props.close();
    }

    cancel() {
        console.warn("[UPG][CapturePopup] cancelled");
        this.props.close();
    }
}
