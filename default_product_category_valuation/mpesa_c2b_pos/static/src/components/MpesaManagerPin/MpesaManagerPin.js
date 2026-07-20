/**
 * MpesaManagerPin
 * PIN dialog for manager overrides (amount mismatch approval).
 * Validates PIN against Odoo session — does not store PIN client-side.
 */

import { Component, useRef, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

export class MpesaManagerPin extends Component {
    static template = "mpesa_c2b_pos.MpesaManagerPin";
    static props = {
        reason:   String,   // Human-readable reason shown to manager
        onApprove: Function,
        onCancel:  Function,
    };

    setup() {
        this.rpc      = rpc;
        this.pinInput = useRef("pinInput");
        this.state    = useState({ error: "" });
    }

    onKeyUp(ev) {
        if (ev.key === "Enter") this.onConfirm();
    }

    async onConfirm() {
        const pin = this.pinInput.el?.value?.trim();
        if (!pin) {
            this.state.error = "Please enter the manager PIN.";
            return;
        }
        try {
            const result = await this.rpc("/web/dataset/call_kw", {
                model:  "res.users",
                method: "verify_manager_pin",
                args:   [pin],
                kwargs: {},
            });
            if (result) {
                this.props.onApprove();
            } else {
                this.state.error = "Incorrect PIN. Try again.";
                this.pinInput.el.value = "";
            }
        } catch (_err) {
            this.state.error = "PIN verification failed — check connection.";
        }
    }

    onCancel() {
        this.props.onCancel();
    }
}
