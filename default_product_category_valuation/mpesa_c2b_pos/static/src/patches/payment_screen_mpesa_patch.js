/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { rpc } from "@web/core/network/rpc";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { MpesaPaymentScreen } from "../components/MpesaPaymentScreen/MpesaPaymentScreen";

function isMpesaMethod(paymentMethod) {
    return Boolean(paymentMethod?.is_mpesa);
}

patch(PaymentScreen.prototype, {
    deletePaymentLine(uuid) {
        const line = this.paymentLines.find((line) => line.uuid === uuid);
        const releaseRef = line?.mpesa_ref && isMpesaMethod(line.payment_method_id)
            ? line.mpesa_ref
            : "";
        const releaseAmount = releaseRef ? Number(line.amount || 0) : 0;
        const reservationToken = line?.mpesa_reservation_token || "";
        const orderUuid = line?.pos_order_id?.uuid || this.currentOrder?.uuid || "";
        const result = super.deletePaymentLine(...arguments);
        if (releaseRef) {
            const route = reservationToken
                ? "/pos/mpesa/reservation/abandon"
                : "/pos/mpesa/release";
            const payload = reservationToken
                ? {
                    token: reservationToken,
                    order_uuid: orderUuid,
                    reason: "payment_line_deleted",
                }
                : {
                    transaction_id: 0,
                    pos_session_id: this.pos.session.id,
                    mpesa_ref: releaseRef,
                    release_amount: releaseAmount,
                };
            void rpc(route, payload).catch((err) => {
                console.warn("[M-Pesa POS] release after payment line delete failed", err);
            });
        }
        return result;
    },

    async addNewPaymentLine(paymentMethod) {
        if (!isMpesaMethod(paymentMethod)) {
            return await super.addNewPaymentLine(...arguments);
        }

        console.log("[M-Pesa POS] intercepted payment method", {
            id: paymentMethod.id,
            name: paymentMethod.name,
            is_mpesa: paymentMethod.is_mpesa,
        });

        const due = this.currentOrder.get_due();
        if (due <= 0) {
            this.dialog.add(AlertDialog, {
                title: _t("Nothing to Pay"),
                body: _t("This order has no remaining amount due."),
            });
            return false;
        }

        const result = await new Promise((resolve) => {
            let closeDialog;
            let resolved = false;
            const finish = (value) => {
                if (resolved) {
                    return;
                }
                resolved = true;
                resolve(value);
            };

            closeDialog = this.dialog.add(
                MpesaPaymentScreen,
                {
                    orderAmount: due,
                    posSessionId: this.pos.session.id,
                    orderUuid: this.currentOrder?.uuid || "",
                    onPaymentDone: (mpesaRef, amount, reservationToken, reservationState) => {
                        finish({ mpesaRef, amount, reservationToken, reservationState });
                        closeDialog();
                    },
                    onPaymentCancel: () => {
                        finish(false);
                        closeDialog();
                    },
                },
                { onClose: () => finish(false) }
            );
        });

        if (!result) {
            return false;
        }

        const added = await super.addNewPaymentLine(paymentMethod);
        if (!added) {
            const route = result.reservationToken
                ? "/pos/mpesa/reservation/abandon"
                : "/pos/mpesa/release";
            const payload = result.reservationToken
                ? {
                    token: result.reservationToken,
                    order_uuid: this.currentOrder?.uuid || "",
                    reason: "payment_line_add_failed",
                }
                : {
                    transaction_id: 0,
                    pos_session_id: this.pos.session.id,
                    mpesa_ref: result.mpesaRef,
                    release_amount: result.amount,
                };
            await rpc(route, payload).catch((err) => {
                console.warn("[M-Pesa POS] release after failed payment line add failed", err);
            });
            return false;
        }

        const line = this.selectedPaymentLine;
        if (line) {
            line.set_amount(result.amount);
            line.update({
                mpesa_ref: result.mpesaRef,
                mpesa_reservation_token: result.reservationToken || false,
                mpesa_reservation_state: result.reservationState || "legacy_confirmed",
            });
        }
        this.notification.add(_t("M-Pesa payment %s accepted.", result.mpesaRef), {
            type: "success",
        });
        return true;
    },
});
