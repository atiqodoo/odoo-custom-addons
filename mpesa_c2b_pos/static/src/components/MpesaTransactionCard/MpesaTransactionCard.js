/**
 * MpesaTransactionCard
 * Displays a single matched M-Pesa transaction.
 * Purely presentational — emits onSelect upward, never calls RPC.
 */

import { Component } from "@odoo/owl";

export class MpesaTransactionCard extends Component {
    static template = "mpesa_c2b_pos.MpesaTransactionCard";
    static props = {
        txn:         Object,   // transaction object from validate response
        orderAmount: Number,
        selected:    Boolean,
        onSelect:    Function,
    };

    get matchLabel() {
        const labels = {
            exact:        "EXACT MATCH",
            overpayment:  "OVERPAYMENT",
            underpayment: "UNDERPAYMENT",
        };
        return labels[this.props.txn.match_type] || this.props.txn.match_type;
    }

    formatAmount(val) {
        return `Ksh ${Number(val).toLocaleString("en-KE", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        })}`;
    }

    formatTime(isoString) {
        if (!isoString) return "—";
        const d = new Date(isoString);
        const now = new Date();
        const diffMin = Math.round((now - d) / 60000);
        const timeStr = d.toLocaleTimeString("en-KE", { hour: "2-digit", minute: "2-digit" });
        if (diffMin < 1)  return `Just now (${timeStr})`;
        if (diffMin < 60) return `${diffMin} min ago (${timeStr})`;
        return timeStr;
    }
}
