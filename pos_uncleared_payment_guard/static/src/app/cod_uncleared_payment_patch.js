/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { CodOrdersScreen } from "@pos_cod/app/screens/cod_orders_screen/CodOrdersScreen";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { UnclearedPaymentCapturePopup } from "@pos_uncleared_payment_guard/app/dialogs/uncleared_payment_capture_popup";
import { UnclearedPaymentNoticePopup } from "@pos_uncleared_payment_guard/app/dialogs/uncleared_payment_notice_popup";
import {
    upgGetDepositBankJournals,
} from "@pos_uncleared_payment_guard/app/services/uncleared_payment_capture_service";
import {
    upgIsGuardedPaymentMethod,
} from "@pos_uncleared_payment_guard/app/services/uncleared_payment_service";
import { upgLogger } from "@pos_uncleared_payment_guard/app/logger";

function formatAmount(pos, amount) {
    return `${pos.currency?.symbol || ""} ${Number(amount || 0).toFixed(2)}`;
}

async function captureCodDetails(screen, paymentMethod, amount) {
    const bankJournals = upgGetDepositBankJournals(screen.pos);
    if (!bankJournals.length) {
        screen.state.message = "No deposit bank journals configured for uncleared COD payment.";
        screen.state.messageType = "error";
        return null;
    }
    let payload = null;
    await new Promise((resolve) => {
        screen.dialog.add(
            UnclearedPaymentCapturePopup,
            {
                title: "COD Cheque Deposit Details",
                methodName: paymentMethod?.name || "Mapped Payment Method",
                amountText: formatAmount(screen.pos, amount),
                bankJournals,
                onConfirm: (capture) => {
                    payload = {
                        deposit_bank_journal_id: capture.depositBankJournal?.id || false,
                        cheque_bank: (capture.chequeBank || "").trim(),
                        cheque_account_number: (capture.chequeAccountNumber || "").trim(),
                        cheque_number: (capture.chequeNumber || "").trim(),
                        cheque_date: capture.chequeDate || false,
                    };
                },
            },
            { onClose: resolve }
        );
    });
    upgLogger.warn(screen.pos, "COD uncleared capture closed", {
        method: paymentMethod?.name,
        amount,
        captured: Boolean(payload),
        payload,
    });
    return payload;
}

async function showCodNotice(screen, paymentMethod, amount) {
    await new Promise((resolve) => {
        screen.dialog.add(
            UnclearedPaymentNoticePopup,
            {
                title: "COD Uncleared Payment Hold",
                methodName: paymentMethod?.name || "Mapped Payment Method",
                amountText: formatAmount(screen.pos, amount),
                body:
                    "This COD payment is recorded, but the COD card will remain visible until the cheque is fully reconciled in accounting. Manual clearance only marks the COD card as manually cleared.",
            },
            { onClose: resolve }
        );
    });
}

patch(PosStore.prototype, {
    async cod_fetch_pending_orders() {
        const result = await super.cod_fetch_pending_orders(...arguments);
        await this.upg_refresh_cod_uncleared_status();
        return result;
    },

    async upg_refresh_cod_uncleared_status() {
        const ids = (this.cod_pending_orders || []).map((order) => order.server_id || order.id).filter(Boolean);
        if (!ids.length) {
            return;
        }
        try {
            const statuses = await this.data.call("pos.order", "upg_cod_uncleared_status", [ids]);
            this.cod_pending_orders = (this.cod_pending_orders || []).map((order) => ({
                ...order,
                ...(statuses[order.server_id || order.id] || {}),
            }));
            upgLogger.warn(this, "COD uncleared statuses refreshed", { ids, statuses });
        } catch (err) {
            upgLogger.warn(this, "COD uncleared status refresh failed", { error: err?.message || err });
        }
    },

    async cod_collect_payment(
        orderId,
        paymentMethodId,
        amount,
        sessionId = this.session?.id || false,
        action = "payment",
        orderRef = false,
        returnLines = null,
        mpesaRef = false,
        upgCapture = null
    ) {
        if (!upgCapture) {
            return await super.cod_collect_payment(...arguments);
        }
        const payload = {
            order_id: orderId,
            payment_method_id: paymentMethodId,
            amount,
            session_id: sessionId,
            action,
            order_ref: orderRef,
            return_lines: returnLines,
            mpesa_ref: mpesaRef,
            upg_capture: upgCapture,
        };
        upgLogger.warn(this, "COD collect payment with uncleared capture", payload);
        const result = await this.data.call("pos.order", "collect_cod_payment", [payload]);
        if (result.success) {
            await this.cod_fetch_pending_orders();
        }
        return result;
    },
});

patch(CodOrdersScreen.prototype, {
    selectedPaymentMethod() {
        const methodId = Number(this.state.paymentMethodId || 0);
        return (this.paymentMethods || []).find((method) => Number(method.id) === methodId);
    },

    upgCodUnclearedClass(order) {
        const state = order?.upg_cod_uncleared_state;
        return state && state !== "none" ? `upg-cod-uncleared upg-cod-uncleared-${state}` : "";
    },

    upgCodUnclearedLabel(order) {
        return order?.upg_cod_uncleared_label || "";
    },

    async processCod(order, action, amount, returnLines = null) {
        const paymentMethod = this.selectedPaymentMethod();
        const guarded = action === "payment" && upgIsGuardedPaymentMethod(this.pos, paymentMethod);
        let capture = null;
        if (guarded) {
            capture = await captureCodDetails(this, paymentMethod, amount);
            if (!capture) {
                this.state.message = "COD uncleared payment cancelled. No payment was recorded.";
                this.state.messageType = "error";
                return;
            }
            await showCodNotice(this, paymentMethod, amount);
        }

        if (!guarded) {
            return await super.processCod(...arguments);
        }

        if (!this.state.paymentMethodId) {
            this.state.message = "Please select a payment method first.";
            this.state.messageType = "error";
            return;
        }
        if (!amount || amount <= 0) {
            return;
        }
        this.state.collecting = true;
        this.state.message = "";
        try {
            const result = await this.pos.cod_collect_payment(
                this.orderServerId(order),
                this.state.paymentMethodId,
                amount,
                this.pos.session?.id,
                action,
                order.name || order.pos_reference,
                returnLines,
                false,
                capture
            );
            if (result.success) {
                this.state.message = `${result.order_name}: uncleared COD payment recorded (${this.formatCurrency(result.amount)}).`;
                this.state.messageType = "success";
                await this.pos.upg_refresh_cod_uncleared_status();
                upgLogger.warn(this.pos, "COD uncleared action completed", result);
            } else {
                this.state.message = `Error: ${result.message}`;
                this.state.messageType = "error";
            }
        } catch (err) {
            this.state.message = "Network error. Please try again.";
            this.state.messageType = "error";
            upgLogger.warn(this.pos, "COD uncleared action failed", { error: err?.message || err });
        } finally {
            this.state.collecting = false;
        }
    },
});
