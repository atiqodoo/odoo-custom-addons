/** @odoo-module **/

/**
 * ManagerPinDialog
 * ─────────────────
 * OWL dialog component rendered when the cashier attempts to validate
 * an order containing lines priced below cost.
 *
 * Props
 *   invalidLines  {Array<string>}  human-readable list of offending lines
 *   onConfirm     {Function}       called with employeeName when PIN accepted
 *   onCancel      {Function}       called when user dismisses without override
 *   close         {Function}       injected by the dialog service — closes the dialog
 */

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

export class ManagerPinDialog extends Component {
    static template = "pos_block_price_cost.ManagerPinDialog";
    static components = { Dialog };
    static props = {
        invalidLines: Array,
        onConfirm: Function,
        onCancel: Function,
        close: Function,
    };

    setup() {
        this.state = useState({
            pin: "",
            error: "",
            loading: false,
        });
        this.orm = useService("orm");
        this.pos = useService("pos");

        console.log("pos_block_price_cost: ManagerPinDialog mounted");
    }

    // ── PIN pad interactions ──────────────────────────────────────────────────

    addDigit(digit) {
        if (this.state.loading) return;
        if (this.state.pin.length >= 6) return;   // max PIN length = 6
        this.state.pin += String(digit);
        this.state.error = "";
    }

    clearPin() {
        this.state.pin = "";
        this.state.error = "";
    }

    // ── Validation ───────────────────────────────────────────────────────────

    async onValidate() {
        if (!this.state.pin) {
            this.state.error = _t("Please enter a PIN.");
            return;
        }

        this.state.loading = true;
        this.state.error = "";

        try {
            // pos.session record is the currently open session
            const sessionId = this.pos.session.id;

            const result = await this.orm.call(
                "pos.session",
                "validate_manager_pin",
                [[sessionId], this.state.pin]
            );

            console.log("pos_block_price_cost: validate_manager_pin result →", result);

            if (result.valid) {
                this.props.close();
                this.props.onConfirm(result.employee_name);
            } else {
                const reasonMessages = {
                    invalid_pin:  _t("Invalid PIN. Please try again."),
                    not_manager:  _t("This employee is not a POS Manager."),
                    config_error: _t("System configuration error. Contact your administrator."),
                    no_pin:       _t("No PIN entered."),
                };
                this.state.error =
                    reasonMessages[result.reason] || _t("Override denied.");
                this.state.pin = "";   // clear so cashier can re-enter
            }
        } catch (err) {
            console.error("pos_block_price_cost: PIN validation RPC error →", err);
            this.state.error = _t("Server error. Please try again.");
            this.state.pin = "";
        } finally {
            this.state.loading = false;
        }
    }

    onCancel() {
        console.log("pos_block_price_cost: Manager override cancelled by cashier");
        this.props.close();
        this.props.onCancel();
    }
}