/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { sblGuardedAction } from "@sensible_pos_access_rights_employee/authorization/sbl_authorization";
import {
    isMpesaPaymentMethod,
    openMpesaPaymentDialog,
} from "../utils/mpesa_payment_dialog";

function isEmptyCustomerSettlementOrder(order) {
    const partner = order?.get_partner?.() || order?.partner_id;
    const lines = order?.get_orderlines?.() || order?.lines || [];
    return Boolean(partner) && lines.length === 0;
}

function mpesaLinesMissingReference(order) {
    return (order?.payment_ids || []).filter(
        (line) =>
            isMpesaPaymentMethod(line.payment_method_id) &&
            Number((line.get_amount?.() ?? line.amount) || 0) > 0 &&
            !line.mpesa_ref
    );
}

patch(PaymentScreen.prototype, {
    async addNewPaymentLine(paymentMethod) {
        const order = this.currentOrder;
        if (!isMpesaPaymentMethod(paymentMethod) || !isEmptyCustomerSettlementOrder(order)) {
            return await super.addNewPaymentLine(...arguments);
        }

        const allowed = await sblGuardedAction(
            this.pos,
            this.dialog,
            this.notification,
            "deposit_settle_payment_method",
            () => true,
            {
                label: _t("Deposit / Due Settlement: %s", paymentMethod.name),
                paymentMethod,
            }
        );
        if (!allowed) {
            console.warn("[M-Pesa POS][deposit] authorization blocked", {
                method: paymentMethod?.name,
            });
            return false;
        }

        this.numberBuffer?.reset?.();
        const amount = Number(
            await makeAwaitable(this.dialog, NumberPopup, {
                title: _t("M-Pesa Deposit Amount"),
                startingValue: 0,
                placeholder: _t("Amount"),
            })
        );
        if (!amount || amount <= 0) {
            console.warn("[M-Pesa POS][deposit] cancelled or invalid amount", { amount });
            return false;
        }

        const mpesaResult = await openMpesaPaymentDialog(this.dialog, {
            orderAmount: amount,
            posSessionId: this.pos.session.id,
            context: "deposit_add_payment_line",
        });
        if (!mpesaResult) {
            console.warn("[M-Pesa POS][deposit] M-Pesa validation cancelled");
            return false;
        }

        const line = order.add_paymentline(paymentMethod);
        if (!line) {
            return false;
        }
        line.set_amount(Number(mpesaResult.amount || amount));
        line.update({ mpesa_ref: mpesaResult.mpesaRef });
        console.warn("[M-Pesa POS][deposit] payment line added", {
            order: order.name || order.uuid,
            method: paymentMethod?.name,
            amount: line.get_amount?.() ?? line.amount,
            mpesaRef: mpesaResult.mpesaRef,
        });
        return true;
    },

    async validateOrder(isForceValidate) {
        const order = this.currentOrder;
        if (isEmptyCustomerSettlementOrder(order)) {
            for (const line of mpesaLinesMissingReference(order)) {
                const amount = Number((line.get_amount?.() ?? line.amount) || 0);
                const mpesaResult = await openMpesaPaymentDialog(this.dialog, {
                    orderAmount: amount,
                    posSessionId: this.pos.session.id,
                    context: "deposit_validate_order",
                });
                if (!mpesaResult) {
                    console.warn("[M-Pesa POS][deposit] validation blocked: missing M-Pesa ref", {
                        order: order.name || order.uuid,
                        amount,
                    });
                    return false;
                }
                line.set_amount(Number(mpesaResult.amount || amount));
                line.update({ mpesa_ref: mpesaResult.mpesaRef });
            }
        }
        return await super.validateOrder(...arguments);
    },
});
