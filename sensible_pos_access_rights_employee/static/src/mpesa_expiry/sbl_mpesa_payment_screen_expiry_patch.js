/** @odoo-module */
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { MpesaPaymentScreen } from "@mpesa_c2b_pos/components/MpesaPaymentScreen/MpesaPaymentScreen";

const LOG = "[SBL M-Pesa Expiry][screen]";

patch(MpesaPaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = useService("pos");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.sblMpesaExpiryAuthorization = false;
    },

    async onConfirm() {
        if (!this.canConfirm) return;

        const txn = this.state.selectedTxn;
        const expiryAuthorization = await this.sblEnsureMpesaExpiryAuthorization(txn);
        if (expiryAuthorization === false) {
            console.warn(LOG, "confirm blocked by expiry authorization", {
                transactionId: txn?.id,
                mpesaRef: txn?.mpesa_ref,
                sessionId: this.props.posSessionId,
            });
            await this.mpesaSvc.release(txn.id, this.props.posSessionId);
            this.state.lockToken = null;
            return;
        }

        this.state.confirming = true;
        const result = await this.mpesaSvc.confirm(
            txn.id,
            this.state.lockToken,
            0,
            this.selectedApplyAmount,
            expiryAuthorization || false
        );
        this.state.confirming = false;

        if (result.success) {
            this.props.onPaymentDone(
                result.mpesa_ref,
                result.applied_amount || this.selectedApplyAmount
            );
        } else {
            this.state.status = "error";
            console.error(LOG, "confirm failed", result);
            this.dialog.add(AlertDialog, {
                title: _t("M-Pesa Payment Blocked"),
                body: result.error || _t("M-Pesa payment could not be confirmed."),
            });
        }
    },

    async sblEnsureMpesaExpiryAuthorization(txn) {
        if (!txn?.id) return false;
        console.debug(LOG, "checking expiry on confirm", {
            transactionId: txn.id,
            mpesaRef: txn.mpesa_ref,
            sessionId: this.props.posSessionId,
        });

        let status;
        try {
            status = await rpc("/pos/mpesa/expiry/check", {
                transaction_id: txn.id,
                pos_session_id: this.props.posSessionId,
            });
        } catch (error) {
            console.error(LOG, "expiry check failed", error);
            this.dialog.add(AlertDialog, {
                title: _t("M-Pesa Expiry Check Failed"),
                body: _t("Could not verify the M-Pesa SMS session time. Payment was blocked."),
            });
            return false;
        }

        if (!status?.expired) {
            console.debug(LOG, "M-Pesa SMS valid for current session", status);
            this.sblMpesaExpiryAuthorization = false;
            return false || null;
        }

        const pin = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Expired M-Pesa SMS"),
            subtitle: status.message || _t("Enter authorized employee PIN to use this M-Pesa SMS."),
            formatDisplayedValue: (value) => String(value || "").replace(/./g, "*"),
            placeholder: _t("PIN"),
            confirmButtonLabel: _t("Authorize"),
        });

        if (!pin) {
            console.warn(LOG, "expiry authorization cancelled", status);
            return false;
        }

        const order = this.pos.get_order?.();
        const cashier = this.pos.get_cashier?.();
        let authorization;
        try {
            authorization = await rpc("/pos/mpesa/expiry/authorize", {
                pin,
                transaction_id: txn.id,
                pos_session_id: this.props.posSessionId,
                cashier_id: cashier?.id || false,
                config_id: this.pos.config?.id || false,
                order_reference: order?.pos_reference || order?.name || false,
            });
        } catch (error) {
            console.error(LOG, "expiry authorization RPC failed", error);
            this.dialog.add(AlertDialog, {
                title: _t("Authorization Error"),
                body: _t("Could not validate the employee PIN. Payment was blocked."),
            });
            return false;
        }

        if (!authorization?.approved || !authorization?.token) {
            console.warn(LOG, "expiry authorization denied", authorization);
            this.dialog.add(AlertDialog, {
                title: _t("Authorization Denied"),
                body: authorization?.message || _t("Employee is not allowed to authorize expired M-Pesa SMS payments."),
            });
            return false;
        }

        this.notification?.add(_t("Expired M-Pesa SMS authorized."), { type: "success" });
        this.sblMpesaExpiryAuthorization = {
            token: authorization.token,
            employee_id: authorization.employee_id || false,
        };
        console.info(LOG, "expiry authorization approved", {
            transactionId: txn.id,
            mpesaRef: txn.mpesa_ref,
            employeeId: authorization.employee_id,
        });
        return this.sblMpesaExpiryAuthorization;
    },
});
